#include <cstdint>

#include "nodrix/c_api.h"

extern "C" NODRIX_C_EXPORT uint32_t
nodrix_plugin_abi_version_v2(void) {
  return NODRIX_C_ABI_VERSION;
}

extern "C" NODRIX_C_EXPORT uint64_t
nodrix_plugin_features_v2(void) {
  return NODRIX_C_FEATURE_TYPED_PORTS |
         NODRIX_C_FEATURE_MEMORY_DOMAINS |
         NODRIX_C_FEATURE_CORRELATION |
         NODRIX_C_FEATURE_DEVICE_HANDLES;
}

/* nodrix_plugin_create_v2 is intentionally absent. */
