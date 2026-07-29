#include <cstdint>
#include <cstring>
#include <new>
#include <string>
#include <string_view>

#include "nodrix/c_api.h"

namespace {

struct Filter final {
  std::uint64_t every{2};
  bool frame{false};
  std::string error;
};

constexpr nodrix_port_v2 kObjectInput{
    sizeof(nodrix_port_v2), "input", "core.any", "any"};
constexpr nodrix_port_v2 kObjectOutput{
    sizeof(nodrix_port_v2), "output", "core.any", "any"};
constexpr nodrix_port_v2 kFrameInput{
    sizeof(nodrix_port_v2), "frame", "vision.frame", "any"};
constexpr nodrix_port_v2 kFrameOutput{
    sizeof(nodrix_port_v2), "frame", "vision.frame", "any"};

std::uint64_t parse_every(std::string_view json) {
  const auto key = json.find("\"every\"");
  if (key == std::string_view::npos) return 2;
  const auto colon = json.find(':', key);
  if (colon == std::string_view::npos) return 2;
  std::uint64_t result = 0;
  for (std::size_t index = colon + 1; index < json.size(); ++index) {
    const char ch = json[index];
    if (ch >= '0' && ch <= '9') {
      result = result * 10 + static_cast<unsigned>(ch - '0');
    } else if (result > 0) {
      break;
    }
  }
  return result == 0 ? 2 : result;
}

size_t input_count(const void*) { return 1; }
size_t output_count(const void*) { return 1; }

nodrix_status_v2 input_port(
    const void* opaque, size_t index, nodrix_port_v2* output) {
  if (!opaque || !output || index != 0) return NODRIX_STATUS_INVALID_ARGUMENT;
  const auto* self = static_cast<const Filter*>(opaque);
  *output = self->frame ? kFrameInput : kObjectInput;
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 output_port(
    const void* opaque, size_t index, nodrix_port_v2* output) {
  if (!opaque || !output || index != 0) return NODRIX_STATUS_INVALID_ARGUMENT;
  const auto* self = static_cast<const Filter*>(opaque);
  *output = self->frame ? kFrameOutput : kObjectOutput;
  return NODRIX_STATUS_OK;
}

uint8_t is_source(const void*) { return 0; }

nodrix_status_v2 open_node(void*, const nodrix_node_context_v2*) {
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 process(
    void* opaque,
    const nodrix_message_v2* inputs,
    size_t count,
    nodrix_emit_v2 emit,
    void* emitter_context) {
  if (!opaque || !inputs || count != 1 || !emit) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  auto* self = static_cast<Filter*>(opaque);
  if (self->frame || inputs[0].sequence % self->every == 0) {
    /* The host retains the buffer during this synchronous callback. */
    emit(emitter_context, 0, &inputs[0]);
  }
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 flush(void*, nodrix_emit_v2, void*) {
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 close_node(void*) { return NODRIX_STATUS_OK; }

const char* last_error(const void* opaque) {
  if (!opaque) return "plugin instance is null";
  return static_cast<const Filter*>(opaque)->error.c_str();
}

void destroy(void* opaque) { delete static_cast<Filter*>(opaque); }

}  // namespace

extern "C" NODRIX_C_EXPORT uint32_t nodrix_plugin_abi_version_v2(void) {
  return NODRIX_C_ABI_VERSION;
}

extern "C" NODRIX_C_EXPORT uint64_t nodrix_plugin_features_v2(void) {
  return NODRIX_C_FEATURE_TYPED_PORTS |
         NODRIX_C_FEATURE_MEMORY_DOMAINS |
         NODRIX_C_FEATURE_ZERO_COPY_BUFFERS;
}

extern "C" NODRIX_C_EXPORT nodrix_status_v2 nodrix_plugin_create_v2(
    uint32_t host_abi_version,
    const char* node_type,
    const char* parameters_json,
    nodrix_node_api_v2* output) {
  if (host_abi_version != NODRIX_C_ABI_VERSION) {
    return NODRIX_STATUS_ABI_MISMATCH;
  }
  if (!node_type || !output || output->struct_size < sizeof(nodrix_node_api_v2)) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  const std::string_view type(node_type);
  if (type != "demo.every_nth" && type != "demo.frame_passthrough") {
    return NODRIX_STATUS_UNSUPPORTED;
  }
  auto* instance = new (std::nothrow) Filter();
  if (!instance) return NODRIX_STATUS_RUNTIME_ERROR;
  instance->frame = type == "demo.frame_passthrough";
  instance->every = parse_every(parameters_json ? parameters_json : "{}");

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
}
