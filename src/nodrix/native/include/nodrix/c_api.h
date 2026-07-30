#ifndef NODRIX_C_API_H
#define NODRIX_C_API_H

/*
 * Nodrix Plugin C ABI 2.0
 *
 * Only fixed-width integers, sized views, function pointers and opaque
 * instance/owner handles cross the shared-library boundary. No C++ standard
 * library object, exception, RTTI object or allocator ownership crosses it.
 *
 * Every structure begins with struct_size. Hosts and plugins must validate the
 * required prefix, ignore a larger trailing area, and zero-initialize output
 * structures before a call. This permits fields to be appended without
 * changing the ABI version.
 *
 * String views are borrowed. Input strings remain valid only until process()
 * returns. Strings in an emitted message need remain valid only until the
 * synchronous emit callback returns. A receiver that needs a longer lifetime
 * must copy them.
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
#define NODRIX_C_FEATURE_CORRELATION ((uint64_t)1u << 3u)
#define NODRIX_C_FEATURE_DEVICE_HANDLES ((uint64_t)1u << 4u)

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

typedef struct nodrix_string_view_v2 {
  uint32_t struct_size;
  const char* data;
  size_t size;
} nodrix_string_view_v2;

typedef struct nodrix_correlation_v2 {
  uint32_t struct_size;
  uint32_t flags;
  nodrix_string_view_v2 pipeline_id;
  nodrix_string_view_v2 run_id;
  nodrix_string_view_v2 source_id;
  nodrix_string_view_v2 stream_id;
  nodrix_string_view_v2 trace_id;
  nodrix_string_view_v2 span_id;
} nodrix_correlation_v2;

#define NODRIX_CORRELATION_TRACE_ID_INTEGER ((uint32_t)1u << 0u)

typedef enum nodrix_memory_domain_v2 {
  NODRIX_MEMORY_HOST = 0,
  NODRIX_MEMORY_PINNED_HOST = 1,
  NODRIX_MEMORY_SHARED = 2,
  NODRIX_MEMORY_DMABUF = 3,
  NODRIX_MEMORY_CUDA = 4,
  NODRIX_MEMORY_ROCM = 5,
  NODRIX_MEMORY_VULKAN = 6,
  NODRIX_MEMORY_OPENCL = 7,
  NODRIX_MEMORY_METAL = 8,
  NODRIX_MEMORY_NPU = 9,
  NODRIX_MEMORY_DLPACK = 10,
  NODRIX_MEMORY_EXTERNAL = 255
} nodrix_memory_domain_v2;

#define NODRIX_MEMORY_FLAG_HOST_VISIBLE ((uint64_t)1u << 0u)
#define NODRIX_MEMORY_FLAG_READ_ONLY ((uint64_t)1u << 1u)
#define NODRIX_MEMORY_FLAG_INTERPROCESS ((uint64_t)1u << 2u)

/*
 * A device handle is opaque to Nodrix unless the domain contract defines its
 * interpretation. owner/retain/release control the lifetime of the underlying
 * allocation or imported handle. A consumer that stores the handle after
 * process() returns must call retain(owner), and later release(owner).
 */
typedef struct nodrix_memory_handle_v2 {
  uint32_t struct_size;
  uint32_t domain;
  uint64_t device_id;
  uint64_t handle;
  uint64_t offset;
  uint64_t size;
  uint64_t flags;
  void* owner;
  nodrix_buffer_retain_v2 retain;
  nodrix_buffer_release_v2 release;
} nodrix_memory_handle_v2;

typedef struct nodrix_buffer_v2 {
  uint32_t struct_size;
  /*
   * data is non-null only when the allocation is host-visible. Device-only
   * buffers use memory.handle and leave data null. size is the logical payload
   * size in both cases.
   */
  const uint8_t* data;
  size_t size;
  void* owner;
  nodrix_buffer_retain_v2 retain;
  nodrix_buffer_release_v2 release;
  nodrix_memory_handle_v2 memory;
} nodrix_buffer_v2;

typedef struct nodrix_message_v2 {
  uint32_t struct_size;
  uint64_t type_id;
  uint64_t sequence;
  int64_t source_timestamp_ns;
  int64_t runtime_timestamp_ns;
  nodrix_correlation_v2 correlation;
  uint8_t end_of_stream;
  uint8_t present;
  uint8_t reserved[6];
  nodrix_buffer_v2 payload;
} nodrix_message_v2;

typedef struct nodrix_port_v2 {
  uint32_t struct_size;
  const char* name;
  const char* type;
  const char* memory;
  uint32_t flags;
  uint32_t reserved;
} nodrix_port_v2;

typedef uint8_t (*nodrix_stop_requested_v2)(void* control_context);

typedef struct nodrix_node_context_v2 {
  uint32_t struct_size;
  const char* name;
  const char* parameters_json;
  const char* run_dir;
  const char* device;
  void* control_context;
  nodrix_stop_requested_v2 stop_requested;
} nodrix_node_context_v2;

#define NODRIX_PORT_OPTIONAL ((uint32_t)1u << 0u)

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

#define NODRIX_REQUIRED_SIZE_V2(type, member) \
  (offsetof(type, member) + sizeof(((type*)0)->member))
#define NODRIX_STRING_VIEW_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_string_view_v2, size)
#define NODRIX_CORRELATION_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_correlation_v2, span_id)
#define NODRIX_MEMORY_HANDLE_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_memory_handle_v2, release)
#define NODRIX_BUFFER_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_buffer_v2, memory)
#define NODRIX_MESSAGE_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_message_v2, payload)
#define NODRIX_PORT_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_port_v2, reserved)
#define NODRIX_NODE_CONTEXT_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_node_context_v2, stop_requested)
#define NODRIX_NODE_API_V2_REQUIRED_SIZE \
  NODRIX_REQUIRED_SIZE_V2(nodrix_node_api_v2, destroy)

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
