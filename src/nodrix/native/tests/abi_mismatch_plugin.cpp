#include <cstdint>

#include "nodrix/c_api.h"

extern "C" NODRIX_C_EXPORT uint32_t
nodrix_plugin_abi_version_v2(void) {
  return 0x00010000u;
}

extern "C" NODRIX_C_EXPORT uint64_t
nodrix_plugin_features_v2(void) {
  return 0;
}

extern "C" NODRIX_C_EXPORT nodrix_status_v2
nodrix_plugin_create_v2(
    uint32_t,
    const char*,
    const char*,
    nodrix_node_api_v2*) {
  return NODRIX_STATUS_ABI_MISMATCH;
}
