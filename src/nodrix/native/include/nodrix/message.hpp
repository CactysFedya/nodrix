#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

#include "nodrix/buffer.hpp"
#include "nodrix/device_memory.hpp"

namespace nodrix {

constexpr std::uint64_t fnv1a_64(std::string_view value) noexcept {
  std::uint64_t hash = 1469598103934665603ULL;
  for (const unsigned char ch : value) {
    hash ^= ch;
    hash *= 1099511628211ULL;
  }
  return hash;
}

inline std::int64_t steady_time_ns() noexcept {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

struct Message final {
  std::uint64_t type_id{0};
  std::uint64_t sequence{0};
  std::int64_t source_timestamp_ns{0};
  std::int64_t runtime_timestamp_ns{0};
  std::string pipeline_id;
  std::string run_id;
  std::string source_id;
  std::string stream_id;
  std::string trace_id;
  std::string span_id;
  bool trace_id_integer{false};
  Buffer payload{};
  std::optional<DeviceBufferDescriptor> device_memory;
  bool present{true};
  bool end_of_stream{false};

  static Message eos() noexcept {
    Message message;
    message.end_of_stream = true;
    return message;
  }
};

}  // namespace nodrix
