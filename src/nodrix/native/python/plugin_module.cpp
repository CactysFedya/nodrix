#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <exception>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#include "nodrix/buffer.hpp"
#include "nodrix/c_api.h"
#include "nodrix/message.hpp"
#include "nodrix/node.hpp"

namespace vp = nodrix;

namespace {

struct DynamicLibrary {
#if defined(_WIN32)
  HMODULE handle{nullptr};
#else
  void* handle{nullptr};
#endif

  ~DynamicLibrary() { close(); }

  void open(const char* path) {
#if defined(_WIN32)
    handle = LoadLibraryA(path);
    if (!handle) throw std::runtime_error("LoadLibrary failed");
#else
    handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
      const char* error = dlerror();
      throw std::runtime_error(error ? error : "dlopen failed");
    }
#endif
  }

  void* symbol(const char* name) {
#if defined(_WIN32)
    void* value = reinterpret_cast<void*>(GetProcAddress(handle, name));
#else
    dlerror();
    void* value = dlsym(handle, name);
#endif
    if (!value) throw std::runtime_error(std::string("Missing Plugin C ABI 2.0 symbol: ") + name);
    return value;
  }

  void close() noexcept {
    if (!handle) return;
#if defined(_WIN32)
    FreeLibrary(handle);
#else
    dlclose(handle);
#endif
    handle = nullptr;
  }
};

struct PythonBufferContext {
  Py_buffer view{};
  std::atomic<std::size_t> references{1};
};

void retain_python_buffer(void* opaque) {
  if (auto* context = static_cast<PythonBufferContext*>(opaque)) {
    context->references.fetch_add(1, std::memory_order_relaxed);
  }
}

void release_python_buffer_owner(void* opaque) {
  auto* context = static_cast<PythonBufferContext*>(opaque);
  if (!context) return;
  if (context->references.fetch_sub(1, std::memory_order_acq_rel) != 1) return;
  PyGILState_STATE state = PyGILState_Ensure();
  PyBuffer_Release(&context->view);
  delete context;
  PyGILState_Release(state);
}

typedef struct {
  PyObject_HEAD
  vp::Buffer* buffer;
  int readonly;
} NativeBufferViewObject;

PyTypeObject NativeBufferViewType = {PyVarObject_HEAD_INIT(nullptr, 0)};

PyObject* NativeBufferView_from_buffer(vp::Buffer buffer, int readonly = 1) {
  auto* result = reinterpret_cast<NativeBufferViewObject*>(
      NativeBufferViewType.tp_alloc(&NativeBufferViewType, 0));
  if (!result) return nullptr;
  result->buffer = new vp::Buffer(std::move(buffer));
  result->readonly = readonly;
  return reinterpret_cast<PyObject*>(result);
}

void NativeBufferView_dealloc(NativeBufferViewObject* self) {
  delete self->buffer;
  self->buffer = nullptr;
  Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}

int NativeBufferView_getbuffer(
    NativeBufferViewObject* self, Py_buffer* view, int flags) {
  if (!self->buffer || !*self->buffer) {
    PyErr_SetString(PyExc_BufferError, "native plugin buffer is empty");
    return -1;
  }
  return PyBuffer_FillInfo(
      view,
      reinterpret_cast<PyObject*>(self),
      self->buffer->data(),
      static_cast<Py_ssize_t>(self->buffer->size()),
      self->readonly,
      flags);
}

void NativeBufferView_releasebuffer(NativeBufferViewObject*, Py_buffer*) {}

PyObject* NativeBufferView_get_nbytes(NativeBufferViewObject* self, void*) {
  return PyLong_FromSize_t(self->buffer ? self->buffer->size() : 0);
}

PyGetSetDef NativeBufferView_getset[] = {
    {const_cast<char*>("nbytes"),
     reinterpret_cast<getter>(NativeBufferView_get_nbytes),
     nullptr,
     const_cast<char*>("Buffer size in bytes."),
     nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

PyBufferProcs NativeBufferView_buffer_procs = {
    reinterpret_cast<getbufferproc>(NativeBufferView_getbuffer),
    reinterpret_cast<releasebufferproc>(NativeBufferView_releasebuffer),
};

std::string python_text(PyObject* value) {
  PyObject* text = PyObject_Str(value);
  if (!text) throw std::runtime_error("cannot convert message field to text");
  Py_ssize_t size = 0;
  const char* utf8 = PyUnicode_AsUTF8AndSize(text, &size);
  if (!utf8) {
    Py_DECREF(text);
    throw std::runtime_error("message text field is not valid UTF-8");
  }
  std::string result(utf8, static_cast<std::size_t>(size));
  Py_DECREF(text);
  return result;
}

std::string message_text_attribute(
    PyObject* message, const char* name, bool optional = false) {
  PyObject* value = PyObject_GetAttrString(message, name);
  if (!value) {
    if (optional) {
      PyErr_Clear();
      return {};
    }
    throw std::runtime_error(std::string("message is missing field ") + name);
  }
  try {
    std::string result = python_text(value);
    Py_DECREF(value);
    return result;
  } catch (...) {
    Py_DECREF(value);
    throw;
  }
}

nodrix_string_view_v2 string_view(const std::string& value) noexcept {
  return {
      sizeof(nodrix_string_view_v2),
      value.empty() ? nullptr : value.data(),
      value.size(),
  };
}

std::string copy_string_view(
    const nodrix_string_view_v2& value, const char* field) {
  if (value.struct_size < NODRIX_STRING_VIEW_V2_REQUIRED_SIZE) {
    throw std::runtime_error(
        std::string("plugin emitted an undersized correlation field: ") + field);
  }
  if (value.size > 0 && !value.data) {
    throw std::runtime_error(
        std::string("plugin emitted a null correlation field: ") + field);
  }
  return value.size ? std::string(value.data, value.size) : std::string{};
}

bool valid_memory_domain(std::uint32_t domain) noexcept {
  switch (domain) {
    case NODRIX_MEMORY_HOST:
    case NODRIX_MEMORY_PINNED_HOST:
    case NODRIX_MEMORY_SHARED:
    case NODRIX_MEMORY_DMABUF:
    case NODRIX_MEMORY_CUDA:
    case NODRIX_MEMORY_ROCM:
    case NODRIX_MEMORY_VULKAN:
    case NODRIX_MEMORY_OPENCL:
    case NODRIX_MEMORY_METAL:
    case NODRIX_MEMORY_NPU:
    case NODRIX_MEMORY_DLPACK:
    case NODRIX_MEMORY_EXTERNAL:
      return true;
    default:
      return false;
  }
}

bool valid_port_memory(const std::string& memory) {
  return memory == "any" || memory == "cpu" ||
         memory == "pinned_cpu" || memory == "shared" ||
         memory == "dma_buf" || memory == "cuda" ||
         memory == "rocm" || memory == "vulkan" ||
         memory == "opencl" || memory == "metal" ||
         memory == "npu" || memory == "dlpack" ||
         memory == "external";
}

struct InputMessage {
  nodrix_message_v2 value{};
  PythonBufferContext* context{nullptr};
  std::string pipeline_id;
  std::string run_id;
  std::string source_id;
  std::string stream_id;
  std::string trace_id;
  std::string span_id;

  ~InputMessage() {
    if (context) release_python_buffer_owner(context);
  }
};

std::unique_ptr<InputMessage> absent_input_message(
    const std::string& type) {
  auto result = std::make_unique<InputMessage>();
  result->value.struct_size = sizeof(nodrix_message_v2);
  result->value.type_id = vp::fnv1a_64(type);
  result->value.correlation = {
      sizeof(nodrix_correlation_v2),
      0,
      string_view(result->pipeline_id),
      string_view(result->run_id),
      string_view(result->source_id),
      string_view(result->stream_id),
      string_view(result->trace_id),
      string_view(result->span_id),
  };
  result->value.present = 0;
  result->value.payload.struct_size = sizeof(nodrix_buffer_v2);
  result->value.payload.memory = {
      sizeof(nodrix_memory_handle_v2),
      NODRIX_MEMORY_HOST,
      0,
      0,
      0,
      0,
      NODRIX_MEMORY_FLAG_HOST_VISIBLE |
          NODRIX_MEMORY_FLAG_READ_ONLY,
      nullptr,
      nullptr,
      nullptr,
  };
  return result;
}

std::unique_ptr<InputMessage> message_from_python(PyObject* message) {
  auto result = std::make_unique<InputMessage>();
  PyObject* sequence = PyObject_GetAttrString(message, "sequence");
  PyObject* timestamp = PyObject_GetAttrString(message, "timestamp_ns");
  PyObject* trace = PyObject_GetAttrString(message, "trace_id");
  PyObject* payload = PyObject_GetAttrString(message, "payload");
  if (!sequence || !timestamp || !trace || !payload) {
    Py_XDECREF(sequence);
    Py_XDECREF(timestamp);
    Py_XDECREF(trace);
    Py_XDECREF(payload);
    throw std::runtime_error("invalid Nodrix Message object");
  }

  const std::string type_text = message_text_attribute(message, "type");
  result->pipeline_id = message_text_attribute(message, "pipeline_id");
  result->run_id = message_text_attribute(message, "run_id");
  result->source_id = message_text_attribute(message, "source_id");
  result->stream_id = message_text_attribute(message, "stream_id");
  result->trace_id = python_text(trace);
  result->span_id = message_text_attribute(message, "span_id", true);

  auto* context = new PythonBufferContext();
  if (PyObject_GetBuffer(payload, &context->view, PyBUF_CONTIG_RO) != 0) {
    Py_DECREF(sequence);
    Py_DECREF(timestamp);
    Py_DECREF(trace);
    Py_DECREF(payload);
    delete context;
    throw std::runtime_error(
        "native nodes require a contiguous buffer-protocol payload; use "
        "Frame.buffer.owner, Tensor.buffer.owner, bytes, memoryview, or NativeBuffer");
  }
  result->context = context;
  result->value.struct_size = sizeof(nodrix_message_v2);
  result->value.type_id = vp::fnv1a_64(type_text);
  result->value.sequence = PyLong_AsUnsignedLongLong(sequence);
  result->value.source_timestamp_ns = PyLong_AsLongLong(timestamp);
  result->value.runtime_timestamp_ns = vp::steady_time_ns();
  result->value.correlation = {
      sizeof(nodrix_correlation_v2),
      PyLong_Check(trace) ? NODRIX_CORRELATION_TRACE_ID_INTEGER : 0u,
      string_view(result->pipeline_id),
      string_view(result->run_id),
      string_view(result->source_id),
      string_view(result->stream_id),
      string_view(result->trace_id),
      string_view(result->span_id),
  };
  result->value.present = 1;
  result->value.payload.struct_size = sizeof(nodrix_buffer_v2);
  result->value.payload.data =
      static_cast<const std::uint8_t*>(context->view.buf);
  result->value.payload.size = static_cast<std::size_t>(context->view.len);
  result->value.payload.owner = context;
  result->value.payload.retain = retain_python_buffer;
  result->value.payload.release = release_python_buffer_owner;
  result->value.payload.memory = {
      sizeof(nodrix_memory_handle_v2),
      NODRIX_MEMORY_HOST,
      0,
      0,
      0,
      static_cast<std::uint64_t>(context->view.len),
      NODRIX_MEMORY_FLAG_HOST_VISIBLE | NODRIX_MEMORY_FLAG_READ_ONLY,
      context,
      retain_python_buffer,
      release_python_buffer_owner,
  };
  Py_DECREF(sequence);
  Py_DECREF(timestamp);
  Py_DECREF(trace);
  Py_DECREF(payload);
  if (PyErr_Occurred()) throw std::runtime_error("cannot convert Nodrix Message fields");
  return result;
}

struct CBufferLease {
  void* owner;
  nodrix_buffer_release_v2 release;
  std::shared_ptr<DynamicLibrary> library;
};

void release_c_buffer(void*, std::size_t, void* opaque) noexcept {
  std::unique_ptr<CBufferLease> lease(static_cast<CBufferLease*>(opaque));
  if (lease && lease->release) lease->release(lease->owner);
}

struct CollectedOutput {
  std::size_t port;
  vp::Message message;
};

struct Collector {
  std::vector<CollectedOutput> outputs;
  std::string error;
  std::size_t output_count{0};
  std::shared_ptr<DynamicLibrary> library;
};

void collect_output(
    void* opaque, std::uint32_t output_port, const nodrix_message_v2* raw) {
  auto* collector = static_cast<Collector*>(opaque);
  if (!collector || !collector->error.empty()) return;
  try {
    if (!raw || raw->struct_size < NODRIX_MESSAGE_V2_REQUIRED_SIZE) {
      throw std::runtime_error("plugin emitted an invalid message structure");
    }
    if (output_port >= collector->output_count) {
      throw std::runtime_error("plugin emitted an invalid port index");
    }
    vp::Message message;
    message.type_id = raw->type_id;
    message.sequence = raw->sequence;
    message.source_timestamp_ns = raw->source_timestamp_ns;
    message.runtime_timestamp_ns = raw->runtime_timestamp_ns;
    if (raw->correlation.struct_size < NODRIX_CORRELATION_V2_REQUIRED_SIZE) {
      throw std::runtime_error("plugin emitted an invalid correlation structure");
    }
    message.pipeline_id =
        copy_string_view(raw->correlation.pipeline_id, "pipeline_id");
    message.run_id = copy_string_view(raw->correlation.run_id, "run_id");
    message.source_id =
        copy_string_view(raw->correlation.source_id, "source_id");
    message.stream_id =
        copy_string_view(raw->correlation.stream_id, "stream_id");
    message.trace_id = copy_string_view(raw->correlation.trace_id, "trace_id");
    message.span_id = copy_string_view(raw->correlation.span_id, "span_id");
    message.trace_id_integer =
        (raw->correlation.flags & NODRIX_CORRELATION_TRACE_ID_INTEGER) != 0;
    message.present = raw->present != 0;
    message.end_of_stream = raw->end_of_stream != 0;

    const auto& payload = raw->payload;
    if (payload.struct_size < NODRIX_BUFFER_V2_REQUIRED_SIZE ||
        payload.memory.struct_size <
            NODRIX_MEMORY_HANDLE_V2_REQUIRED_SIZE ||
        !valid_memory_domain(payload.memory.domain)) {
      throw std::runtime_error("plugin emitted an invalid buffer structure");
    }
    const bool host_visible =
        (payload.memory.flags & NODRIX_MEMORY_FLAG_HOST_VISIBLE) != 0;
    if (payload.size > 0 && !payload.data && !host_visible) {
      throw std::runtime_error(
          "Python host cannot expose a device-only plugin buffer; use a "
          "domain-specific SDK adapter or the standalone native engine");
    }
    if (payload.size > 0 && !payload.data) {
      throw std::runtime_error("plugin marked a host-visible buffer without data");
    }
    if (payload.size > 0 && payload.retain && payload.release) {
      payload.retain(payload.owner);
      auto* lease = new CBufferLease{
          payload.owner,
          payload.release,
          collector->library,
      };
      message.payload = vp::Buffer::wrap(
          const_cast<std::uint8_t*>(payload.data),
          payload.size,
          release_c_buffer,
          lease);
    } else if (payload.size > 0) {
      message.payload = vp::Buffer::allocate(payload.size);
      std::memcpy(message.payload.data(), payload.data, payload.size);
    }
    collector->outputs.push_back({output_port, std::move(message)});
  } catch (const std::exception& exc) {
    collector->error = exc.what();
  } catch (...) {
    collector->error = "plugin emitted an unknown host-side error";
  }
}

typedef struct {
  PyObject_HEAD
  std::shared_ptr<DynamicLibrary>* library;
  nodrix_node_api_v2 api;
  std::vector<vp::PortSpec>* inputs;
  std::vector<vp::PortSpec>* outputs;
  std::string* parameters_json;
  int opened;
} NativeNodeHostObject;

PyTypeObject NativeNodeHostType = {PyVarObject_HEAD_INIT(nullptr, 0)};

std::string plugin_error(const nodrix_node_api_v2& api, nodrix_status_v2 status) {
  const char* detail =
      api.last_error && api.instance ? api.last_error(api.instance) : nullptr;
  std::string result = "Plugin C ABI 2.0 call failed with status " +
                       std::to_string(status);
  if (detail && *detail) result += ": " + std::string(detail);
  return result;
}

std::vector<vp::PortSpec> read_ports(
    const nodrix_node_api_v2& api, bool inputs) {
  const std::size_t count =
      inputs ? api.input_count(api.instance) : api.output_count(api.instance);
  std::vector<vp::PortSpec> result;
  result.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    nodrix_port_v2 port{sizeof(nodrix_port_v2), nullptr, nullptr, nullptr};
    const auto status = inputs
                            ? api.input_port(api.instance, index, &port)
                            : api.output_port(api.instance, index, &port);
    if (status != NODRIX_STATUS_OK) throw std::runtime_error(plugin_error(api, status));
    if (port.struct_size < NODRIX_PORT_V2_REQUIRED_SIZE ||
        !port.name || !port.type) {
      throw std::runtime_error("Plugin C ABI 2.0 returned an invalid port");
    }
    const std::string memory =
        port.memory ? port.memory : "any";
    if (!valid_port_memory(memory)) {
      throw std::runtime_error(
          "Plugin C ABI 2.0 returned an unknown memory domain");
    }
    result.push_back(
        {
            port.name,
            port.type,
            memory,
            (port.flags & NODRIX_PORT_OPTIONAL) != 0,
        });
  }
  return result;
}

void validate_api(const nodrix_node_api_v2& api) {
  if (api.struct_size < NODRIX_NODE_API_V2_REQUIRED_SIZE ||
      api.abi_version != NODRIX_C_ABI_VERSION || !api.instance ||
      !api.input_count || !api.output_count || !api.input_port ||
      !api.output_port || !api.is_source || !api.open || !api.process ||
      !api.flush || !api.close || !api.destroy) {
    throw std::runtime_error("Plugin returned an incomplete or incompatible C ABI 2.0 table");
  }
}

PyObject* NativeNodeHost_new(PyTypeObject* type, PyObject*, PyObject*) {
  auto* self = reinterpret_cast<NativeNodeHostObject*>(type->tp_alloc(type, 0));
  if (self) {
    self->library = nullptr;
    self->api = {};
    self->inputs = nullptr;
    self->outputs = nullptr;
    self->parameters_json = nullptr;
    self->opened = 0;
  }
  return reinterpret_cast<PyObject*>(self);
}

int NativeNodeHost_init(
    NativeNodeHostObject* self, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {
      "library", "node_type", "parameters_json", nullptr};
  const char* library_path = nullptr;
  const char* node_type = nullptr;
  const char* parameters = "{}";
  if (!PyArg_ParseTupleAndKeywords(
          args,
          kwargs,
          "ss|s",
          const_cast<char**>(keywords),
          &library_path,
          &node_type,
          &parameters)) {
    return -1;
  }
  try {
    self->library = new std::shared_ptr<DynamicLibrary>(
        std::make_shared<DynamicLibrary>());
    (*self->library)->open(library_path);
    const auto abi = reinterpret_cast<nodrix_plugin_abi_version_v2_fn>(
        (*self->library)->symbol("nodrix_plugin_abi_version_v2"));
    if (abi() != NODRIX_C_ABI_VERSION) {
      throw std::runtime_error("Nodrix Plugin C ABI 2.0 version mismatch");
    }
    const auto features = reinterpret_cast<nodrix_plugin_features_v2_fn>(
        (*self->library)->symbol("nodrix_plugin_features_v2"));
    constexpr std::uint64_t required_features =
        NODRIX_C_FEATURE_TYPED_PORTS |
        NODRIX_C_FEATURE_MEMORY_DOMAINS |
        NODRIX_C_FEATURE_CORRELATION |
        NODRIX_C_FEATURE_DEVICE_HANDLES;
    if ((features() & required_features) != required_features) {
      throw std::runtime_error(
          "Plugin C ABI 2.0 does not provide the required stable features");
    }
    const auto create = reinterpret_cast<nodrix_plugin_create_v2_fn>(
        (*self->library)->symbol("nodrix_plugin_create_v2"));
    self->api.struct_size = sizeof(nodrix_node_api_v2);
    const auto status =
        create(NODRIX_C_ABI_VERSION, node_type, parameters, &self->api);
    if (status != NODRIX_STATUS_OK) {
      throw std::runtime_error(
          "Plugin refused node type or ABI with status " +
          std::to_string(status));
    }
    validate_api(self->api);
    self->inputs = new std::vector<vp::PortSpec>(read_ports(self->api, true));
    self->outputs = new std::vector<vp::PortSpec>(read_ports(self->api, false));
    self->parameters_json = new std::string(parameters);
  } catch (const std::exception& exc) {
    if (self->api.instance && self->api.destroy) self->api.destroy(self->api.instance);
    delete self->inputs;
    delete self->outputs;
    delete self->parameters_json;
    delete self->library;
    self->library = nullptr;
    self->api = {};
    self->inputs = nullptr;
    self->outputs = nullptr;
    self->parameters_json = nullptr;
    PyErr_SetString(PyExc_RuntimeError, exc.what());
    return -1;
  }
  return 0;
}

void NativeNodeHost_dealloc(NativeNodeHostObject* self) {
  if (self->api.instance) {
    if (self->opened && self->api.close) self->api.close(self->api.instance);
    if (self->api.destroy) self->api.destroy(self->api.instance);
  }
  delete self->inputs;
  delete self->outputs;
  delete self->parameters_json;
  delete self->library;
  self->library = nullptr;
  self->api = {};
  Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}

PyObject* ports_to_dict(
    const std::vector<vp::PortSpec>& ports, bool memory) {
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  for (const auto& port : ports) {
    const std::string& value = memory ? port.memory : port.type;
    PyObject* text = PyUnicode_FromStringAndSize(
        value.data(), static_cast<Py_ssize_t>(value.size()));
    if (!text || PyDict_SetItemString(result, port.name.c_str(), text) != 0) {
      Py_XDECREF(text);
      Py_DECREF(result);
      return nullptr;
    }
    Py_DECREF(text);
  }
  return result;
}

PyObject* NativeNodeHost_inputs(NativeNodeHostObject* self, void*) {
  return ports_to_dict(*self->inputs, false);
}

PyObject* NativeNodeHost_outputs(NativeNodeHostObject* self, void*) {
  return ports_to_dict(*self->outputs, false);
}

PyObject* NativeNodeHost_input_memory(NativeNodeHostObject* self, void*) {
  return ports_to_dict(*self->inputs, true);
}

PyObject* NativeNodeHost_output_memory(NativeNodeHostObject* self, void*) {
  return ports_to_dict(*self->outputs, true);
}

PyObject* NativeNodeHost_optional_inputs(
    NativeNodeHostObject* self, void*) {
  PyObject* result = PyTuple_New(static_cast<Py_ssize_t>(
      std::count_if(
          self->inputs->begin(),
          self->inputs->end(),
          [](const vp::PortSpec& port) { return port.optional; })));
  if (!result) return nullptr;
  Py_ssize_t index = 0;
  for (const auto& port : *self->inputs) {
    if (!port.optional) continue;
    PyObject* name = PyUnicode_FromString(port.name.c_str());
    if (!name) {
      Py_DECREF(result);
      return nullptr;
    }
    PyTuple_SET_ITEM(result, index++, name);
  }
  return result;
}

PyObject* NativeNodeHost_is_source(NativeNodeHostObject* self, void*) {
  return PyBool_FromLong(self->api.is_source(self->api.instance));
}

PyObject* NativeNodeHost_open(
    NativeNodeHostObject* self, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {"name", "run_dir", "device", nullptr};
  const char* name = nullptr;
  const char* run_dir = nullptr;
  const char* device = "auto";
  if (!PyArg_ParseTupleAndKeywords(
          args,
          kwargs,
          "ss|s",
          const_cast<char**>(keywords),
          &name,
          &run_dir,
          &device)) {
    return nullptr;
  }
  nodrix_node_context_v2 context{
      sizeof(nodrix_node_context_v2),
      name,
      self->parameters_json ? self->parameters_json->c_str() : "{}",
      run_dir,
      device,
      nullptr,
      nullptr,
  };
  nodrix_status_v2 status = NODRIX_STATUS_RUNTIME_ERROR;
  Py_BEGIN_ALLOW_THREADS
  status = self->api.open(self->api.instance, &context);
  Py_END_ALLOW_THREADS
  if (status != NODRIX_STATUS_OK) {
    PyErr_SetString(PyExc_RuntimeError, plugin_error(self->api, status).c_str());
    return nullptr;
  }
  self->opened = 1;
  Py_RETURN_NONE;
}

PyObject* build_python_outputs(
    NativeNodeHostObject* self,
    const std::vector<CollectedOutput>& outputs,
    PyObject* message_class,
    PyObject* template_message) {
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  PyObject* metadata =
      template_message ? PyObject_GetAttrString(template_message, "metadata")
                       : PyDict_New();
  PyObject* created =
      template_message ? PyObject_GetAttrString(template_message, "created_ns")
                       : PyLong_FromLongLong(0);
  for (const auto& output : outputs) {
    const auto& port = self->outputs->at(output.port);
    PyObject* payload = NativeBufferView_from_buffer(output.message.payload);
    PyObject* call_args = PyTuple_New(2);
    PyObject* call_kwargs = PyDict_New();
    if (!payload || !call_args || !call_kwargs) {
      Py_XDECREF(payload);
      Py_XDECREF(call_args);
      Py_XDECREF(call_kwargs);
      Py_DECREF(result);
      Py_XDECREF(metadata);
      Py_XDECREF(created);
      return nullptr;
    }
    PyTuple_SET_ITEM(call_args, 0, PyUnicode_FromString(port.type.c_str()));
    PyTuple_SET_ITEM(call_args, 1, payload);
    auto set_owned = [&](const char* key, PyObject* value) {
      if (!value) return false;
      const int status = PyDict_SetItemString(call_kwargs, key, value);
      Py_DECREF(value);
      return status == 0;
    };
    PyObject* trace_id = nullptr;
    if (output.message.trace_id_integer) {
      trace_id = PyLong_FromString(
          const_cast<char*>(
              output.message.trace_id.empty()
                  ? "0"
                  : output.message.trace_id.c_str()),
          nullptr,
          10);
    } else {
      trace_id = PyUnicode_FromStringAndSize(
          output.message.trace_id.data(),
          static_cast<Py_ssize_t>(output.message.trace_id.size()));
    }
    if (!set_owned(
            "sequence",
            PyLong_FromUnsignedLongLong(output.message.sequence)) ||
        !set_owned(
            "timestamp_ns",
            PyLong_FromLongLong(output.message.source_timestamp_ns)) ||
        !set_owned("trace_id", trace_id) ||
        !set_owned(
            "pipeline_id",
            PyUnicode_FromStringAndSize(
                output.message.pipeline_id.data(),
                static_cast<Py_ssize_t>(output.message.pipeline_id.size()))) ||
        !set_owned(
            "run_id",
            PyUnicode_FromStringAndSize(
                output.message.run_id.data(),
                static_cast<Py_ssize_t>(output.message.run_id.size()))) ||
        !set_owned(
            "source_id",
            PyUnicode_FromStringAndSize(
                output.message.source_id.data(),
                static_cast<Py_ssize_t>(output.message.source_id.size()))) ||
        !set_owned(
            "stream_id",
            PyUnicode_FromStringAndSize(
                output.message.stream_id.data(),
                static_cast<Py_ssize_t>(output.message.stream_id.size()))) ||
        !set_owned(
            "span_id",
            PyUnicode_FromStringAndSize(
                output.message.span_id.data(),
                static_cast<Py_ssize_t>(output.message.span_id.size())))) {
      Py_DECREF(call_args);
      Py_DECREF(call_kwargs);
      Py_DECREF(result);
      Py_XDECREF(metadata);
      Py_XDECREF(created);
      return nullptr;
    }
    if (metadata) PyDict_SetItemString(call_kwargs, "metadata", metadata);
    if (created) PyDict_SetItemString(call_kwargs, "created_ns", created);
    PyObject* message = PyObject_Call(message_class, call_args, call_kwargs);
    Py_DECREF(call_args);
    Py_DECREF(call_kwargs);
    if (!message ||
        PyDict_SetItemString(result, port.name.c_str(), message) != 0) {
      Py_XDECREF(message);
      Py_DECREF(result);
      Py_XDECREF(metadata);
      Py_XDECREF(created);
      return nullptr;
    }
    Py_DECREF(message);
  }
  Py_XDECREF(metadata);
  Py_XDECREF(created);
  return result;
}

PyObject* NativeNodeHost_process(
    NativeNodeHostObject* self, PyObject* inputs) {
  if (!PyDict_Check(inputs)) {
    PyErr_SetString(PyExc_TypeError, "inputs must be a dict of Nodrix messages");
    return nullptr;
  }
  PyObject* template_message = nullptr;
  try {
    std::vector<std::unique_ptr<InputMessage>> holders;
    std::vector<nodrix_message_v2> native_inputs;
    holders.reserve(self->inputs->size());
    native_inputs.reserve(self->inputs->size());
    for (const auto& port : *self->inputs) {
      PyObject* message = PyDict_GetItemString(inputs, port.name.c_str());
      if (!message) {
        if (!port.optional) {
          throw std::runtime_error(
              "missing native node input: " + port.name);
        }
        auto holder = absent_input_message(port.type);
        native_inputs.push_back(holder->value);
        holders.push_back(std::move(holder));
        continue;
      }
      if (!template_message) template_message = message;
      auto holder = message_from_python(message);
      native_inputs.push_back(holder->value);
      holders.push_back(std::move(holder));
    }
    Collector collector;
    collector.output_count = self->outputs->size();
    if (self->library) collector.library = *self->library;
    nodrix_status_v2 status = NODRIX_STATUS_RUNTIME_ERROR;
    Py_BEGIN_ALLOW_THREADS
    status = self->api.process(
        self->api.instance,
        native_inputs.data(),
        native_inputs.size(),
        collect_output,
        &collector);
    Py_END_ALLOW_THREADS
    if (status != NODRIX_STATUS_OK) {
      throw std::runtime_error(plugin_error(self->api, status));
    }
    if (!collector.error.empty()) throw std::runtime_error(collector.error);

    PyObject* module = PyImport_ImportModule("nodrix.messages");
    if (!module) return nullptr;
    PyObject* message_class = PyObject_GetAttrString(module, "Message");
    Py_DECREF(module);
    if (!message_class) return nullptr;
    PyObject* result = build_python_outputs(
        self, collector.outputs, message_class, template_message);
    Py_DECREF(message_class);
    return result;
  } catch (const std::exception& exc) {
    PyErr_SetString(PyExc_RuntimeError, exc.what());
    return nullptr;
  }
}

PyObject* NativeNodeHost_flush(NativeNodeHostObject* self, PyObject*) {
  Collector collector;
  collector.output_count = self->outputs->size();
  if (self->library) collector.library = *self->library;
  nodrix_status_v2 status = NODRIX_STATUS_RUNTIME_ERROR;
  Py_BEGIN_ALLOW_THREADS
  status =
      self->api.flush(self->api.instance, collect_output, &collector);
  Py_END_ALLOW_THREADS
  if (status != NODRIX_STATUS_OK || !collector.error.empty()) {
    const std::string error =
        !collector.error.empty() ? collector.error : plugin_error(self->api, status);
    PyErr_SetString(PyExc_RuntimeError, error.c_str());
    return nullptr;
  }
  if (collector.outputs.empty()) return PyDict_New();
  PyObject* module = PyImport_ImportModule("nodrix.messages");
  if (!module) return nullptr;
  PyObject* message_class = PyObject_GetAttrString(module, "Message");
  Py_DECREF(module);
  if (!message_class) return nullptr;
  PyObject* result =
      build_python_outputs(self, collector.outputs, message_class, nullptr);
  Py_DECREF(message_class);
  return result;
}

PyObject* NativeNodeHost_close(NativeNodeHostObject* self, PyObject*) {
  if (!self->opened) Py_RETURN_NONE;
  nodrix_status_v2 status = NODRIX_STATUS_RUNTIME_ERROR;
  Py_BEGIN_ALLOW_THREADS
  status = self->api.close(self->api.instance);
  Py_END_ALLOW_THREADS
  if (status != NODRIX_STATUS_OK) {
    PyErr_SetString(PyExc_RuntimeError, plugin_error(self->api, status).c_str());
    return nullptr;
  }
  self->opened = 0;
  Py_RETURN_NONE;
}

PyMethodDef NativeNodeHost_methods[] = {
    {"open",
     reinterpret_cast<PyCFunction>(NativeNodeHost_open),
     METH_VARARGS | METH_KEYWORDS,
     "Open the native node."},
    {"process",
     reinterpret_cast<PyCFunction>(NativeNodeHost_process),
     METH_O,
     "Process messages through Plugin C ABI 2.0."},
    {"flush",
     reinterpret_cast<PyCFunction>(NativeNodeHost_flush),
     METH_NOARGS,
     "Flush the native node."},
    {"close",
     reinterpret_cast<PyCFunction>(NativeNodeHost_close),
     METH_NOARGS,
     "Close the native node."},
    {nullptr, nullptr, 0, nullptr},
};

PyGetSetDef NativeNodeHost_getset[] = {
    {const_cast<char*>("input_types"),
     reinterpret_cast<getter>(NativeNodeHost_inputs),
     nullptr,
     nullptr,
     nullptr},
    {const_cast<char*>("output_types"),
     reinterpret_cast<getter>(NativeNodeHost_outputs),
     nullptr,
     nullptr,
     nullptr},
    {const_cast<char*>("input_memory"),
     reinterpret_cast<getter>(NativeNodeHost_input_memory),
     nullptr,
     nullptr,
     nullptr},
    {const_cast<char*>("output_memory"),
     reinterpret_cast<getter>(NativeNodeHost_output_memory),
     nullptr,
     nullptr,
     nullptr},
    {const_cast<char*>("optional_inputs"),
     reinterpret_cast<getter>(NativeNodeHost_optional_inputs),
     nullptr,
     nullptr,
     nullptr},
    {const_cast<char*>("is_source"),
     reinterpret_cast<getter>(NativeNodeHost_is_source),
     nullptr,
     nullptr,
     nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native_plugin",
    "Native Plugin C ABI 2.0 host for unified Nodrix graphs.",
    -1,
    nullptr,
};

}  // namespace

PyMODINIT_FUNC PyInit__native_plugin() {
  NativeBufferViewType.tp_name = "nodrix._native_plugin.NativeBufferView";
  NativeBufferViewType.tp_basicsize = sizeof(NativeBufferViewObject);
  NativeBufferViewType.tp_flags = Py_TPFLAGS_DEFAULT;
  NativeBufferViewType.tp_doc = "Zero-copy view of a Plugin C ABI 2.0 buffer.";
  NativeBufferViewType.tp_dealloc =
      reinterpret_cast<destructor>(NativeBufferView_dealloc);
  NativeBufferViewType.tp_getset = NativeBufferView_getset;
  NativeBufferViewType.tp_as_buffer = &NativeBufferView_buffer_procs;
  if (PyType_Ready(&NativeBufferViewType) < 0) return nullptr;

  NativeNodeHostType.tp_name = "nodrix._native_plugin.NativeNodeHost";
  NativeNodeHostType.tp_basicsize = sizeof(NativeNodeHostObject);
  NativeNodeHostType.tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE;
  NativeNodeHostType.tp_doc =
      "Loads a Nodrix Plugin C ABI 2.0 node into the unified graph.";
  NativeNodeHostType.tp_new = NativeNodeHost_new;
  NativeNodeHostType.tp_init =
      reinterpret_cast<initproc>(NativeNodeHost_init);
  NativeNodeHostType.tp_dealloc =
      reinterpret_cast<destructor>(NativeNodeHost_dealloc);
  NativeNodeHostType.tp_methods = NativeNodeHost_methods;
  NativeNodeHostType.tp_getset = NativeNodeHost_getset;
  if (PyType_Ready(&NativeNodeHostType) < 0) return nullptr;

  PyObject* result = PyModule_Create(&module);
  if (!result) return nullptr;
  Py_INCREF(&NativeBufferViewType);
  Py_INCREF(&NativeNodeHostType);
  if (PyModule_AddObject(
          result,
          "NativeBufferView",
          reinterpret_cast<PyObject*>(&NativeBufferViewType)) < 0 ||
      PyModule_AddObject(
          result,
          "NativeNodeHost",
          reinterpret_cast<PyObject*>(&NativeNodeHostType)) < 0) {
    Py_DECREF(result);
    return nullptr;
  }
  return result;
}
