#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include "nodrix/builtin_nodes.hpp"
#include "nodrix/c_api.h"
#include "nodrix/mpmc_queue.hpp"
#include "nodrix/node.hpp"
#include "nodrix/spsc_queue.hpp"

#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#ifndef NODRIX_NATIVE_VERSION
#define NODRIX_NATIVE_VERSION "unknown"
#endif

namespace vp = nodrix;
namespace fs = std::filesystem;

namespace {

volatile std::sig_atomic_t g_received_signal = 0;

void native_signal_handler(int signal_number) {
  g_received_signal = signal_number;
}

#if defined(_WIN32)
BOOL WINAPI native_console_handler(DWORD control_type) {
  switch (control_type) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
    case CTRL_CLOSE_EVENT:
    case CTRL_LOGOFF_EVENT:
    case CTRL_SHUTDOWN_EVENT:
      g_received_signal = SIGINT;
      return TRUE;
    default:
      return FALSE;
  }
}
#endif

enum class QueuePolicy { Block, Latest, DropOldest, DropNewest };
enum class SynchronizationPolicy {
  ExactSequence,
  ApproximateTimestamp,
  LatestAvailable,
  Zip,
};
enum class LifecycleState {
  Created,
  Configuring,
  Ready,
  Starting,
  Running,
  Degraded,
  Stopping,
  Stopped,
  Failed,
};

const char* lifecycle_name(LifecycleState state) noexcept {
  switch (state) {
    case LifecycleState::Created: return "CREATED";
    case LifecycleState::Configuring: return "CONFIGURING";
    case LifecycleState::Ready: return "READY";
    case LifecycleState::Starting: return "STARTING";
    case LifecycleState::Running: return "RUNNING";
    case LifecycleState::Degraded: return "DEGRADED";
    case LifecycleState::Stopping: return "STOPPING";
    case LifecycleState::Stopped: return "STOPPED";
    case LifecycleState::Failed: return "FAILED";
  }
  return "FAILED";
}

QueuePolicy parse_policy(std::string_view value) {
  if (value == "block") return QueuePolicy::Block;
  if (value == "latest") return QueuePolicy::Latest;
  if (value == "drop_oldest") return QueuePolicy::DropOldest;
  if (value == "drop_newest") return QueuePolicy::DropNewest;
  throw std::runtime_error("Unsupported queue policy: " + std::string(value));
}

const char* queue_policy_name(QueuePolicy policy) noexcept {
  switch (policy) {
    case QueuePolicy::Block: return "block";
    case QueuePolicy::Latest: return "latest";
    case QueuePolicy::DropOldest: return "drop_oldest";
    case QueuePolicy::DropNewest: return "drop_newest";
  }
  return "block";
}

SynchronizationPolicy parse_synchronization(std::string_view value) {
  if (value == "exact_sequence") {
    return SynchronizationPolicy::ExactSequence;
  }
  if (value == "approximate_timestamp") {
    return SynchronizationPolicy::ApproximateTimestamp;
  }
  if (value == "latest_available") {
    return SynchronizationPolicy::LatestAvailable;
  }
  if (value == "zip") return SynchronizationPolicy::Zip;
  throw std::runtime_error(
      "Unsupported synchronization policy: " + std::string(value));
}

std::string json_escape(std::string_view value) {
  std::ostringstream out;
  for (const unsigned char ch : value) {
    switch (ch) {
      case '\\': out << "\\\\"; break;
      case '"': out << "\\\""; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (ch < 0x20) {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch)
              << std::dec;
        } else {
          out << static_cast<char>(ch);
        }
    }
  }
  return out.str();
}

std::string hex_decode(std::string_view value) {
  if (value.size() % 2 != 0) throw std::runtime_error("Invalid hexadecimal plan field");
  std::string result;
  result.reserve(value.size() / 2);
  auto nibble = [](char ch) -> unsigned {
    if (ch >= '0' && ch <= '9') return static_cast<unsigned>(ch - '0');
    if (ch >= 'a' && ch <= 'f') return static_cast<unsigned>(ch - 'a' + 10);
    if (ch >= 'A' && ch <= 'F') return static_cast<unsigned>(ch - 'A' + 10);
    throw std::runtime_error("Invalid hexadecimal digit");
  };
  for (std::size_t i = 0; i < value.size(); i += 2) {
    result.push_back(static_cast<char>((nibble(value[i]) << 4U) | nibble(value[i + 1])));
  }
  return result;
}

std::vector<std::string> split_tabs(const std::string& line) {
  std::vector<std::string> fields;
  std::size_t begin = 0;
  for (;;) {
    const std::size_t pos = line.find('\t', begin);
    if (pos == std::string::npos) {
      fields.push_back(line.substr(begin));
      break;
    }
    fields.push_back(line.substr(begin, pos - begin));
    begin = pos + 1;
  }
  return fields;
}

struct NodeDef {
  std::string name;
  std::string uses;
  std::string parameters_json;
  SynchronizationPolicy synchronization{
      SynchronizationPolicy::ExactSequence};
  std::uint64_t tolerance_ns{20'000'000};
  std::string trigger_port;
  std::vector<std::string> optional_inputs;
};

struct EdgeDef {
  std::string source_node;
  std::string source_port;
  std::string target_node;
  std::string target_port;
  std::size_t capacity{8};
  QueuePolicy policy{QueuePolicy::Block};
  std::string source_memory{"any"};
  std::string target_memory{"any"};
  std::string resolved_memory{"any"};
};

struct Plan {
  std::string pipeline_name;
  std::string run_dir;
  std::uint64_t shutdown_timeout_ms{10'000};
  std::uint64_t metrics_interval_ms{1'000};
  std::vector<NodeDef> nodes;
  std::vector<EdgeDef> edges;
};

Plan read_plan(const fs::path& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("Cannot open plan: " + path.string());
  std::string line;
  if (!std::getline(input, line) ||
      (line != "NODRIX_NATIVE_PLAN_V1" &&
       line != "NODRIX_NATIVE_PLAN_V2")) {
    throw std::runtime_error("Unsupported native plan format");
  }
  Plan plan;
  while (std::getline(input, line)) {
    if (line.empty()) continue;
    const auto fields = split_tabs(line);
    if (fields[0] == "END") break;
    if (fields[0] == "PIPELINE" && fields.size() == 2) {
      plan.pipeline_name = hex_decode(fields[1]);
    } else if (fields[0] == "RUN_DIR" && fields.size() == 2) {
      plan.run_dir = hex_decode(fields[1]);
    } else if (fields[0] == "NODE" && fields.size() == 4) {
      plan.nodes.push_back({hex_decode(fields[1]), hex_decode(fields[2]), hex_decode(fields[3])});
    } else if (fields[0] == "RUNTIME" && fields.size() == 3) {
      plan.shutdown_timeout_ms = std::stoull(fields[1]);
      plan.metrics_interval_ms = std::stoull(fields[2]);
    } else if (fields[0] == "SYNC" && fields.size() == 6) {
      const std::string name = hex_decode(fields[1]);
      auto node = std::find_if(
          plan.nodes.begin(),
          plan.nodes.end(),
          [&](const NodeDef& value) { return value.name == name; });
      if (node == plan.nodes.end()) {
        throw std::runtime_error(
            "SYNC references an unknown node: " + name);
      }
      node->synchronization = parse_synchronization(fields[2]);
      node->tolerance_ns = std::stoull(fields[3]);
      node->trigger_port = hex_decode(fields[4]);
      std::istringstream optional(hex_decode(fields[5]));
      std::string port;
      while (std::getline(optional, port, '\n')) {
        if (!port.empty()) node->optional_inputs.push_back(port);
      }
    } else if (fields[0] == "EDGE" && fields.size() == 7) {
      plan.edges.push_back({hex_decode(fields[1]), hex_decode(fields[2]), hex_decode(fields[3]),
                            hex_decode(fields[4]), static_cast<std::size_t>(std::stoull(fields[5])),
                            parse_policy(fields[6])});
    } else {
      throw std::runtime_error("Malformed plan line: " + line);
    }
  }
  if (plan.pipeline_name.empty()) plan.pipeline_name = "native-pipeline";
  if (plan.run_dir.empty()) throw std::runtime_error("Native plan has no run directory");
  return plan;
}

struct NodeHolder {
  vp::Node* pointer{nullptr};
  std::function<void(vp::Node*)> destroy;

  NodeHolder() = default;
  NodeHolder(vp::Node* node, std::function<void(vp::Node*)> fn)
      : pointer(node), destroy(std::move(fn)) {}
  NodeHolder(const NodeHolder&) = delete;
  NodeHolder& operator=(const NodeHolder&) = delete;
  NodeHolder(NodeHolder&& other) noexcept
      : pointer(std::exchange(other.pointer, nullptr)), destroy(std::move(other.destroy)) {}
  NodeHolder& operator=(NodeHolder&& other) noexcept {
    if (this == &other) return *this;
    reset();
    pointer = std::exchange(other.pointer, nullptr);
    destroy = std::move(other.destroy);
    return *this;
  }
  ~NodeHolder() { reset(); }
  void reset() noexcept {
    if (pointer) {
      try { destroy(pointer); } catch (...) {}
      pointer = nullptr;
    }
  }
  vp::Node* operator->() noexcept { return pointer; }
  const vp::Node* operator->() const noexcept { return pointer; }
};

class DynamicLibrary final {
 public:
  explicit DynamicLibrary(const fs::path& path) : path_(path) {
#if defined(_WIN32)
    handle_ = LoadLibraryW(path.wstring().c_str());
    if (!handle_) {
      throw std::runtime_error(
          "LoadLibrary failed for Plugin C ABI 2.0 library: " + path.string());
    }
#else
    handle_ = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (!handle_) {
      const char* detail = dlerror();
      throw std::runtime_error(
          "dlopen failed for " + path.string() + ": " +
          (detail ? detail : "unknown dynamic loader error"));
    }
#endif
  }

  DynamicLibrary(const DynamicLibrary&) = delete;
  DynamicLibrary& operator=(const DynamicLibrary&) = delete;

  ~DynamicLibrary() {
    if (!handle_) return;
#if defined(_WIN32)
    FreeLibrary(handle_);
#else
    dlclose(handle_);
#endif
  }

  void* symbol(const char* name) const {
#if defined(_WIN32)
    void* value =
        reinterpret_cast<void*>(GetProcAddress(handle_, name));
#else
    dlerror();
    void* value = dlsym(handle_, name);
#endif
    if (!value) {
      throw std::runtime_error(
          "Missing Plugin C ABI 2.0 symbol " + std::string(name) +
          " in " + path_.string());
    }
    return value;
  }

 private:
  fs::path path_;
#if defined(_WIN32)
  HMODULE handle_{nullptr};
#else
  void* handle_{nullptr};
#endif
};

nodrix_string_view_v2 c_string_view(const std::string& value) noexcept {
  return {
      sizeof(nodrix_string_view_v2),
      value.empty() ? nullptr : value.data(),
      value.size(),
  };
}

std::string copy_c_string(
    const nodrix_string_view_v2& value, const char* field) {
  if (value.struct_size < NODRIX_STRING_VIEW_V2_REQUIRED_SIZE) {
    throw std::runtime_error(
        std::string("Plugin emitted undersized correlation field ") + field);
  }
  if (value.size > 0 && !value.data) {
    throw std::runtime_error(
        std::string("Plugin emitted null correlation field ") + field);
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

bool valid_port_memory(std::string_view memory) noexcept {
  constexpr std::array<std::string_view, 13> domains{
      "any",
      "cpu",
      "pinned_cpu",
      "shared",
      "dma_buf",
      "cuda",
      "rocm",
      "vulkan",
      "opencl",
      "metal",
      "npu",
      "dlpack",
      "external",
  };
  return std::find(domains.begin(), domains.end(), memory) !=
         domains.end();
}

void retain_native_buffer(void* owner) {
  vp::Buffer::retain_owner(owner);
}

void release_native_buffer(void* owner) {
  vp::Buffer::release_owner(owner);
}

struct CBufferLease {
  void* owner{nullptr};
  nodrix_buffer_release_v2 release{nullptr};
};

void release_plugin_buffer(
    void*, std::size_t, void* opaque) noexcept {
  std::unique_ptr<CBufferLease> lease(
      static_cast<CBufferLease*>(opaque));
  if (lease && lease->owner && lease->release) {
    lease->release(lease->owner);
  }
}

class CAbiNode final : public vp::Node {
 public:
  CAbiNode(
      fs::path library_path,
      std::string node_type,
      std::string parameters_json)
      : library_(
            std::make_shared<DynamicLibrary>(std::move(library_path))),
        node_type_(std::move(node_type)),
        parameters_json_(std::move(parameters_json)) {
    const auto abi = reinterpret_cast<nodrix_plugin_abi_version_v2_fn>(
        library_->symbol("nodrix_plugin_abi_version_v2"));
    const auto features = reinterpret_cast<nodrix_plugin_features_v2_fn>(
        library_->symbol("nodrix_plugin_features_v2"));
    const auto create = reinterpret_cast<nodrix_plugin_create_v2_fn>(
        library_->symbol("nodrix_plugin_create_v2"));
    if (abi() != NODRIX_C_ABI_VERSION) {
      throw std::runtime_error("Plugin C ABI 2.0 version mismatch");
    }
    constexpr std::uint64_t required =
        NODRIX_C_FEATURE_TYPED_PORTS |
        NODRIX_C_FEATURE_MEMORY_DOMAINS |
        NODRIX_C_FEATURE_CORRELATION |
        NODRIX_C_FEATURE_DEVICE_HANDLES;
    if ((features() & required) != required) {
      throw std::runtime_error(
          "Plugin does not implement required C ABI 2.0 features");
    }
    api_ = {};
    api_.struct_size = sizeof(api_);
    const nodrix_status_v2 status = create(
        NODRIX_C_ABI_VERSION,
        node_type_.c_str(),
        parameters_json_.c_str(),
        &api_);
    if (status != NODRIX_STATUS_OK) {
      throw std::runtime_error(
          "Plugin refused node type " + node_type_ +
          " with status " + std::to_string(status));
    }
    try {
      validate_api();
      inputs_ = read_ports(true);
      outputs_ = read_ports(false);
    } catch (...) {
      destroy();
      throw;
    }
  }

  CAbiNode(const CAbiNode&) = delete;
  CAbiNode& operator=(const CAbiNode&) = delete;

  ~CAbiNode() override {
    try {
      close();
    } catch (...) {
    }
    destroy();
  }

  const std::vector<vp::PortSpec>& input_ports() const noexcept override {
    return inputs_;
  }
  const std::vector<vp::PortSpec>& output_ports() const noexcept override {
    return outputs_;
  }
  bool is_source() const noexcept override {
    return api_.is_source && api_.is_source(api_.instance) != 0;
  }
  std::uint64_t observed_copies() const noexcept override {
    return observed_copies_.load(std::memory_order_relaxed);
  }

  void open(const vp::NodeContext& context) override {
    stop_requested_ = context.stop_requested;
    nodrix_node_context_v2 raw{
        sizeof(nodrix_node_context_v2),
        context.name.c_str(),
        context.parameters_json.c_str(),
        context.run_dir.c_str(),
        context.device.c_str(),
        this,
        stop_requested_callback,
    };
    check(api_.open(api_.instance, &raw), "open");
    opened_ = true;
  }

  void run_source(vp::Emitter& emitter) override {
    invoke({}, emitter, "source process");
  }

  void process(
      std::span<const vp::Message> inputs, vp::Emitter& emitter) override {
    invoke(inputs, emitter, "process");
  }

  void flush(vp::Emitter& emitter) override {
    EmitState state{this, &emitter, {}};
    const nodrix_status_v2 status =
        api_.flush(api_.instance, emit_callback, &state);
    if (!state.error.empty()) throw std::runtime_error(state.error);
    check(status, "flush");
  }

  void close() override {
    if (!opened_ || closed_) return;
    closed_ = true;
    check(api_.close(api_.instance), "close");
  }

 private:
  struct EmitState {
    CAbiNode* node;
    vp::Emitter* emitter;
    std::string error;
  };

  struct NativeInputs {
    std::vector<nodrix_message_v2> values;
  };

  static void emit_callback(
      void* opaque,
      std::uint32_t output_port,
      const nodrix_message_v2* message) {
    auto* state = static_cast<EmitState*>(opaque);
    if (!state || !state->error.empty()) return;
    try {
      if (!message ||
          message->struct_size < NODRIX_MESSAGE_V2_REQUIRED_SIZE) {
        throw std::runtime_error("Plugin emitted an invalid message");
      }
      state->emitter->emit(
          output_port, state->node->from_c_message(*message));
    } catch (const std::exception& error) {
      state->error = error.what();
    } catch (...) {
      state->error = "Plugin emit callback failed with an unknown error";
    }
  }

  NativeInputs to_c_messages(
      std::span<const vp::Message> inputs) const {
    NativeInputs result;
    result.values.reserve(inputs.size());
    for (const vp::Message& message : inputs) {
      nodrix_message_v2 raw{};
      raw.struct_size = sizeof(raw);
      raw.type_id = message.type_id;
      raw.sequence = message.sequence;
      raw.source_timestamp_ns = message.source_timestamp_ns;
      raw.runtime_timestamp_ns = message.runtime_timestamp_ns;
      raw.correlation = {
          sizeof(nodrix_correlation_v2),
          message.trace_id_integer
              ? NODRIX_CORRELATION_TRACE_ID_INTEGER
              : 0u,
          c_string_view(message.pipeline_id),
          c_string_view(message.run_id),
          c_string_view(message.source_id),
          c_string_view(message.stream_id),
          c_string_view(message.trace_id),
          c_string_view(message.span_id),
      };
      raw.end_of_stream = message.end_of_stream ? 1 : 0;
      raw.present = message.present ? 1 : 0;
      raw.payload.struct_size = sizeof(nodrix_buffer_v2);
      raw.payload.data = reinterpret_cast<const std::uint8_t*>(
          message.payload.data());
      raw.payload.size = message.payload.size();
      raw.payload.owner = message.payload.owner_handle();
      raw.payload.retain =
          message.payload ? retain_native_buffer : nullptr;
      raw.payload.release =
          message.payload ? release_native_buffer : nullptr;
      if (message.device_memory) {
        const auto& memory = *message.device_memory;
        raw.payload.memory = {
            sizeof(nodrix_memory_handle_v2),
            static_cast<std::uint32_t>(memory.domain),
            memory.device_index,
            memory.handle,
            memory.offset,
            memory.size,
            memory.flags,
            memory.owner,
            memory.retain,
            memory.release,
        };
      } else {
        raw.payload.memory = {
            sizeof(nodrix_memory_handle_v2),
            NODRIX_MEMORY_HOST,
            0,
            0,
            0,
            message.payload.size(),
            NODRIX_MEMORY_FLAG_HOST_VISIBLE |
                NODRIX_MEMORY_FLAG_READ_ONLY,
            message.payload.owner_handle(),
            message.payload ? retain_native_buffer : nullptr,
            message.payload ? release_native_buffer : nullptr,
        };
      }
      result.values.push_back(raw);
    }
    return result;
  }

  vp::Message from_c_message(const nodrix_message_v2& raw) const {
    if (raw.correlation.struct_size <
        NODRIX_CORRELATION_V2_REQUIRED_SIZE) {
      throw std::runtime_error(
          "Plugin emitted an invalid correlation structure");
    }
    if (raw.payload.struct_size < NODRIX_BUFFER_V2_REQUIRED_SIZE ||
        raw.payload.memory.struct_size <
            NODRIX_MEMORY_HANDLE_V2_REQUIRED_SIZE) {
      throw std::runtime_error(
          "Plugin emitted an invalid memory structure");
    }
    if (!valid_memory_domain(raw.payload.memory.domain)) {
      throw std::runtime_error(
          "Plugin emitted an unknown memory domain");
    }
    vp::Message message;
    message.type_id = raw.type_id;
    message.sequence = raw.sequence;
    message.source_timestamp_ns = raw.source_timestamp_ns;
    message.runtime_timestamp_ns = raw.runtime_timestamp_ns;
    message.pipeline_id =
        copy_c_string(raw.correlation.pipeline_id, "pipeline_id");
    message.run_id = copy_c_string(raw.correlation.run_id, "run_id");
    message.source_id =
        copy_c_string(raw.correlation.source_id, "source_id");
    message.stream_id =
        copy_c_string(raw.correlation.stream_id, "stream_id");
    message.trace_id =
        copy_c_string(raw.correlation.trace_id, "trace_id");
    message.span_id =
        copy_c_string(raw.correlation.span_id, "span_id");
    message.trace_id_integer =
        (raw.correlation.flags &
         NODRIX_CORRELATION_TRACE_ID_INTEGER) != 0;
    message.present = raw.present != 0;
    message.end_of_stream = raw.end_of_stream != 0;

    const nodrix_buffer_v2& payload = raw.payload;
    if (payload.size > 0 && payload.data) {
      if (payload.retain && payload.release) {
        payload.retain(payload.owner);
        auto* lease =
            new CBufferLease{payload.owner, payload.release};
        message.payload = vp::Buffer::wrap(
            const_cast<std::uint8_t*>(payload.data),
            payload.size,
            release_plugin_buffer,
            lease);
      } else {
        message.payload = vp::Buffer::allocate(payload.size);
        std::memcpy(
            message.payload.data(), payload.data, payload.size);
        observed_copies_.fetch_add(1, std::memory_order_relaxed);
      }
    } else if (
        payload.size > 0 &&
        payload.memory.domain == NODRIX_MEMORY_HOST) {
      throw std::runtime_error(
          "Plugin emitted host memory without a data pointer");
    }

    if (payload.memory.domain != NODRIX_MEMORY_HOST) {
      vp::DeviceBufferDescriptor memory;
      memory.domain =
          static_cast<vp::MemoryDomain>(payload.memory.domain);
      memory.device_index = payload.memory.device_id;
      memory.handle = payload.memory.handle;
      memory.offset = payload.memory.offset;
      memory.size = payload.memory.size;
      memory.flags = payload.memory.flags;
      memory.owner = payload.memory.owner;
      memory.retain = payload.memory.retain;
      memory.release = payload.memory.release;
      if (memory.owner && memory.retain) memory.retain(memory.owner);
      message.device_memory = std::move(memory);
    }
    return message;
  }

  void invoke(
      std::span<const vp::Message> inputs,
      vp::Emitter& emitter,
      const char* operation) {
    NativeInputs native = to_c_messages(inputs);
    EmitState state{this, &emitter, {}};
    const nodrix_status_v2 status = api_.process(
        api_.instance,
        native.values.empty() ? nullptr : native.values.data(),
        native.values.size(),
        emit_callback,
        &state);
    if (!state.error.empty()) throw std::runtime_error(state.error);
    check(status, operation);
  }

  void validate_api() const {
    if (api_.struct_size < NODRIX_NODE_API_V2_REQUIRED_SIZE ||
        api_.abi_version != NODRIX_C_ABI_VERSION ||
        !api_.instance || !api_.input_count || !api_.output_count ||
        !api_.input_port || !api_.output_port || !api_.is_source ||
        !api_.open || !api_.process || !api_.flush || !api_.close ||
        !api_.last_error || !api_.destroy) {
      throw std::runtime_error(
          "Plugin returned an incomplete C ABI 2.0 function table");
    }
  }

  std::vector<vp::PortSpec> read_ports(bool input) const {
    const std::size_t count = input
                                  ? api_.input_count(api_.instance)
                                  : api_.output_count(api_.instance);
    std::vector<vp::PortSpec> result;
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
      nodrix_port_v2 port{
          sizeof(nodrix_port_v2), nullptr, nullptr, nullptr};
      const nodrix_status_v2 status =
          input ? api_.input_port(api_.instance, index, &port)
                : api_.output_port(api_.instance, index, &port);
      check(status, input ? "input_port" : "output_port");
      if (port.struct_size < NODRIX_PORT_V2_REQUIRED_SIZE ||
          !port.name || !port.type) {
        throw std::runtime_error("Plugin returned an invalid port");
      }
      const std::string memory =
          port.memory ? port.memory : "any";
      if (!valid_port_memory(memory)) {
        throw std::runtime_error(
            "Plugin returned an unknown port memory domain");
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

  void check(nodrix_status_v2 status, const char* operation) const {
    if (status == NODRIX_STATUS_OK) return;
    std::string message =
        "Plugin C ABI 2.0 " + std::string(operation) +
        " failed with status " + std::to_string(status);
    const char* detail =
        api_.last_error && api_.instance
            ? api_.last_error(api_.instance)
            : nullptr;
    if (detail && *detail) message += ": " + std::string(detail);
    throw std::runtime_error(message);
  }

  void destroy() noexcept {
    if (!api_.instance) return;
    void* instance = api_.instance;
    api_.instance = nullptr;
    if (api_.destroy) api_.destroy(instance);
  }

  static std::uint8_t stop_requested_callback(void* opaque) {
    const auto* self = static_cast<const CAbiNode*>(opaque);
    return self && self->stop_requested_ &&
                   self->stop_requested_->load(std::memory_order_acquire)
               ? 1
               : 0;
  }

  std::shared_ptr<DynamicLibrary> library_;
  std::string node_type_;
  std::string parameters_json_;
  nodrix_node_api_v2 api_{};
  std::vector<vp::PortSpec> inputs_;
  std::vector<vp::PortSpec> outputs_;
  bool opened_{false};
  bool closed_{false};
  const std::atomic<bool>* stop_requested_{nullptr};
  mutable std::atomic<std::uint64_t> observed_copies_{0};
};

std::unique_ptr<vp::Node> create_c_abi_node(
    std::string_view reference, std::string parameters_json) {
  constexpr std::string_view prefix = "native:";
  if (!reference.starts_with(prefix)) {
    throw std::runtime_error("Invalid native plugin reference");
  }
  const std::string_view body = reference.substr(prefix.size());
  const std::size_t separator = body.rfind('#');
  if (separator == std::string_view::npos || separator == 0 ||
      separator + 1 >= body.size()) {
    throw std::runtime_error(
        "Native plugin reference must be native:/path/library#node-type");
  }
  fs::path library_path(std::string(body.substr(0, separator)));
  if (!library_path.is_absolute()) {
    throw std::runtime_error(
        "Native runner requires an absolute plugin library path");
  }
  if (!fs::is_regular_file(library_path)) {
    throw std::runtime_error(
        "Native plugin library does not exist: " +
        library_path.string());
  }
  return std::make_unique<CAbiNode>(
      std::move(library_path),
      std::string(body.substr(separator + 1)),
      std::move(parameters_json));
}

struct NodeStats {
  std::atomic<std::uint64_t> process_calls{0};
  std::atomic<std::uint64_t> output_messages{0};
  std::atomic<std::uint64_t> errors{0};
  std::atomic<std::uint64_t> total_process_ns{0};
  std::atomic<std::uint64_t> min_process_ns{
      (std::numeric_limits<std::uint64_t>::max)()};
  std::atomic<std::uint64_t> max_process_ns{0};
  std::atomic<std::uint64_t> synchronization_misses{0};
  mutable std::mutex duration_samples_mutex;
  std::array<std::uint64_t, 4096> duration_samples{};
  std::size_t duration_sample_count{0};
  std::atomic<LifecycleState> state{LifecycleState::Created};
  std::atomic<std::int64_t> state_timestamp_ns{0};
  std::atomic<std::uint64_t> restart_count{0};
  std::string state_reason;
  std::string last_error;

  NodeStats() = default;
  NodeStats(const NodeStats&) = delete;
  NodeStats& operator=(const NodeStats&) = delete;
  NodeStats(NodeStats&& other) noexcept {
    assign_from(other);
  }
  NodeStats& operator=(NodeStats&& other) noexcept {
    if (this != &other) assign_from(other);
    return *this;
  }

  void observe(std::uint64_t duration) noexcept {
    const std::uint64_t call =
        process_calls.fetch_add(1, std::memory_order_relaxed);
    total_process_ns.fetch_add(duration, std::memory_order_relaxed);
    std::uint64_t minimum =
        min_process_ns.load(std::memory_order_relaxed);
    while (duration < minimum &&
           !min_process_ns.compare_exchange_weak(
               minimum, duration, std::memory_order_relaxed)) {
    }
    std::uint64_t maximum =
        max_process_ns.load(std::memory_order_relaxed);
    while (duration > maximum &&
           !max_process_ns.compare_exchange_weak(
               maximum, duration, std::memory_order_relaxed)) {
    }
    {
      std::lock_guard lock(duration_samples_mutex);
      duration_samples[call % duration_samples.size()] = duration;
      duration_sample_count = std::min<std::size_t>(
          duration_sample_count + 1, duration_samples.size());
    }
  }

 private:
  void assign_from(const NodeStats& other) noexcept {
    process_calls.store(
        other.process_calls.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    output_messages.store(
        other.output_messages.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    errors.store(
        other.errors.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    total_process_ns.store(
        other.total_process_ns.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    min_process_ns.store(
        other.min_process_ns.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    max_process_ns.store(
        other.max_process_ns.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    synchronization_misses.store(
        other.synchronization_misses.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    {
      std::lock_guard lock(other.duration_samples_mutex);
      duration_samples = other.duration_samples;
      duration_sample_count = other.duration_sample_count;
    }
    state.store(
        other.state.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    state_timestamp_ns.store(
        other.state_timestamp_ns.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    restart_count.store(
        other.restart_count.load(std::memory_order_relaxed),
        std::memory_order_relaxed);
    state_reason = other.state_reason;
    last_error = other.last_error;
  }
};

struct EdgeStats {
  std::atomic<std::uint64_t> enqueued{0};
  std::atomic<std::uint64_t> dequeued{0};
  std::atomic<std::uint64_t> dropped{0};
  std::atomic<std::uint64_t> shutdown_discarded{0};
  std::atomic<std::size_t> max_depth{0};

  void observe_depth(std::size_t depth) noexcept {
    std::size_t maximum = max_depth.load(std::memory_order_relaxed);
    while (depth > maximum &&
           !max_depth.compare_exchange_weak(
               maximum, depth, std::memory_order_relaxed)) {
    }
  }
};

class Edge final {
 public:
  Edge(EdgeDef definition, std::atomic<bool>& stop)
      : definition_(std::move(definition)), stop_(stop) {
    if (definition_.policy == QueuePolicy::Latest || definition_.policy == QueuePolicy::DropOldest) {
      mpmc_ = std::make_unique<vp::MpmcQueue<vp::Message>>(definition_.capacity);
    } else {
      spsc_ = std::make_unique<vp::SpscQueue<vp::Message>>(definition_.capacity);
    }
  }

  bool publish(vp::Message message) {
    if (message.end_of_stream) return publish_eos(std::move(message));
    bool accepted = false;
    switch (definition_.policy) {
      case QueuePolicy::Block:
        accepted = push_until(std::move(message));
        break;
      case QueuePolicy::DropNewest:
        accepted = try_push(std::move(message));
        if (!accepted) ++stats_.dropped;
        break;
      case QueuePolicy::Latest:
      case QueuePolicy::DropOldest: {
        vp::Message stale;
        while (!(accepted = try_push(std::move(message)))) {
          if (try_pop(stale)) ++stats_.dropped;
          else vp::cpu_relax();
        }
        break;
      }
    }
    if (accepted) {
      ++stats_.enqueued;
      stats_.observe_depth(size_approx());
    }
    return accepted;
  }

  bool consume(vp::Message& message) {
    std::uint32_t spins = 0;
    while (!try_pop(message)) {
      if (stop_.load(std::memory_order_acquire) && size_approx() == 0) return false;
      if (++spins < 512) vp::cpu_relax();
      else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    ++stats_.dequeued;
    return true;
  }

  bool try_consume(vp::Message& message) {
    if (!try_pop(message)) return false;
    ++stats_.dequeued;
    return true;
  }

  std::size_t depth() const noexcept { return size_approx(); }

  void discard_pending() {
    vp::Message message;
    while (try_pop(message)) {
      ++stats_.shutdown_discarded;
    }
  }

  const EdgeDef& definition() const noexcept { return definition_; }
  const EdgeStats& stats() const noexcept { return stats_; }

 private:
  template <typename U>
  bool try_push(U&& message) {
    if (spsc_) return spsc_->try_push(std::forward<U>(message));
    return mpmc_->try_push(std::forward<U>(message));
  }

  bool try_pop(vp::Message& message) {
    if (spsc_) return spsc_->try_pop(message);
    return mpmc_->try_pop(message);
  }

  std::size_t size_approx() const noexcept {
    return spsc_ ? spsc_->size_approx() : mpmc_->size_approx();
  }

  bool push_until(vp::Message message) {
    std::uint32_t spins = 0;
    while (!try_push(std::move(message))) {
      if (stop_.load(std::memory_order_acquire)) return false;
      if (++spins < 512) vp::cpu_relax();
      else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    return true;
  }

  bool publish_eos(vp::Message message) {
    // EOS is never discarded. For overwrite queues, old data is removed only
    // if needed to guarantee graph shutdown.
    std::uint32_t spins = 0;
    while (!try_push(std::move(message))) {
      if (definition_.policy == QueuePolicy::Latest || definition_.policy == QueuePolicy::DropOldest) {
        vp::Message stale;
        if (try_pop(stale)) ++stats_.dropped;
      } else if (stop_.load(std::memory_order_acquire)) {
        return false;
      } else if (++spins < 512) {
        vp::cpu_relax();
      } else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    ++stats_.enqueued;
    stats_.observe_depth(size_approx());
    return true;
  }

  EdgeDef definition_;
  std::atomic<bool>& stop_;
  std::unique_ptr<vp::SpscQueue<vp::Message>> spsc_;
  std::unique_ptr<vp::MpmcQueue<vp::Message>> mpmc_;
  EdgeStats stats_{};
};

struct LoadedNode {
  std::string name;
  std::string uses;
  std::string parameters_json;
  NodeHolder node;
  std::vector<Edge*> inputs;
  std::vector<std::vector<Edge*>> outputs;
  SynchronizationPolicy synchronization{
      SynchronizationPolicy::ExactSequence};
  std::uint64_t tolerance_ns{20'000'000};
  std::string trigger_port;
  std::vector<vp::Message> synchronized_cache;
  std::vector<bool> synchronized_have;
  std::vector<bool> synchronized_closed;
  NodeStats stats;
};

class NodeEmitter final : public vp::Emitter {
 public:
  explicit NodeEmitter(LoadedNode& owner) : owner_(owner) {}

  void emit(std::size_t output_port, vp::Message message) override {
    if (output_port >= owner_.outputs.size()) throw std::runtime_error("Output port index out of range");
    auto& edges = owner_.outputs[output_port];
    if (edges.empty()) return;
    ++owner_.stats.output_messages;
    for (std::size_t i = 0; i < edges.size(); ++i) {
      if (i + 1 == edges.size()) edges[i]->publish(std::move(message));
      else edges[i]->publish(message);
    }
  }

  void close_outputs() {
    for (auto& port_edges : owner_.outputs) {
      for (Edge* edge : port_edges) edge->publish(vp::Message::eos());
    }
  }

 private:
  LoadedNode& owner_;
};

class Runtime final {
 public:
  explicit Runtime(Plan plan) : plan_(std::move(plan)) {}

  void build() {
    nodes_.reserve(plan_.nodes.size());
    for (const NodeDef& definition : plan_.nodes) {
      NodeHolder holder;
      if (definition.uses.starts_with("native.")) {
        auto builtin = vp::create_builtin_node(definition.uses, definition.parameters_json);
        vp::Node* raw = builtin.release();
        holder = NodeHolder(raw, [](vp::Node* node) { delete node; });
      } else if (definition.uses.starts_with("native:")) {
        auto plugin =
            create_c_abi_node(definition.uses, definition.parameters_json);
        vp::Node* raw = plugin.release();
        holder = NodeHolder(raw, [](vp::Node* node) { delete node; });
      } else {
        throw std::runtime_error("Native engine cannot load node: " + definition.uses);
      }
      LoadedNode loaded;
      loaded.name = definition.name;
      loaded.uses = definition.uses;
      loaded.parameters_json = definition.parameters_json;
      loaded.node = std::move(holder);
      loaded.synchronization = definition.synchronization;
      loaded.tolerance_ns = definition.tolerance_ns;
      loaded.trigger_port = definition.trigger_port;
      loaded.inputs.resize(loaded.node->input_ports().size(), nullptr);
      loaded.outputs.resize(loaded.node->output_ports().size());
      loaded.synchronized_cache.resize(
          loaded.node->input_ports().size());
      loaded.synchronized_have.resize(
          loaded.node->input_ports().size(), false);
      loaded.synchronized_closed.resize(
          loaded.node->input_ports().size(), false);
      for (const std::string& optional : definition.optional_inputs) {
        const auto& ports = loaded.node->input_ports();
        const auto found = std::find_if(
            ports.begin(),
            ports.end(),
            [&](const vp::PortSpec& port) {
              return port.name == optional;
            });
        if (found == ports.end() || !found->optional) {
          throw std::runtime_error(
              "SYNC marks a required or unknown input optional: " +
              loaded.name + "." + optional);
        }
      }
      if (!node_index_.emplace(loaded.name, nodes_.size()).second) {
        throw std::runtime_error("Duplicate node name: " + loaded.name);
      }
      nodes_.push_back(std::move(loaded));
    }

    edges_.reserve(plan_.edges.size());
    for (const EdgeDef& definition : plan_.edges) {
      auto source_it = node_index_.find(definition.source_node);
      auto target_it = node_index_.find(definition.target_node);
      if (source_it == node_index_.end() || target_it == node_index_.end()) {
        throw std::runtime_error("Edge references unknown node");
      }
      LoadedNode& source = nodes_[source_it->second];
      LoadedNode& target = nodes_[target_it->second];
      const auto output_index = port_index(source.node->output_ports(), definition.source_port);
      const auto input_index = port_index(target.node->input_ports(), definition.target_port);
      const auto& output_type = source.node->output_ports()[output_index].type;
      const auto& input_type = target.node->input_ports()[input_index].type;
      if (!(output_type == input_type || output_type == "core.any" || input_type == "core.any")) {
        throw std::runtime_error("Type mismatch: " + output_type + " -> " + input_type);
      }
      if (target.inputs[input_index] != nullptr) {
        throw std::runtime_error("Input already connected: " + target.name + "." + definition.target_port);
      }
      const std::string output_memory =
          source.node->output_ports()[output_index].memory;
      const std::string input_memory =
          target.node->input_ports()[input_index].memory;
      if (!(output_memory == "any" || input_memory == "any" ||
            output_memory == input_memory)) {
        throw std::runtime_error(
            "Memory-domain mismatch: " + output_memory + " -> " +
            input_memory);
      }
      EdgeDef resolved_definition = definition;
      resolved_definition.source_memory = output_memory;
      resolved_definition.target_memory = input_memory;
      resolved_definition.resolved_memory =
          output_memory != "any" ? output_memory : input_memory;
      edges_.push_back(
          std::make_unique<Edge>(
              std::move(resolved_definition), stop_));
      Edge* edge = edges_.back().get();
      source.outputs[output_index].push_back(edge);
      target.inputs[input_index] = edge;
    }

    for (LoadedNode& node : nodes_) {
      for (std::size_t i = 0; i < node.inputs.size(); ++i) {
        if (node.inputs[i] == nullptr) {
          if (!node.node->input_ports()[i].optional) {
            throw std::runtime_error(
                "Unconnected input: " + node.name + "." +
                node.node->input_ports()[i].name);
          }
        }
      }
      if (!node.trigger_port.empty()) {
        const auto& ports = node.node->input_ports();
        const auto trigger = std::find_if(
            ports.begin(),
            ports.end(),
            [&](const vp::PortSpec& port) {
              return port.name == node.trigger_port;
            });
        if (trigger == ports.end() || trigger->optional) {
          throw std::runtime_error(
              "Synchronization trigger must be a required input: " +
              node.name + "." + node.trigger_port);
        }
      }
    }
  }

  int run() {
    const auto start = std::chrono::steady_clock::now();
    try {
      for (LoadedNode& node : nodes_) {
        transition(
            node,
            LifecycleState::Configuring,
            "opening native node");
        node.node->open(
            {
                node.name,
                node.parameters_json,
                plan_.run_dir,
                "auto",
                &stop_,
            });
        transition(node, LifecycleState::Ready, "open completed");
      }
      for (LoadedNode& node : nodes_) {
        transition(node, LifecycleState::Starting, "worker starting");
      }
    } catch (const std::exception& error) {
      record_error(error.what());
      stop_.store(true, std::memory_order_release);
      for (LoadedNode& node : nodes_) {
        if (node.stats.state.load(std::memory_order_acquire) ==
            LifecycleState::Configuring) {
          transition(
              node, LifecycleState::Failed, error.what(), error.what());
        }
      }
      close_nodes();
      const auto finish = std::chrono::steady_clock::now();
      write_report(
          std::chrono::duration<double>(finish - start).count());
      return 1;
    }

    std::vector<std::thread> threads;
    threads.reserve(nodes_.size());
    for (LoadedNode& node : nodes_) {
      threads.emplace_back([this, &node] { run_node(node); });
    }
    std::thread monitor([this, start] { monitor_runtime(start); });
    for (auto& thread : threads) thread.join();
    workers_finished_.store(true, std::memory_order_release);
    if (monitor.joinable()) monitor.join();

    discard_pending_messages();
    close_nodes();
    const auto finish = std::chrono::steady_clock::now();
    const double duration = std::chrono::duration<double>(finish - start).count();
    write_report(duration);
    write_live_status(duration, true);
    if (first_error_) {
      try { std::rethrow_exception(first_error_); }
      catch (const std::exception& error) {
        std::cerr << "Nodrix native runtime failed: " << error.what() << '\n';
      }
      return 1;
    }
    return 0;
  }

  private:
  static std::int64_t wall_time_ns() noexcept {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
  }

  void transition(
      LoadedNode& node,
      LifecycleState state,
      std::string reason = {},
      std::string last_error = {}) {
    {
      std::lock_guard lock(lifecycle_mutex_);
      node.stats.state_reason = reason;
      if (!last_error.empty()) node.stats.last_error = last_error;
      node.stats.state_timestamp_ns.store(
          wall_time_ns(), std::memory_order_release);
      node.stats.state.store(state, std::memory_order_release);
    }
    append_event(
        "node_state",
        node.name,
        lifecycle_name(state),
        reason);
  }

  void append_event(
      std::string_view event,
      std::string_view node = {},
      std::string_view state = {},
      std::string_view reason = {}) {
    std::lock_guard lock(event_mutex_);
    fs::create_directories(plan_.run_dir);
    std::ofstream output(
        fs::path(plan_.run_dir) / "native-events.jsonl",
        std::ios::app);
    if (!output) return;
    output << "{\"timestamp_ns\":" << wall_time_ns()
           << ",\"event\":\"" << json_escape(event) << "\"";
    if (!node.empty()) {
      output << ",\"node\":\"" << json_escape(node) << "\"";
    }
    if (!state.empty()) {
      output << ",\"state\":\"" << json_escape(state) << "\"";
    }
    if (!reason.empty()) {
      output << ",\"reason\":\"" << json_escape(reason) << "\"";
    }
    output << "}\n";
  }

  void record_error(const std::string& message) {
    std::lock_guard lock(error_mutex_);
    if (first_error_) return;
    first_error_ =
        std::make_exception_ptr(std::runtime_error(message));
  }

  void close_nodes() {
    for (auto it = nodes_.rbegin(); it != nodes_.rend(); ++it) {
      const LifecycleState current =
          it->stats.state.load(std::memory_order_acquire);
      if (current != LifecycleState::Failed) {
        transition(
            *it, LifecycleState::Stopping, "closing native node");
      }
      try {
        it->node->close();
        if (current != LifecycleState::Failed) {
          transition(*it, LifecycleState::Stopped, "close completed");
        }
      } catch (const std::exception& error) {
        ++it->stats.errors;
        transition(
            *it,
            LifecycleState::Failed,
            "close failed",
            error.what());
        record_error(error.what());
      }
    }
  }

  void discard_pending_messages() {
    for (LoadedNode& node : nodes_) {
      for (std::size_t index = 0;
           index < node.synchronized_cache.size();
           ++index) {
        node.synchronized_cache[index] = {};
        node.synchronized_have[index] = false;
      }
    }
    for (const auto& edge : edges_) {
      edge->discard_pending();
    }
  }

  void monitor_runtime(
      std::chrono::steady_clock::time_point started) {
    auto next_metrics = started;
    std::optional<std::chrono::steady_clock::time_point> stopping;
    while (!workers_finished_.load(std::memory_order_acquire)) {
      const auto now = std::chrono::steady_clock::now();
      const int signal_number = g_received_signal;
      if (signal_number != 0 &&
          !stop_.exchange(true, std::memory_order_acq_rel)) {
        append_event(
            "runtime_stop_requested",
            {},
            "STOPPING",
            "signal " + std::to_string(signal_number));
        for (LoadedNode& node : nodes_) {
          const LifecycleState state =
              node.stats.state.load(std::memory_order_acquire);
          if (state == LifecycleState::Running ||
              state == LifecycleState::Starting) {
            transition(
                node,
                LifecycleState::Stopping,
                "runtime signal received");
          }
        }
      }
      if (stop_.load(std::memory_order_acquire) && !stopping) {
        stopping = now;
      }
      if (stopping &&
          now - *stopping >
              std::chrono::milliseconds(plan_.shutdown_timeout_ms)) {
        write_forced_shutdown(signal_number);
        std::_Exit(signal_number ? 128 + signal_number : 3);
      }
      if (now >= next_metrics) {
        write_live_status(
            std::chrono::duration<double>(now - started).count(),
            false);
        next_metrics =
            now + std::chrono::milliseconds(
                      std::max<std::uint64_t>(
                          100, plan_.metrics_interval_ms));
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
  }

  void write_forced_shutdown(int signal_number) {
    append_event(
        "forced_shutdown",
        {},
        "FAILED",
        "shutdown timeout exceeded");
    fs::create_directories(plan_.run_dir);
    std::ofstream output(
        fs::path(plan_.run_dir) / "forced-shutdown.json");
    if (!output) return;
    output << "{\"status\":\"forced_shutdown\","
           << "\"timeout_ms\":" << plan_.shutdown_timeout_ms << ","
           << "\"signal\":" << signal_number << "}\n";
    output.flush();
  }

  static std::size_t port_index(const std::vector<vp::PortSpec>& ports, const std::string& name) {
    for (std::size_t i = 0; i < ports.size(); ++i) {
      if (ports[i].name == name) return i;
    }
    throw std::runtime_error("Unknown port: " + name);
  }

  void run_node(LoadedNode& loaded) noexcept {
    NodeEmitter emitter(loaded);
    try {
      transition(loaded, LifecycleState::Running, "worker running");
      if (loaded.node->is_source()) {
        loaded.node->run_source(emitter);
      } else {
        run_processor(loaded, emitter);
      }
      transition(
          loaded,
          LifecycleState::Stopping,
          stop_.load(std::memory_order_acquire)
              ? "runtime stop requested"
              : "input completed");
      loaded.node->flush(emitter);
      if (loaded.node->observed_copies() > 0) {
        transition(
            loaded,
            LifecycleState::Degraded,
            "unplanned host payload copies observed");
      }
    } catch (const std::exception& error) {
      ++loaded.stats.errors;
      transition(
          loaded,
          LifecycleState::Failed,
          "native node failed",
          error.what());
      {
        std::lock_guard lock(error_mutex_);
        if (!first_error_) first_error_ = std::current_exception();
      }
      stop_.store(true, std::memory_order_release);
    } catch (...) {
      ++loaded.stats.errors;
      transition(
          loaded,
          LifecycleState::Failed,
          "native node failed",
          "unknown native exception");
      {
        std::lock_guard lock(error_mutex_);
        if (!first_error_) first_error_ = std::current_exception();
      }
      stop_.store(true, std::memory_order_release);
    }
    emitter.close_outputs();
  }

  void run_processor(LoadedNode& loaded, NodeEmitter& emitter) {
    std::vector<vp::Message> current(loaded.inputs.size());
    for (;;) {
      if (!receive_synchronized(loaded, current)) return;
      const auto begin = std::chrono::steady_clock::now();
      loaded.node->process(std::span<const vp::Message>(current.data(), current.size()), emitter);
      const auto end = std::chrono::steady_clock::now();
      loaded.stats.observe(static_cast<std::uint64_t>(
          std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count()));
    }
  }

  static vp::Message absent_message() {
    vp::Message message;
    message.present = false;
    return message;
  }

  bool optional_input(
      const LoadedNode& loaded, std::size_t index) const {
    return loaded.node->input_ports()[index].optional;
  }

  bool blocking_cache(LoadedNode& loaded, std::size_t index) {
    if (loaded.synchronized_have[index]) return true;
    Edge* edge = loaded.inputs[index];
    if (!edge) return false;
    if (!edge->consume(loaded.synchronized_cache[index])) return false;
    if (loaded.synchronized_cache[index].end_of_stream) {
      loaded.synchronized_closed[index] = true;
      return false;
    }
    loaded.synchronized_have[index] = true;
    return true;
  }

  void drain_cache(LoadedNode& loaded, std::size_t index) {
    Edge* edge = loaded.inputs[index];
    if (!edge || loaded.synchronized_closed[index]) return;
    vp::Message next;
    while (edge->try_consume(next)) {
      if (next.end_of_stream) {
        loaded.synchronized_closed[index] = true;
        break;
      }
      if (loaded.synchronized_have[index]) {
        ++loaded.stats.synchronization_misses;
      }
      loaded.synchronized_cache[index] = std::move(next);
      loaded.synchronized_have[index] = true;
    }
  }

  std::size_t trigger_index(const LoadedNode& loaded) const {
    if (loaded.trigger_port.empty()) {
      for (std::size_t i = 0; i < loaded.inputs.size(); ++i) {
        if (!optional_input(loaded, i)) return i;
      }
      throw std::runtime_error(
          "Synchronization requires at least one required input");
    }
    const auto& ports = loaded.node->input_ports();
    for (std::size_t i = 0; i < ports.size(); ++i) {
      if (ports[i].name == loaded.trigger_port) return i;
    }
    throw std::runtime_error("Unknown synchronization trigger");
  }

  bool receive_zip(
      LoadedNode& loaded, std::vector<vp::Message>& selected) {
    for (std::size_t i = 0; i < loaded.inputs.size(); ++i) {
      if (optional_input(loaded, i)) {
        drain_cache(loaded, i);
        if (!loaded.synchronized_have[i]) {
          selected[i] = absent_message();
          continue;
        }
      } else if (!blocking_cache(loaded, i)) {
        return false;
      }
      selected[i] = loaded.synchronized_cache[i];
      loaded.synchronized_have[i] = false;
    }
    return true;
  }

  bool receive_latest(
      LoadedNode& loaded, std::vector<vp::Message>& selected) {
    const std::size_t trigger = trigger_index(loaded);
    if (!blocking_cache(loaded, trigger)) return false;
    for (std::size_t i = 0; i < loaded.inputs.size(); ++i) {
      if (i == trigger) continue;
      drain_cache(loaded, i);
      if (!loaded.synchronized_have[i] &&
          !optional_input(loaded, i)) {
        if (!blocking_cache(loaded, i)) return false;
      }
    }
    for (std::size_t i = 0; i < loaded.inputs.size(); ++i) {
      selected[i] = loaded.synchronized_have[i]
                        ? loaded.synchronized_cache[i]
                        : absent_message();
    }
    loaded.synchronized_have[trigger] = false;
    return true;
  }

  static std::uint64_t timestamp_key(std::int64_t value) {
    return static_cast<std::uint64_t>(value) ^
           (std::uint64_t{1} << 63U);
  }

  bool receive_matching(
      LoadedNode& loaded,
      std::vector<vp::Message>& selected,
      bool approximate) {
    std::vector<std::size_t> required;
    for (std::size_t i = 0; i < loaded.inputs.size(); ++i) {
      if (!optional_input(loaded, i)) required.push_back(i);
    }
    if (required.empty()) {
      throw std::runtime_error(
          "Matching synchronization has no required input");
    }
    for (;;) {
      for (std::size_t index : required) {
        if (!blocking_cache(loaded, index)) return false;
      }
      std::size_t oldest = required.front();
      std::uint64_t minimum =
          (std::numeric_limits<std::uint64_t>::max)();
      std::uint64_t maximum = 0;
      for (std::size_t index : required) {
        const auto& message = loaded.synchronized_cache[index];
        const std::uint64_t value = approximate
                                        ? static_cast<std::uint64_t>(
                                              std::max<std::int64_t>(
                                                  0,
                                                  message.source_timestamp_ns))
                                        : message.sequence;
        if (value < minimum) {
          minimum = value;
          oldest = index;
        }
        maximum = std::max(maximum, value);
      }
      const bool matched = approximate
                               ? maximum - minimum <= loaded.tolerance_ns
                               : maximum == minimum;
      if (matched) break;
      loaded.synchronized_have[oldest] = false;
      ++loaded.stats.synchronization_misses;
    }

    const std::uint64_t target_sequence =
        loaded.synchronized_cache[required.front()].sequence;
    const std::int64_t target_timestamp =
        loaded.synchronized_cache[required.front()]
            .source_timestamp_ns;
    for (std::size_t i = 0; i < loaded.inputs.size(); ++i) {
      if (!optional_input(loaded, i)) {
        selected[i] = loaded.synchronized_cache[i];
        loaded.synchronized_have[i] = false;
        continue;
      }
      drain_cache(loaded, i);
      if (!loaded.synchronized_have[i]) {
        selected[i] = absent_message();
        continue;
      }
      const auto& candidate = loaded.synchronized_cache[i];
      const auto candidate_timestamp =
          timestamp_key(candidate.source_timestamp_ns);
      const auto target_timestamp_key =
          timestamp_key(target_timestamp);
      const std::uint64_t timestamp_distance =
          candidate_timestamp >= target_timestamp_key
              ? candidate_timestamp - target_timestamp_key
              : target_timestamp_key - candidate_timestamp;
      const bool matches =
          approximate
              ? timestamp_distance <= loaded.tolerance_ns
              : candidate.sequence == target_sequence;
      if (matches) {
        selected[i] = candidate;
        loaded.synchronized_have[i] = false;
      } else {
        selected[i] = absent_message();
        ++loaded.stats.synchronization_misses;
        const bool stale =
            approximate
                ? candidate_timestamp < target_timestamp_key &&
                      timestamp_distance > loaded.tolerance_ns
                : candidate.sequence < target_sequence;
        if (stale) {
          loaded.synchronized_have[i] = false;
        }
      }
    }
    return true;
  }

  bool receive_synchronized(
      LoadedNode& loaded, std::vector<vp::Message>& selected) {
    if (loaded.inputs.empty()) return false;
    if (loaded.inputs.size() == 1 &&
        !optional_input(loaded, 0)) {
      if (!blocking_cache(loaded, 0)) return false;
      selected[0] = loaded.synchronized_cache[0];
      loaded.synchronized_have[0] = false;
      return true;
    }
    switch (loaded.synchronization) {
      case SynchronizationPolicy::Zip:
        return receive_zip(loaded, selected);
      case SynchronizationPolicy::LatestAvailable:
        return receive_latest(loaded, selected);
      case SynchronizationPolicy::ApproximateTimestamp:
        return receive_matching(loaded, selected, true);
      case SynchronizationPolicy::ExactSequence:
        return receive_matching(loaded, selected, false);
    }
    return false;
  }

  static double percentile_ms(
      const NodeStats& stats, double fraction) {
    std::lock_guard lock(stats.duration_samples_mutex);
    if (stats.duration_sample_count == 0) return 0.0;
    std::vector<std::uint64_t> samples(
        stats.duration_samples.begin(),
        stats.duration_samples.begin() +
            static_cast<std::ptrdiff_t>(
                stats.duration_sample_count));
    std::sort(samples.begin(), samples.end());
    const std::size_t index = std::min<std::size_t>(
        samples.size() - 1,
        static_cast<std::size_t>(
            fraction * static_cast<double>(samples.size() - 1)));
    return static_cast<double>(samples[index]) / 1e6;
  }

  void write_live_status(double duration_seconds, bool completed) {
    fs::create_directories(plan_.run_dir);
    const fs::path target =
        fs::path(plan_.run_dir) / "status.json";
    const fs::path temporary =
        fs::path(plan_.run_dir) / "status.json.tmp";
    std::ofstream output(temporary);
    if (!output) return;
    const bool failed = [&] {
      std::lock_guard lock(error_mutex_);
      return static_cast<bool>(first_error_);
    }();
    const char* status =
        failed ? "failed"
               : completed
                     ? "completed"
                     : stop_.load(std::memory_order_acquire)
                           ? "stopping"
                           : "running";
    output << "{\n"
           << "  \"pipeline\":\""
           << json_escape(plan_.pipeline_name) << "\",\n"
           << "  \"engine\":\"native-cpp20\",\n"
           << "  \"status\":\"" << status << "\",\n"
           << "  \"duration_seconds\":"
           << std::setprecision(12) << duration_seconds << ",\n"
           << "  \"nodes\":{\n";
    for (std::size_t i = 0; i < nodes_.size(); ++i) {
      const LoadedNode& node = nodes_[i];
      const std::uint64_t calls =
          node.stats.process_calls.load(std::memory_order_relaxed);
      const std::uint64_t outputs =
          node.stats.output_messages.load(std::memory_order_relaxed);
      const std::uint64_t errors =
          node.stats.errors.load(std::memory_order_relaxed);
      const double mean_ms =
          calls
              ? static_cast<double>(
                    node.stats.total_process_ns.load(
                        std::memory_order_relaxed)) /
                    static_cast<double>(calls) / 1e6
              : 0.0;
      const double p50_ms = percentile_ms(node.stats, 0.50);
      const double p95_ms = percentile_ms(node.stats, 0.95);
      const double p99_ms = percentile_ms(node.stats, 0.99);
      const LifecycleState state =
          node.stats.state.load(std::memory_order_acquire);
      output << "    \"" << json_escape(node.name) << "\":{"
             << "\"state\":\"" << lifecycle_name(state) << "\","
             << "\"rate_hz\":"
             << (duration_seconds > 0
                     ? static_cast<double>(
                           outputs > 0 ? outputs : calls) /
                           duration_seconds
                     : 0.0)
             << ",\"mean_ms\":" << mean_ms
             << ",\"p50_ms\":" << p50_ms
             << ",\"p95_ms\":" << p95_ms
             << ",\"p99_ms\":" << p99_ms
             << ",\"messages\":" << calls
             << ",\"outputs\":" << outputs
             << ",\"errors\":" << errors
             << ",\"observed_copies\":"
             << node.node->observed_copies()
             << ",\"resources\":{"
             << "\"sync_misses\":"
             << node.stats.synchronization_misses.load(
                    std::memory_order_relaxed)
             << ",\"busy_time_seconds\":"
             << static_cast<double>(
                    node.stats.total_process_ns.load(
                        std::memory_order_relaxed)) /
                    1e9
             << ",\"overflow_drops\":0,"
             << "\"stale_skips\":0},"
             << "\"health\":{"
             << "\"alive\":"
             << (state == LifecycleState::Failed ? "false" : "true")
             << ",\"ready\":"
             << ((state == LifecycleState::Ready ||
                  state == LifecycleState::Starting ||
                  state == LifecycleState::Running ||
                  state == LifecycleState::Stopping ||
                  state == LifecycleState::Stopped)
                     ? "true"
                     : "false")
             << ",\"status\":\""
             << (state == LifecycleState::Failed
                     ? "failed"
                     : state == LifecycleState::Degraded
                           ? "degraded"
                           : "healthy")
             << "\",\"restart_count\":"
             << node.stats.restart_count.load(
                    std::memory_order_relaxed)
             << "}}"
             << (i + 1 == nodes_.size() ? "\n" : ",\n");
    }
    output << "  },\n  \"edges\":[\n";
    for (std::size_t i = 0; i < edges_.size(); ++i) {
      const Edge& edge = *edges_[i];
      const EdgeDef& definition = edge.definition();
      const EdgeStats& stats = edge.stats();
      output << "    {\"source\":\""
             << json_escape(
                    definition.source_node + "." +
                    definition.source_port)
             << "\",\"target\":\""
             << json_escape(
                    definition.target_node + "." +
                    definition.target_port)
             << "\",\"depth\":" << edge.depth()
             << ",\"capacity\":" << definition.capacity
             << ",\"policy\":\""
             << queue_policy_name(definition.policy)
             << "\",\"overflow_drops\":"
             << stats.dropped.load(std::memory_order_relaxed)
             << ",\"shutdown_discarded\":"
             << stats.shutdown_discarded.load(
                    std::memory_order_relaxed)
             << ",\"memory_domain\":\""
             << json_escape(definition.resolved_memory)
             << "\",\"planned_copies\":0"
             << ",\"stale_skips\":0}"
             << (i + 1 == edges_.size() ? "\n" : ",\n");
    }
    output << "  ]\n}\n";
    output.close();
    std::error_code error;
    fs::rename(temporary, target, error);
    if (error) {
      fs::remove(target, error);
      error.clear();
      fs::rename(temporary, target, error);
    }
  }

  void write_report(double duration_seconds) {
    fs::create_directories(plan_.run_dir);
    const fs::path report_path = fs::path(plan_.run_dir) / "native-run.json";
    std::ofstream report(report_path);
    if (!report) throw std::runtime_error("Cannot write native report");

    std::uint64_t maximum_messages = 0;
    for (const auto& node : nodes_) {
      maximum_messages = std::max(
          maximum_messages,
          node.stats.process_calls.load(std::memory_order_relaxed));
    }

    report << "{\n"
           << "  \"pipeline\": \"" << json_escape(plan_.pipeline_name) << "\",\n"
           << "  \"engine\": \"native-cpp20\",\n"
           << "  \"status\": \"" << (first_error_ ? "failed" : "completed") << "\",\n"
           << "  \"run_dir\": \"" << json_escape(plan_.run_dir) << "\",\n"
           << "  \"duration_seconds\": " << std::setprecision(12) << duration_seconds << ",\n"
           << "  \"messages_per_second\": "
           << (duration_seconds > 0 ? static_cast<double>(maximum_messages) / duration_seconds : 0.0) << ",\n"
           << "  \"nodes\": {\n";
    for (std::size_t i = 0; i < nodes_.size(); ++i) {
      const auto& node = nodes_[i];
      const std::uint64_t process_calls =
          node.stats.process_calls.load(std::memory_order_relaxed);
      const double mean_ms =
          process_calls
              ? static_cast<double>(
                    node.stats.total_process_ns.load(
                        std::memory_order_relaxed)) /
                    static_cast<double>(process_calls) / 1e6
              : 0.0;
      const double min_ms =
          process_calls
              ? node.stats.min_process_ns.load(
                    std::memory_order_relaxed) /
                    1e6
              : 0.0;
      report << "    \"" << json_escape(node.name) << "\": {"
             << "\"uses\": \"" << json_escape(node.uses) << "\", "
             << "\"messages\": " << process_calls << ", "
             << "\"outputs\": "
             << node.stats.output_messages.load(
                    std::memory_order_relaxed)
             << ", "
             << "\"errors\": "
             << node.stats.errors.load(std::memory_order_relaxed)
             << ", \"observed_copies\": "
             << node.node->observed_copies()
             << ", "
             << "\"synchronization_misses\": "
             << node.stats.synchronization_misses.load(
                    std::memory_order_relaxed)
             << ", "
             << "\"mean_ms\": " << mean_ms << ", "
             << "\"min_ms\": " << min_ms << ", "
             << "\"p50_ms\": "
             << percentile_ms(node.stats, 0.50) << ", "
             << "\"p95_ms\": "
             << percentile_ms(node.stats, 0.95) << ", "
             << "\"p99_ms\": "
             << percentile_ms(node.stats, 0.99) << ", "
             << "\"max_ms\": "
             << node.stats.max_process_ns.load(
                    std::memory_order_relaxed) /
                    1e6
             << ", \"state\": \""
             << lifecycle_name(
                    node.stats.state.load(
                        std::memory_order_acquire))
             << "\", \"state_reason\": \""
             << json_escape(node.stats.state_reason)
             << "\", \"state_timestamp_ns\": "
             << node.stats.state_timestamp_ns.load(
                    std::memory_order_relaxed)
             << ", \"last_error\": \""
             << json_escape(node.stats.last_error)
             << "\", \"restart_count\": "
             << node.stats.restart_count.load(
                    std::memory_order_relaxed)
             << "}"
             << (i + 1 == nodes_.size() ? "\n" : ",\n");
    }
    report << "  },\n  \"edges\": [\n";
    for (std::size_t i = 0; i < edges_.size(); ++i) {
      const auto& edge = *edges_[i];
      const auto& def = edge.definition();
      const auto& stats = edge.stats();
      report << "    {\"from\": \"" << json_escape(def.source_node + "." + def.source_port)
             << "\", \"to\": \"" << json_escape(def.target_node + "." + def.target_port)
             << "\", \"enqueued\": "
             << stats.enqueued.load(std::memory_order_relaxed)
             << ", \"dequeued\": "
             << stats.dequeued.load(std::memory_order_relaxed)
             << ", \"dropped\": "
             << stats.dropped.load(std::memory_order_relaxed)
             << ", \"shutdown_discarded\": "
             << stats.shutdown_discarded.load(
                    std::memory_order_relaxed)
             << ", \"memory_domain\": \""
             << json_escape(def.resolved_memory)
             << "\", \"planned_copies\": 0"
             << ", \"max_depth\": "
             << stats.max_depth.load(std::memory_order_relaxed)
             << "}"
             << (i + 1 == edges_.size() ? "\n" : ",\n");
    }
    report << "  ]\n}\n";
  }

  Plan plan_;
  std::atomic<bool> stop_{false};
  std::vector<LoadedNode> nodes_;
  std::vector<std::unique_ptr<Edge>> edges_;
  std::unordered_map<std::string, std::size_t> node_index_;
  std::mutex error_mutex_;
  std::mutex lifecycle_mutex_;
  std::mutex event_mutex_;
  std::atomic<bool> workers_finished_{false};
  std::exception_ptr first_error_;
};

}  // namespace

int main(int argc, char** argv) {
  try {
    fs::path plan_path;
    for (int i = 1; i < argc; ++i) {
      const std::string_view argument(argv[i]);
      if (argument == "--plan" && i + 1 < argc) {
        plan_path = argv[++i];
      } else if (argument == "--version") {
        std::cout << "nodrix-native-runner " << NODRIX_NATIVE_VERSION << '\n';
        return 0;
      } else {
        throw std::runtime_error("Usage: nodrix-native-runner --plan PLAN");
      }
    }
    if (plan_path.empty()) throw std::runtime_error("Missing --plan");
    std::signal(SIGINT, native_signal_handler);
    std::signal(SIGTERM, native_signal_handler);
#if defined(_WIN32) && defined(SIGBREAK)
    std::signal(SIGBREAK, native_signal_handler);
#endif
#if defined(_WIN32)
    if (!SetConsoleCtrlHandler(native_console_handler, TRUE)) {
      throw std::runtime_error(
          "Cannot install Windows console shutdown handler");
    }
#endif
    Runtime runtime(read_plan(plan_path));
    runtime.build();
    return runtime.run();
  } catch (const std::exception& error) {
    std::cerr << "Nodrix native runner error: " << error.what() << '\n';
    return 2;
  }
}
