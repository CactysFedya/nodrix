#include <atomic>
#include <cstdint>
#include <cstring>
#include <new>
#include <string>
#include <string_view>
#include <vector>

#include "nodrix/c_api.h"

namespace {

constexpr char kPipeline[] = "pipeline/тест";
constexpr char kRun[] = "run-0001";
constexpr char kSource[] = "camera.front";
constexpr char kStream[] = "/frames/main";
constexpr char kTrace[] = "trace:0123456789abcdef";
constexpr char kSpan[] = "span:fedcba9876543210";

nodrix_string_view_v2 view(const char* value) {
  return {
      sizeof(nodrix_string_view_v2),
      value,
      std::strlen(value),
  };
}

std::uint64_t json_u64(
    std::string_view json,
    std::string_view key,
    std::uint64_t fallback) {
  const std::string needle = "\"" + std::string(key) + "\"";
  std::size_t position = json.find(needle);
  if (position == std::string_view::npos) return fallback;
  position = json.find(':', position + needle.size());
  if (position == std::string_view::npos) return fallback;
  std::uint64_t result = 0;
  bool found = false;
  for (++position; position < json.size(); ++position) {
    const char ch = json[position];
    if (ch >= '0' && ch <= '9') {
      found = true;
      result = result * 10 + static_cast<unsigned>(ch - '0');
    } else if (found) {
      break;
    }
  }
  return found ? result : fallback;
}

enum class Role {
  Source,
  Bridge,
  Sink,
  OptionalSink,
  Error,
};

struct Instance final {
  Role role{Role::Bridge};
  std::uint64_t count{32};
  std::uint64_t received{0};
  std::string error;
  void* control_context{nullptr};
  nodrix_stop_requested_v2 stop_requested{nullptr};
};

struct OwnedPayload final {
  explicit OwnedPayload(std::uint8_t value) : bytes(64, value) {
    live.fetch_add(1, std::memory_order_relaxed);
  }

  ~OwnedPayload() {
    live.fetch_sub(1, std::memory_order_relaxed);
  }

  std::atomic<std::size_t> references{1};
  std::vector<std::uint8_t> bytes;
  static std::atomic<std::size_t> live;
};

std::atomic<std::size_t> OwnedPayload::live{0};

void retain_payload(void* opaque) {
  if (auto* payload = static_cast<OwnedPayload*>(opaque)) {
    payload->references.fetch_add(1, std::memory_order_relaxed);
  }
}

void release_payload(void* opaque) {
  auto* payload = static_cast<OwnedPayload*>(opaque);
  if (!payload) return;
  if (payload->references.fetch_sub(1, std::memory_order_acq_rel) == 1) {
    delete payload;
  }
}

constexpr nodrix_port_v2 kInput{
    sizeof(nodrix_port_v2),
    "input",
    "core.bytes",
    "cpu",
    0,
    0,
};
constexpr nodrix_port_v2 kOutput{
    sizeof(nodrix_port_v2),
    "output",
    "core.bytes",
    "cpu",
    0,
    0,
};
constexpr nodrix_port_v2 kOptionalInput{
    sizeof(nodrix_port_v2),
    "side",
    "core.bytes",
    "cpu",
    NODRIX_PORT_OPTIONAL,
    0,
};

size_t input_count(const void* opaque) {
  const auto* instance = static_cast<const Instance*>(opaque);
  if (!instance || instance->role == Role::Source) return 0;
  return instance->role == Role::OptionalSink ? 2 : 1;
}

size_t output_count(const void* opaque) {
  const auto* instance = static_cast<const Instance*>(opaque);
  return instance &&
                 (instance->role == Role::Source ||
                  instance->role == Role::Bridge)
             ? 1
             : 0;
}

nodrix_status_v2 input_port(
    const void* opaque,
    size_t index,
    nodrix_port_v2* output) {
  if (!opaque || !output || index >= input_count(opaque)) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  *output = index == 0 ? kInput : kOptionalInput;
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 output_port(
    const void* opaque,
    size_t index,
    nodrix_port_v2* output) {
  if (!opaque || !output || index != 0 ||
      output_count(opaque) != 1) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  *output = kOutput;
  return NODRIX_STATUS_OK;
}

uint8_t is_source(const void* opaque) {
  const auto* instance = static_cast<const Instance*>(opaque);
  return instance && instance->role == Role::Source ? 1 : 0;
}

nodrix_status_v2 open_node(
    void* opaque,
    const nodrix_node_context_v2* context) {
  if (!opaque || !context ||
      context->struct_size < NODRIX_NODE_CONTEXT_V2_REQUIRED_SIZE) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  auto* instance = static_cast<Instance*>(opaque);
  instance->control_context = context->control_context;
  instance->stop_requested = context->stop_requested;
  return NODRIX_STATUS_OK;
}

bool equals(
    const nodrix_string_view_v2& actual,
    std::string_view expected) {
  return actual.struct_size >= NODRIX_STRING_VIEW_V2_REQUIRED_SIZE &&
         actual.size == expected.size() &&
         (actual.size == 0 ||
          (actual.data &&
           std::memcmp(
               actual.data,
               expected.data(),
               expected.size()) == 0));
}

nodrix_status_v2 validate_message(
    Instance& instance,
    const nodrix_message_v2& message) {
  const bool integer_trace =
      (message.correlation.flags &
       NODRIX_CORRELATION_TRACE_ID_INTEGER) != 0;
  bool decimal_trace =
      message.correlation.trace_id.data &&
      message.correlation.trace_id.size > 0;
  if (message.correlation.trace_id.data) {
    for (std::size_t index = 0;
         index < message.correlation.trace_id.size;
         ++index) {
      const char ch = message.correlation.trace_id.data[index];
      decimal_trace =
          decimal_trace && ch >= '0' && ch <= '9';
    }
  }
  const bool valid_trace =
      integer_trace
          ? decimal_trace
          : equals(message.correlation.trace_id, kTrace);
  if (message.struct_size < NODRIX_MESSAGE_V2_REQUIRED_SIZE ||
      message.correlation.struct_size <
          NODRIX_CORRELATION_V2_REQUIRED_SIZE ||
      message.payload.struct_size <
          NODRIX_BUFFER_V2_REQUIRED_SIZE ||
      message.payload.memory.struct_size <
          NODRIX_MEMORY_HANDLE_V2_REQUIRED_SIZE ||
      !message.present || message.end_of_stream ||
      !equals(message.correlation.pipeline_id, kPipeline) ||
      !equals(message.correlation.run_id, kRun) ||
      !equals(message.correlation.source_id, kSource) ||
      !equals(message.correlation.stream_id, kStream) ||
      !valid_trace ||
      !equals(message.correlation.span_id, kSpan) ||
      message.source_timestamp_ns !=
          static_cast<std::int64_t>(1000 + message.sequence * 100) ||
      message.payload.size != 64 || !message.payload.data ||
      message.payload.data[0] !=
          static_cast<std::uint8_t>(message.sequence & 0xFFU) ||
      message.payload.memory.domain != NODRIX_MEMORY_HOST) {
    instance.error =
        "correlation, timestamp, or zero-copy payload changed";
    return NODRIX_STATUS_RUNTIME_ERROR;
  }
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 process(
    void* opaque,
    const nodrix_message_v2* inputs,
    size_t count,
    nodrix_emit_v2 emit,
    void* emitter_context) {
  if (!opaque) return NODRIX_STATUS_INVALID_ARGUMENT;
  auto& instance = *static_cast<Instance*>(opaque);
  try {
    if (instance.role == Role::Error) {
      instance.error = "intentional conformance plugin failure";
      return NODRIX_STATUS_RUNTIME_ERROR;
    }
    if (instance.role == Role::Source) {
      if (inputs || count != 0 || !emit) {
        return NODRIX_STATUS_INVALID_ARGUMENT;
      }
      for (std::uint64_t sequence = 0;
           sequence < instance.count;
           ++sequence) {
        if (instance.stop_requested &&
            instance.stop_requested(instance.control_context)) {
          break;
        }
        auto* payload = new OwnedPayload(
            static_cast<std::uint8_t>(sequence & 0xFFU));
        nodrix_message_v2 message{};
        message.struct_size = sizeof(message);
        message.type_id = 0x8d91246ac121e4bfULL;
        message.sequence = sequence;
        message.source_timestamp_ns =
            static_cast<std::int64_t>(1000 + sequence * 100);
        message.runtime_timestamp_ns =
            static_cast<std::int64_t>(2000 + sequence * 100);
        message.correlation = {
            sizeof(nodrix_correlation_v2),
            0,
            view(kPipeline),
            view(kRun),
            view(kSource),
            view(kStream),
            view(kTrace),
            view(kSpan),
        };
        message.present = 1;
        message.payload = {
            sizeof(nodrix_buffer_v2),
            payload->bytes.data(),
            payload->bytes.size(),
            payload,
            retain_payload,
            release_payload,
            {
                sizeof(nodrix_memory_handle_v2),
                NODRIX_MEMORY_HOST,
                0,
                0,
                0,
                payload->bytes.size(),
                NODRIX_MEMORY_FLAG_HOST_VISIBLE |
                    NODRIX_MEMORY_FLAG_READ_ONLY,
                payload,
                retain_payload,
                release_payload,
            },
        };
        emit(emitter_context, 0, &message);
        release_payload(payload);
      }
      return NODRIX_STATUS_OK;
    }
    const std::size_t expected_inputs =
        instance.role == Role::OptionalSink ? 2 : 1;
    if (!inputs || count != expected_inputs) {
      return NODRIX_STATUS_INVALID_ARGUMENT;
    }
    const nodrix_status_v2 valid =
        validate_message(instance, inputs[0]);
    if (valid != NODRIX_STATUS_OK) return valid;
    if (instance.role == Role::OptionalSink &&
        inputs[1].present) {
      const nodrix_status_v2 side_valid =
          validate_message(instance, inputs[1]);
      if (side_valid != NODRIX_STATUS_OK) return side_valid;
    }
    ++instance.received;
    if (instance.role == Role::Bridge) {
      if (!emit) return NODRIX_STATUS_INVALID_ARGUMENT;
      emit(emitter_context, 0, &inputs[0]);
    }
    return NODRIX_STATUS_OK;
  } catch (const std::exception& error) {
    instance.error = error.what();
    return NODRIX_STATUS_RUNTIME_ERROR;
  } catch (...) {
    instance.error = "unknown conformance plugin exception";
    return NODRIX_STATUS_RUNTIME_ERROR;
  }
}

nodrix_status_v2 flush(void*, nodrix_emit_v2, void*) {
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 close_node(void* opaque) {
  if (!opaque) return NODRIX_STATUS_INVALID_ARGUMENT;
  auto& instance = *static_cast<Instance*>(opaque);
  if ((instance.role == Role::Sink ||
       instance.role == Role::OptionalSink) &&
      instance.count != 0 &&
      instance.received != instance.count) {
    instance.error = "sink did not receive the expected message count";
    return NODRIX_STATUS_RUNTIME_ERROR;
  }
  if (instance.role == Role::Source &&
      OwnedPayload::live.load(std::memory_order_acquire) != 0) {
    instance.error = "plugin-owned buffers leaked";
    return NODRIX_STATUS_RUNTIME_ERROR;
  }
  return NODRIX_STATUS_OK;
}

const char* last_error(const void* opaque) {
  if (!opaque) return "plugin instance is null";
  return static_cast<const Instance*>(opaque)->error.c_str();
}

void destroy(void* opaque) {
  delete static_cast<Instance*>(opaque);
}

}  // namespace

extern "C" NODRIX_C_EXPORT uint32_t
nodrix_plugin_abi_version_v2(void) {
  return NODRIX_C_ABI_VERSION;
}

extern "C" NODRIX_C_EXPORT uint64_t
nodrix_plugin_features_v2(void) {
  return NODRIX_C_FEATURE_TYPED_PORTS |
         NODRIX_C_FEATURE_MEMORY_DOMAINS |
         NODRIX_C_FEATURE_ZERO_COPY_BUFFERS |
         NODRIX_C_FEATURE_CORRELATION |
         NODRIX_C_FEATURE_DEVICE_HANDLES;
}

extern "C" NODRIX_C_EXPORT nodrix_status_v2
nodrix_plugin_create_v2(
    uint32_t host_abi_version,
    const char* node_type,
    const char* parameters_json,
    nodrix_node_api_v2* output) {
  if (host_abi_version != NODRIX_C_ABI_VERSION) {
    return NODRIX_STATUS_ABI_MISMATCH;
  }
  if (!node_type || !output ||
      output->struct_size < NODRIX_NODE_API_V2_REQUIRED_SIZE) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  try {
    Role role;
    const std::string_view type(node_type);
    if (type == "conformance.source") {
      role = Role::Source;
    } else if (type == "conformance.bridge") {
      role = Role::Bridge;
    } else if (type == "conformance.sink") {
      role = Role::Sink;
    } else if (type == "conformance.optional_sink") {
      role = Role::OptionalSink;
    } else if (type == "conformance.error") {
      role = Role::Error;
    } else {
      return NODRIX_STATUS_UNSUPPORTED;
    }
    auto* instance = new Instance();
    instance->role = role;
    instance->count = json_u64(
        parameters_json ? parameters_json : "{}",
        "count",
        32);
    *output = {
        sizeof(nodrix_node_api_v2),
        NODRIX_C_ABI_VERSION,
        nodrix_plugin_features_v2(),
        instance,
        input_count,
        output_count,
        input_port,
        output_port,
        is_source,
        open_node,
        process,
        flush,
        close_node,
        last_error,
        destroy,
    };
    return NODRIX_STATUS_OK;
  } catch (...) {
    return NODRIX_STATUS_RUNTIME_ERROR;
  }
}
