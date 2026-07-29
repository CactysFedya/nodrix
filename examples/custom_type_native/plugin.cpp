#include <cstring>
#include <new>
#include <string>
#include <vector>

#include "nodrix/c_api.h"
#include "generated/demo_telemetry.hpp"

namespace {

struct IncrementTemperature final {
  std::string error;
};

constexpr nodrix_port_v2 kInput{
    sizeof(nodrix_port_v2), "input", "demo.Telemetry", "cpu"};
constexpr nodrix_port_v2 kOutput{
    sizeof(nodrix_port_v2), "output", "demo.Telemetry", "cpu"};

size_t one(const void*) { return 1; }

nodrix_status_v2 input_port(const void*, size_t index, nodrix_port_v2* output) {
  if (!output || index != 0) return NODRIX_STATUS_INVALID_ARGUMENT;
  *output = kInput;
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 output_port(const void*, size_t index, nodrix_port_v2* output) {
  if (!output || index != 0) return NODRIX_STATUS_INVALID_ARGUMENT;
  *output = kOutput;
  return NODRIX_STATUS_OK;
}

uint8_t not_source(const void*) { return 0; }
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
  if (inputs[0].payload.size != sizeof(nodrix::types::Telemetry)) {
    static_cast<IncrementTemperature*>(opaque)->error =
        "unexpected Telemetry payload size";
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  std::vector<std::uint8_t> bytes(inputs[0].payload.size);
  std::memcpy(bytes.data(), inputs[0].payload.data, bytes.size());
  auto* value = reinterpret_cast<nodrix::types::Telemetry*>(bytes.data());
  value->temperature += 1.0F;
  nodrix_message_v2 output = inputs[0];
  output.payload = {
      sizeof(nodrix_buffer_v2),
      bytes.data(),
      bytes.size(),
      nullptr,
      nullptr,
      nullptr,
  };
  /* No owner callbacks: the host copies this short custom value in emit(). */
  emit(emitter_context, 0, &output);
  return NODRIX_STATUS_OK;
}

nodrix_status_v2 flush(void*, nodrix_emit_v2, void*) {
  return NODRIX_STATUS_OK;
}
nodrix_status_v2 close_node(void*) { return NODRIX_STATUS_OK; }
const char* last_error(const void* opaque) {
  return opaque ? static_cast<const IncrementTemperature*>(opaque)->error.c_str()
                : "null plugin instance";
}
void destroy(void* opaque) {
  delete static_cast<IncrementTemperature*>(opaque);
}

}  // namespace

extern "C" NODRIX_C_EXPORT uint32_t nodrix_plugin_abi_version_v2(void) {
  return NODRIX_C_ABI_VERSION;
}

extern "C" NODRIX_C_EXPORT uint64_t nodrix_plugin_features_v2(void) {
  return NODRIX_C_FEATURE_TYPED_PORTS |
         NODRIX_C_FEATURE_MEMORY_DOMAINS;
}

extern "C" NODRIX_C_EXPORT nodrix_status_v2 nodrix_plugin_create_v2(
    uint32_t host_abi_version,
    const char* node_type,
    const char*,
    nodrix_node_api_v2* output) {
  if (host_abi_version != NODRIX_C_ABI_VERSION) {
    return NODRIX_STATUS_ABI_MISMATCH;
  }
  if (!node_type || std::strcmp(node_type, "demo.increment_temperature") != 0) {
    return NODRIX_STATUS_UNSUPPORTED;
  }
  if (!output || output->struct_size < sizeof(nodrix_node_api_v2)) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  auto* instance = new (std::nothrow) IncrementTemperature();
  if (!instance) return NODRIX_STATUS_RUNTIME_ERROR;
  *output = {
      sizeof(nodrix_node_api_v2),
      NODRIX_C_ABI_VERSION,
      nodrix_plugin_features_v2(),
      instance,
      one,
      one,
      input_port,
      output_port,
      not_source,
      open_node,
      process,
      flush,
      close_node,
      last_error,
      destroy,
  };
  return NODRIX_STATUS_OK;
}
