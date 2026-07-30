#pragma once

/*
 * Optional C++20 convenience layer for Plugin C ABI 2.0.
 *
 * These C++ classes live entirely inside the plugin. export_node() exposes
 * only the C function table from c_api.h, so no C++ object crosses the DSO
 * boundary.
 */

#include <exception>
#include <cstdint>
#include <span>
#include <string>
#include <utility>

#include "nodrix/c_api.h"

namespace nodrix::c_api {

class Emitter final {
 public:
  Emitter(nodrix_emit_v2 emit, void* context) noexcept
      : emit_(emit), context_(context) {}

  void emit(std::uint32_t output_port, const nodrix_message_v2& message) const {
    if (emit_) emit_(context_, output_port, &message);
  }

 private:
  nodrix_emit_v2 emit_;
  void* context_;
};

class Node {
 public:
  virtual ~Node() = default;
  virtual std::span<const nodrix_port_v2> input_ports() const noexcept = 0;
  virtual std::span<const nodrix_port_v2> output_ports() const noexcept = 0;
  virtual bool is_source() const noexcept { return false; }
  virtual nodrix_status_v2 open(const nodrix_node_context_v2&) {
    return NODRIX_STATUS_OK;
  }
  virtual nodrix_status_v2 process(
      std::span<const nodrix_message_v2> inputs, const Emitter& emitter) = 0;
  virtual nodrix_status_v2 flush(const Emitter&) {
    return NODRIX_STATUS_OK;
  }
  virtual nodrix_status_v2 close() { return NODRIX_STATUS_OK; }

  const char* last_error() const noexcept { return error_.c_str(); }
  void set_error(std::string value) noexcept { error_ = std::move(value); }

 private:
  std::string error_;
};

namespace detail {

template <typename Function>
nodrix_status_v2 guard(Node* node, Function&& function) noexcept {
  if (!node) return NODRIX_STATUS_INVALID_ARGUMENT;
  try {
    return function();
  } catch (const std::exception& exc) {
    try {
      node->set_error(exc.what());
    } catch (...) {
    }
  } catch (...) {
    try {
      node->set_error("unknown C++ plugin exception");
    } catch (...) {
    }
  }
  return NODRIX_STATUS_RUNTIME_ERROR;
}

inline size_t input_count(const void* opaque) {
  return opaque ? static_cast<const Node*>(opaque)->input_ports().size() : 0;
}

inline size_t output_count(const void* opaque) {
  return opaque ? static_cast<const Node*>(opaque)->output_ports().size() : 0;
}

inline nodrix_status_v2 input_port(
    const void* opaque, size_t index, nodrix_port_v2* output) {
  if (!opaque || !output) return NODRIX_STATUS_INVALID_ARGUMENT;
  if (output->struct_size < NODRIX_PORT_V2_REQUIRED_SIZE) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  const auto ports = static_cast<const Node*>(opaque)->input_ports();
  if (index >= ports.size()) return NODRIX_STATUS_INVALID_ARGUMENT;
  *output = ports[index];
  return NODRIX_STATUS_OK;
}

inline nodrix_status_v2 output_port(
    const void* opaque, size_t index, nodrix_port_v2* output) {
  if (!opaque || !output) return NODRIX_STATUS_INVALID_ARGUMENT;
  if (output->struct_size < NODRIX_PORT_V2_REQUIRED_SIZE) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  const auto ports = static_cast<const Node*>(opaque)->output_ports();
  if (index >= ports.size()) return NODRIX_STATUS_INVALID_ARGUMENT;
  *output = ports[index];
  return NODRIX_STATUS_OK;
}

inline uint8_t is_source(const void* opaque) {
  return opaque && static_cast<const Node*>(opaque)->is_source() ? 1 : 0;
}

inline nodrix_status_v2 open_node(
    void* opaque, const nodrix_node_context_v2* context) {
  auto* node = static_cast<Node*>(opaque);
  if (!context ||
      context->struct_size < NODRIX_NODE_CONTEXT_V2_REQUIRED_SIZE) {
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  return guard(node, [&] { return node->open(*context); });
}

inline nodrix_status_v2 process(
    void* opaque,
    const nodrix_message_v2* inputs,
    size_t count,
    nodrix_emit_v2 emit,
    void* emitter_context) {
  auto* node = static_cast<Node*>(opaque);
  if (!inputs && count > 0) return NODRIX_STATUS_INVALID_ARGUMENT;
  for (size_t index = 0; index < count; ++index) {
    if (inputs[index].struct_size <
            NODRIX_MESSAGE_V2_REQUIRED_SIZE ||
        inputs[index].correlation.struct_size <
            NODRIX_CORRELATION_V2_REQUIRED_SIZE ||
        inputs[index].payload.struct_size <
            NODRIX_BUFFER_V2_REQUIRED_SIZE ||
        inputs[index].payload.memory.struct_size <
            NODRIX_MEMORY_HANDLE_V2_REQUIRED_SIZE) {
      return NODRIX_STATUS_INVALID_ARGUMENT;
    }
  }
  return guard(node, [&] {
    return node->process(
        std::span<const nodrix_message_v2>(inputs, count),
        Emitter(emit, emitter_context));
  });
}

inline nodrix_status_v2 flush(
    void* opaque, nodrix_emit_v2 emit, void* emitter_context) {
  auto* node = static_cast<Node*>(opaque);
  return guard(
      node, [&] { return node->flush(Emitter(emit, emitter_context)); });
}

inline nodrix_status_v2 close_node(void* opaque) {
  auto* node = static_cast<Node*>(opaque);
  return guard(node, [&] { return node->close(); });
}

inline const char* last_error(const void* opaque) {
  return opaque ? static_cast<const Node*>(opaque)->last_error()
                : "null plugin instance";
}

inline void destroy(void* opaque) {
  delete static_cast<Node*>(opaque);
}

}  // namespace detail

inline nodrix_status_v2 export_node(
    Node* node,
    nodrix_node_api_v2* output,
    std::uint64_t features = NODRIX_C_FEATURE_TYPED_PORTS |
                             NODRIX_C_FEATURE_MEMORY_DOMAINS |
                             NODRIX_C_FEATURE_ZERO_COPY_BUFFERS |
                             NODRIX_C_FEATURE_CORRELATION |
                             NODRIX_C_FEATURE_DEVICE_HANDLES) noexcept {
  if (!node || !output ||
      output->struct_size < NODRIX_NODE_API_V2_REQUIRED_SIZE) {
    delete node;
    return NODRIX_STATUS_INVALID_ARGUMENT;
  }
  *output = {
      sizeof(nodrix_node_api_v2),
      NODRIX_C_ABI_VERSION,
      features,
      node,
      detail::input_count,
      detail::output_count,
      detail::input_port,
      detail::output_port,
      detail::is_source,
      detail::open_node,
      detail::process,
      detail::flush,
      detail::close_node,
      detail::last_error,
      detail::destroy,
  };
  return NODRIX_STATUS_OK;
}

}  // namespace nodrix::c_api
