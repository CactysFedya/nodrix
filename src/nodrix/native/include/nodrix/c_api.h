#ifndef NODRIX_C_API_H
#define NODRIX_C_API_H

/*
 * Nodrix Plugin C ABI 2.0
 *
 * Only fixed-width integers, byte spans, function pointers and opaque
 * instance/owner handles cross the shared-library boundary. No C++ standard
 * library object, exception, RTTI object or allocator ownership crosses it.
 */

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define NODRIX_C_EXPORT __declspec(dllexport)
#else
#define NODRIX_C_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define NODRIX_C_ABI_VERSION ((uint32_t)0x00020000u)
#define NODRIX_C_FEATURE_TYPED_PORTS ((uint64_t)1u << 0u)
#define NODRIX_C_FEATURE_MEMORY_DOMAINS ((uint64_t)1u << 1u)
#define NODRIX_C_FEATURE_ZERO_COPY_BUFFERS ((uint64_t)1u << 2u)

typedef int32_t nodrix_status_v2;

enum {
  NODRIX_STATUS_OK = 0,
  NODRIX_STATUS_INVALID_ARGUMENT = 1,
  NODRIX_STATUS_UNSUPPORTED = 2,
  NODRIX_STATUS_RUNTIME_ERROR = 3,
  NODRIX_STATUS_ABI_MISMATCH = 4
};

typedef void (*nodrix_buffer_retain_v2)(void* owner);
typedef void (*nodrix_buffer_release_v2)(void* owner);

typedef struct nodrix_buffer_v2 {
  uint32_t struct_size;
  const uint8_t* data;
  size_t size;
  void* owner;
  nodrix_buffer_retain_v2 retain;
  nodrix_buffer_release_v2 release;
} nodrix_buffer_v2;

typedef struct nodrix_message_v2 {
  uint32_t struct_size;
  uint64_t type_id;
  uint64_t sequence;
  int64_t source_timestamp_ns;
  int64_t runtime_timestamp_ns;
  uint64_t trace_id;
  uint8_t end_of_stream;
  uint8_t reserved[7];
  nodrix_buffer_v2 payload;
} nodrix_message_v2;

typedef struct nodrix_port_v2 {
  uint32_t struct_size;
  const char* name;
  const char* type;
  const char* memory;
} nodrix_port_v2;

typedef struct nodrix_node_context_v2 {
  uint32_t struct_size;
  const char* name;
  const char* parameters_json;
  const char* run_dir;
  const char* device;
} nodrix_node_context_v2;

typedef void (*nodrix_emit_v2)(
    void* emitter_context,
    uint32_t output_port,
    const nodrix_message_v2* message);

typedef struct nodrix_node_api_v2 {
  uint32_t struct_size;
  uint32_t abi_version;
  uint64_t features;
  void* instance;

  size_t (*input_count)(const void* instance);
  size_t (*output_count)(const void* instance);
  nodrix_status_v2 (*input_port)(
      const void* instance, size_t index, nodrix_port_v2* output);
  nodrix_status_v2 (*output_port)(
      const void* instance, size_t index, nodrix_port_v2* output);
  uint8_t (*is_source)(const void* instance);

  nodrix_status_v2 (*open)(
      void* instance, const nodrix_node_context_v2* context);
  nodrix_status_v2 (*process)(
      void* instance,
      const nodrix_message_v2* inputs,
      size_t input_count,
      nodrix_emit_v2 emit,
      void* emitter_context);
  nodrix_status_v2 (*flush)(
      void* instance, nodrix_emit_v2 emit, void* emitter_context);
  nodrix_status_v2 (*close)(void* instance);

  const char* (*last_error)(const void* instance);
  void (*destroy)(void* instance);
} nodrix_node_api_v2;

typedef uint32_t (*nodrix_plugin_abi_version_v2_fn)(void);
typedef uint64_t (*nodrix_plugin_features_v2_fn)(void);
typedef nodrix_status_v2 (*nodrix_plugin_create_v2_fn)(
    uint32_t host_abi_version,
    const char* node_type,
    const char* parameters_json,
    nodrix_node_api_v2* output);

NODRIX_C_EXPORT uint32_t nodrix_plugin_abi_version_v2(void);
NODRIX_C_EXPORT uint64_t nodrix_plugin_features_v2(void);
NODRIX_C_EXPORT nodrix_status_v2 nodrix_plugin_create_v2(
    uint32_t host_abi_version,
    const char* node_type,
    const char* parameters_json,
    nodrix_node_api_v2* output);

#ifdef __cplusplus
}
#endif

#endif
