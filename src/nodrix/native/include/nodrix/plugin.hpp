#pragma once

#include "nodrix/node.hpp"

#if defined(_WIN32)
#define NODRIX_PLUGIN_EXPORT extern "C" __declspec(dllexport)
#else
#define NODRIX_PLUGIN_EXPORT extern "C" __attribute__((visibility("default")))
#endif

#define NODRIX_DECLARE_PLUGIN(create_body)                                      \
  NODRIX_PLUGIN_EXPORT std::uint32_t nodrix_plugin_abi_version() {           \
    return ::nodrix::kPluginAbiVersion;                                           \
  }                                                                                  \
  NODRIX_PLUGIN_EXPORT std::uint64_t nodrix_plugin_features() {                    \
    return ::nodrix::kPluginFeatures;                                             \
  }                                                                                  \
  NODRIX_PLUGIN_EXPORT ::nodrix::Node* nodrix_create_node(              \
      const char* node_type, const char* parameters_json) {                         \
    create_body                                                                      \
  }                                                                                  \
  NODRIX_PLUGIN_EXPORT void nodrix_destroy_node(::nodrix::Node* node) { \
    delete node;                                                                      \
  }
