#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cstddef>
#include <cstdint>
#include <exception>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#endif

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
    if (!handle) throw std::runtime_error(dlerror() ? dlerror() : "dlopen failed");
#endif
  }

  void* symbol(const char* name) {
#if defined(_WIN32)
    void* value = reinterpret_cast<void*>(GetProcAddress(handle, name));
#else
    dlerror();
    void* value = dlsym(handle, name);
#endif
    if (!value) throw std::runtime_error(std::string("Missing plugin symbol: ") + name);
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
};

void release_python_buffer(void*, std::size_t, void* opaque) noexcept {
  auto* context = static_cast<PythonBufferContext*>(opaque);
  if (!context) return;
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

int NativeBufferView_getbuffer(NativeBufferViewObject* self, Py_buffer* view, int flags) {
  if (!self->buffer || !*self->buffer) {
    PyErr_SetString(PyExc_BufferError, "native plugin buffer is empty");
    return -1;
  }
  return PyBuffer_FillInfo(
      view, reinterpret_cast<PyObject*>(self), self->buffer->data(),
      static_cast<Py_ssize_t>(self->buffer->size()), self->readonly, flags);
}

void NativeBufferView_releasebuffer(NativeBufferViewObject*, Py_buffer*) {}

PyObject* NativeBufferView_get_nbytes(NativeBufferViewObject* self, void*) {
  return PyLong_FromSize_t(self->buffer ? self->buffer->size() : 0);
}

PyGetSetDef NativeBufferView_getset[] = {
    {const_cast<char*>("nbytes"), reinterpret_cast<getter>(NativeBufferView_get_nbytes), nullptr,
     const_cast<char*>("Buffer size in bytes."), nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

PyBufferProcs NativeBufferView_buffer_procs = {
    reinterpret_cast<getbufferproc>(NativeBufferView_getbuffer),
    reinterpret_cast<releasebufferproc>(NativeBufferView_releasebuffer),
};

vp::Buffer buffer_from_python(PyObject* payload) {
  if (PyObject_TypeCheck(payload, &NativeBufferViewType)) {
    auto* native = reinterpret_cast<NativeBufferViewObject*>(payload);
    return native->buffer ? *native->buffer : vp::Buffer{};
  }
  auto* context = new PythonBufferContext();
  if (PyObject_GetBuffer(payload, &context->view, PyBUF_CONTIG_RO) != 0) {
    delete context;
    throw std::runtime_error(
        "native nodes require a contiguous buffer-protocol payload; use Frame.buffer.owner, Tensor.buffer.owner, bytes, memoryview, or NativeBuffer");
  }
  return vp::Buffer::wrap(
      context->view.buf, static_cast<std::size_t>(context->view.len),
      release_python_buffer, context);
}

std::uint64_t python_trace_id(PyObject* value) {
  if (PyLong_Check(value)) return PyLong_AsUnsignedLongLongMask(value);
  PyObject* text = PyObject_Str(value);
  if (!text) return 0;
  const char* utf8 = PyUnicode_AsUTF8(text);
  const auto result = utf8 ? vp::fnv1a_64(utf8) : 0;
  Py_DECREF(text);
  return result;
}

vp::Message message_from_python(PyObject* message) {
  vp::Message result;
  PyObject* type = PyObject_GetAttrString(message, "type");
  PyObject* sequence = PyObject_GetAttrString(message, "sequence");
  PyObject* timestamp = PyObject_GetAttrString(message, "timestamp_ns");
  PyObject* trace = PyObject_GetAttrString(message, "trace_id");
  PyObject* payload = PyObject_GetAttrString(message, "payload");
  if (!type || !sequence || !timestamp || !trace || !payload) {
    Py_XDECREF(type); Py_XDECREF(sequence); Py_XDECREF(timestamp); Py_XDECREF(trace); Py_XDECREF(payload);
    throw std::runtime_error("invalid Nodrix Message object");
  }
  const char* type_text = PyUnicode_AsUTF8(type);
  result.type_id = type_text ? vp::fnv1a_64(type_text) : 0;
  result.sequence = PyLong_AsUnsignedLongLong(sequence);
  result.source_timestamp_ns = PyLong_AsLongLong(timestamp);
  result.runtime_timestamp_ns = vp::steady_time_ns();
  result.trace_id = python_trace_id(trace);
  result.payload = buffer_from_python(payload);
  Py_DECREF(type); Py_DECREF(sequence); Py_DECREF(timestamp); Py_DECREF(trace); Py_DECREF(payload);
  if (PyErr_Occurred()) throw std::runtime_error("cannot convert Nodrix Message fields");
  return result;
}

struct CollectedOutput {
  std::size_t port;
  vp::Message message;
};

class Collector final : public vp::Emitter {
 public:
  void emit(std::size_t output_port, vp::Message message) override {
    outputs.push_back({output_port, std::move(message)});
  }
  std::vector<CollectedOutput> outputs;
};

typedef struct {
  PyObject_HEAD
  DynamicLibrary* library;
  vp::Node* node;
  vp::DestroyNodeFn destroy;
  std::string* parameters_json;
  int opened;
} NativeNodeHostObject;

PyTypeObject NativeNodeHostType = {PyVarObject_HEAD_INIT(nullptr, 0)};

PyObject* ports_memory_to_dict(const std::vector<vp::PortSpec>& ports) {
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  for (const auto& port : ports) {
    PyObject* memory = PyUnicode_FromStringAndSize(port.memory.data(), static_cast<Py_ssize_t>(port.memory.size()));
    if (!memory || PyDict_SetItemString(result, port.name.c_str(), memory) != 0) {
      Py_XDECREF(memory);
      Py_DECREF(result);
      return nullptr;
    }
    Py_DECREF(memory);
  }
  return result;
}

PyObject* ports_to_dict(const std::vector<vp::PortSpec>& ports) {
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  for (const auto& port : ports) {
    PyObject* type = PyUnicode_FromStringAndSize(port.type.data(), static_cast<Py_ssize_t>(port.type.size()));
    if (!type || PyDict_SetItemString(result, port.name.c_str(), type) != 0) {
      Py_XDECREF(type);
      Py_DECREF(result);
      return nullptr;
    }
    Py_DECREF(type);
  }
  return result;
}

PyObject* NativeNodeHost_new(PyTypeObject* type, PyObject*, PyObject*) {
  auto* self = reinterpret_cast<NativeNodeHostObject*>(type->tp_alloc(type, 0));
  if (self) {
    self->library = nullptr;
    self->node = nullptr;
    self->destroy = nullptr;
    self->parameters_json = nullptr;
    self->opened = 0;
  }
  return reinterpret_cast<PyObject*>(self);
}

int NativeNodeHost_init(NativeNodeHostObject* self, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {"library", "node_type", "parameters_json", nullptr};
  const char* library_path = nullptr;
  const char* node_type = nullptr;
  const char* parameters = "{}";
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|s", const_cast<char**>(keywords),
                                   &library_path, &node_type, &parameters)) return -1;
  try {
    self->library = new DynamicLibrary();
    self->library->open(library_path);
    auto abi = reinterpret_cast<vp::PluginAbiVersionFn>(self->library->symbol("nodrix_plugin_abi_version"));
    if (abi() != vp::kPluginAbiVersion) throw std::runtime_error("Nodrix plugin ABI version mismatch");
    auto create = reinterpret_cast<vp::CreateNodeFn>(self->library->symbol("nodrix_create_node"));
    self->destroy = reinterpret_cast<vp::DestroyNodeFn>(self->library->symbol("nodrix_destroy_node"));
    self->node = create(node_type, parameters);
    if (!self->node) throw std::runtime_error("plugin did not create the requested node type");
    self->parameters_json = new std::string(parameters);
  } catch (const std::exception& exc) {
    if (self->node && self->destroy) self->destroy(self->node);
    delete self->library;
    delete self->parameters_json;
    self->node = nullptr; self->library = nullptr; self->parameters_json = nullptr;
    PyErr_SetString(PyExc_RuntimeError, exc.what());
    return -1;
  }
  return 0;
}

void NativeNodeHost_dealloc(NativeNodeHostObject* self) {
  if (self->node) {
    try { if (self->opened) self->node->close(); } catch (...) {}
    if (self->destroy) self->destroy(self->node);
  }
  delete self->parameters_json;
  delete self->library;
  self->node = nullptr; self->library = nullptr; self->parameters_json = nullptr;
  Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}

PyObject* NativeNodeHost_inputs(NativeNodeHostObject* self, void*) {
  return ports_to_dict(self->node->input_ports());
}

PyObject* NativeNodeHost_outputs(NativeNodeHostObject* self, void*) {
  return ports_to_dict(self->node->output_ports());
}

PyObject* NativeNodeHost_input_memory(NativeNodeHostObject* self, void*) {
  return ports_memory_to_dict(self->node->input_ports());
}

PyObject* NativeNodeHost_output_memory(NativeNodeHostObject* self, void*) {
  return ports_memory_to_dict(self->node->output_ports());
}

PyObject* NativeNodeHost_is_source(NativeNodeHostObject* self, void*) {
  return PyBool_FromLong(self->node->is_source());
}

PyObject* NativeNodeHost_open(NativeNodeHostObject* self, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {"name", "run_dir", "device", nullptr};
  const char* name = nullptr;
  const char* run_dir = nullptr;
  const char* device = "auto";
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|s", const_cast<char**>(keywords), &name, &run_dir, &device)) return nullptr;
  try {
    std::exception_ptr error;
    Py_BEGIN_ALLOW_THREADS
    try {
      self->node->open({name, self->parameters_json ? *self->parameters_json : "{}", run_dir, device});
    } catch (...) { error = std::current_exception(); }
    Py_END_ALLOW_THREADS
    if (error) std::rethrow_exception(error);
    self->opened = 1;
  } catch (const std::exception& exc) {
    PyErr_SetString(PyExc_RuntimeError, exc.what());
    return nullptr;
  }
  Py_RETURN_NONE;
}

PyObject* build_python_outputs(
    NativeNodeHostObject* self, const std::vector<CollectedOutput>& outputs,
    PyObject* message_class, PyObject* template_message) {
  PyObject* result = PyDict_New();
  if (!result) return nullptr;
  PyObject* metadata = template_message ? PyObject_GetAttrString(template_message, "metadata") : PyDict_New();
  PyObject* created = template_message ? PyObject_GetAttrString(template_message, "created_ns") : PyLong_FromLongLong(0);
  const auto& ports = self->node->output_ports();
  for (const auto& output : outputs) {
    if (output.port >= ports.size()) {
      PyErr_SetString(PyExc_RuntimeError, "native plugin emitted an invalid port index");
      Py_DECREF(result); Py_XDECREF(metadata); Py_XDECREF(created);
      return nullptr;
    }
    PyObject* payload = NativeBufferView_from_buffer(output.message.payload);
    PyObject* args = PyTuple_New(2);
    PyObject* kwargs = PyDict_New();
    PyTuple_SET_ITEM(args, 0, PyUnicode_FromString(ports[output.port].type.c_str()));
    PyTuple_SET_ITEM(args, 1, payload);
    auto set_owned = [&](const char* key, PyObject* value) {
      if (!value) return false;
      const int status = PyDict_SetItemString(kwargs, key, value);
      Py_DECREF(value);
      return status == 0;
    };
    if (!set_owned("sequence", PyLong_FromUnsignedLongLong(output.message.sequence)) ||
        !set_owned("timestamp_ns", PyLong_FromLongLong(output.message.source_timestamp_ns)) ||
        !set_owned("trace_id", PyLong_FromUnsignedLongLong(output.message.trace_id))) {
      Py_DECREF(args); Py_DECREF(kwargs); Py_DECREF(result); Py_XDECREF(metadata); Py_XDECREF(created);
      return nullptr;
    }
    if (metadata) PyDict_SetItemString(kwargs, "metadata", metadata);
    if (created) PyDict_SetItemString(kwargs, "created_ns", created);
    PyObject* message = PyObject_Call(message_class, args, kwargs);
    Py_DECREF(args); Py_DECREF(kwargs);
    if (!message || PyDict_SetItemString(result, ports[output.port].name.c_str(), message) != 0) {
      Py_XDECREF(message); Py_DECREF(result); Py_XDECREF(metadata); Py_XDECREF(created);
      return nullptr;
    }
    Py_DECREF(message);
  }
  Py_XDECREF(metadata); Py_XDECREF(created);
  return result;
}

PyObject* NativeNodeHost_process(NativeNodeHostObject* self, PyObject* inputs) {
  if (!PyDict_Check(inputs)) {
    PyErr_SetString(PyExc_TypeError, "inputs must be a dict of Nodrix messages");
    return nullptr;
  }
  std::vector<vp::Message> native_inputs;
  native_inputs.reserve(self->node->input_ports().size());
  PyObject* template_message = nullptr;
  try {
    for (const auto& port : self->node->input_ports()) {
      PyObject* message = PyDict_GetItemString(inputs, port.name.c_str());
      if (!message) throw std::runtime_error("missing native node input: " + port.name);
      if (!template_message) template_message = message;
      native_inputs.push_back(message_from_python(message));
    }
    Collector collector;
    std::exception_ptr error;
    Py_BEGIN_ALLOW_THREADS
    try { self->node->process(native_inputs, collector); }
    catch (...) { error = std::current_exception(); }
    Py_END_ALLOW_THREADS
    if (error) std::rethrow_exception(error);
    PyObject* module = PyImport_ImportModule("nodrix.messages");
    if (!module) return nullptr;
    PyObject* message_class = PyObject_GetAttrString(module, "Message");
    Py_DECREF(module);
    if (!message_class) return nullptr;
    PyObject* result = build_python_outputs(self, collector.outputs, message_class, template_message);
    Py_DECREF(message_class);
    return result;
  } catch (const std::exception& exc) {
    PyErr_SetString(PyExc_RuntimeError, exc.what());
    return nullptr;
  }
}

PyObject* NativeNodeHost_flush(NativeNodeHostObject* self, PyObject*) {
  try {
    Collector collector;
    std::exception_ptr error;
    Py_BEGIN_ALLOW_THREADS
    try { self->node->flush(collector); }
    catch (...) { error = std::current_exception(); }
    Py_END_ALLOW_THREADS
    if (error) std::rethrow_exception(error);
    if (collector.outputs.empty()) return PyDict_New();
    PyObject* module = PyImport_ImportModule("nodrix.messages");
    if (!module) return nullptr;
    PyObject* message_class = PyObject_GetAttrString(module, "Message");
    Py_DECREF(module);
    if (!message_class) return nullptr;
    PyObject* result = build_python_outputs(self, collector.outputs, message_class, nullptr);
    Py_DECREF(message_class);
    return result;
  } catch (const std::exception& exc) {
    PyErr_SetString(PyExc_RuntimeError, exc.what());
    return nullptr;
  }
}

PyObject* NativeNodeHost_close(NativeNodeHostObject* self, PyObject*) {
  if (self->opened) {
    std::exception_ptr error;
    Py_BEGIN_ALLOW_THREADS
    try { self->node->close(); }
    catch (...) { error = std::current_exception(); }
    Py_END_ALLOW_THREADS
    if (error) {
      try { std::rethrow_exception(error); }
      catch (const std::exception& exc) { PyErr_SetString(PyExc_RuntimeError, exc.what()); return nullptr; }
    }
    self->opened = 0;
  }
  Py_RETURN_NONE;
}

PyMethodDef NativeNodeHost_methods[] = {
    {"open", reinterpret_cast<PyCFunction>(NativeNodeHost_open), METH_VARARGS | METH_KEYWORDS, "Open the native node."},
    {"process", reinterpret_cast<PyCFunction>(NativeNodeHost_process), METH_O, "Process messages through the native plugin."},
    {"flush", reinterpret_cast<PyCFunction>(NativeNodeHost_flush), METH_NOARGS, "Flush the native node."},
    {"close", reinterpret_cast<PyCFunction>(NativeNodeHost_close), METH_NOARGS, "Close the native node."},
    {nullptr, nullptr, 0, nullptr},
};

PyGetSetDef NativeNodeHost_getset[] = {
    {const_cast<char*>("input_types"), reinterpret_cast<getter>(NativeNodeHost_inputs), nullptr, nullptr, nullptr},
    {const_cast<char*>("output_types"), reinterpret_cast<getter>(NativeNodeHost_outputs), nullptr, nullptr, nullptr},
    {const_cast<char*>("input_memory"), reinterpret_cast<getter>(NativeNodeHost_input_memory), nullptr, nullptr, nullptr},
    {const_cast<char*>("output_memory"), reinterpret_cast<getter>(NativeNodeHost_output_memory), nullptr, nullptr, nullptr},
    {const_cast<char*>("is_source"), reinterpret_cast<getter>(NativeNodeHost_is_source), nullptr, nullptr, nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native_plugin",
    "Native plugin host for mixed Python/C++ Nodrix graphs.",
    -1,
    nullptr,
};

}  // namespace

PyMODINIT_FUNC PyInit__native_plugin() {
  NativeBufferViewType.tp_name = "nodrix._native_plugin.NativeBufferView";
  NativeBufferViewType.tp_basicsize = sizeof(NativeBufferViewObject);
  NativeBufferViewType.tp_flags = Py_TPFLAGS_DEFAULT;
  NativeBufferViewType.tp_doc = "Zero-copy view of a Nodrix C++ Buffer.";
  NativeBufferViewType.tp_dealloc = reinterpret_cast<destructor>(NativeBufferView_dealloc);
  NativeBufferViewType.tp_getset = NativeBufferView_getset;
  NativeBufferViewType.tp_as_buffer = &NativeBufferView_buffer_procs;
  if (PyType_Ready(&NativeBufferViewType) < 0) return nullptr;

  NativeNodeHostType.tp_name = "nodrix._native_plugin.NativeNodeHost";
  NativeNodeHostType.tp_basicsize = sizeof(NativeNodeHostObject);
  NativeNodeHostType.tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE;
  NativeNodeHostType.tp_doc = "Loads and executes a Nodrix C++ plugin inside the unified graph.";
  NativeNodeHostType.tp_new = NativeNodeHost_new;
  NativeNodeHostType.tp_init = reinterpret_cast<initproc>(NativeNodeHost_init);
  NativeNodeHostType.tp_dealloc = reinterpret_cast<destructor>(NativeNodeHost_dealloc);
  NativeNodeHostType.tp_methods = NativeNodeHost_methods;
  NativeNodeHostType.tp_getset = NativeNodeHost_getset;
  if (PyType_Ready(&NativeNodeHostType) < 0) return nullptr;

  PyObject* result = PyModule_Create(&module);
  if (!result) return nullptr;
  Py_INCREF(&NativeBufferViewType);
  Py_INCREF(&NativeNodeHostType);
  if (PyModule_AddObject(result, "NativeBufferView", reinterpret_cast<PyObject*>(&NativeBufferViewType)) < 0 ||
      PyModule_AddObject(result, "NativeNodeHost", reinterpret_cast<PyObject*>(&NativeNodeHostType)) < 0) {
    Py_DECREF(result);
    return nullptr;
  }
  return result;
}
