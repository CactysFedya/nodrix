#pragma once

#include <chrono>
#include <cstdint>
#include <string_view>

#include "nodrix/buffer.hpp"

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
  std::uint64_t trace_id{0};
  Buffer payload{};
  bool end_of_stream{false};

  static Message eos() noexcept {
    Message message;
    message.end_of_stream = true;
    return message;
  }
};

}  // namespace nodrix
