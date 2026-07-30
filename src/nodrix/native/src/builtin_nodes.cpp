#include "nodrix/builtin_nodes.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace nodrix {
namespace {

std::uint64_t json_u64(std::string_view json, std::string_view key, std::uint64_t fallback) {
  const std::string needle = "\"" + std::string(key) + "\"";
  std::size_t pos = json.find(needle);
  if (pos == std::string_view::npos) return fallback;
  pos = json.find(':', pos + needle.size());
  if (pos == std::string_view::npos) return fallback;
  ++pos;
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
  std::uint64_t value = fallback;
  const char* begin = json.data() + pos;
  const char* end = json.data() + json.size();
  const auto result = std::from_chars(begin, end, value);
  return result.ec == std::errc{} ? value : fallback;
}

bool json_bool(std::string_view json, std::string_view key, bool fallback) {
  const std::string needle = "\"" + std::string(key) + "\"";
  std::size_t pos = json.find(needle);
  if (pos == std::string_view::npos) return fallback;
  pos = json.find(':', pos + needle.size());
  if (pos == std::string_view::npos) return fallback;
  ++pos;
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
  if (json.substr(pos, 4) == "true") return true;
  if (json.substr(pos, 5) == "false") return false;
  return fallback;
}

class SyntheticSource final : public Node {
 public:
  explicit SyntheticSource(std::string_view parameters)
      : count_(json_u64(parameters, "count", 1000)),
        payload_bytes_(json_u64(parameters, "payload_bytes", 0)),
        reuse_buffer_(json_bool(parameters, "reuse_buffer", true)) {}

  const std::vector<PortSpec>& input_ports() const noexcept override { return inputs_; }
  const std::vector<PortSpec>& output_ports() const noexcept override { return outputs_; }
  bool is_source() const noexcept override { return true; }

  void open(const NodeContext& context) override {
    stop_requested_ = context.stop_requested;
  }

  void run_source(Emitter& emitter) override {
    Buffer reusable;
    if (payload_bytes_ > 0 && reuse_buffer_) {
      reusable = Buffer::allocate(payload_bytes_);
      std::memset(reusable.data(), 0x5A, reusable.size());
    }
    for (std::uint64_t sequence = 0; sequence < count_; ++sequence) {
      if (stop_requested_ &&
          stop_requested_->load(std::memory_order_acquire)) {
        break;
      }
      Buffer payload = reusable;
      if (payload_bytes_ > 0 && !reuse_buffer_) {
        payload = Buffer::allocate(payload_bytes_);
        std::memset(payload.data(), static_cast<int>(sequence & 0xFFU), payload.size());
      }
      Message message;
      message.type_id = fnv1a_64("core.bytes");
      message.sequence = sequence;
      message.source_timestamp_ns = steady_time_ns();
      message.runtime_timestamp_ns = message.source_timestamp_ns;
      message.trace_id = std::to_string(sequence);
      message.trace_id_integer = true;
      message.payload = std::move(payload);
      emitter.emit(0, std::move(message));
    }
  }

  void process(std::span<const Message>, Emitter&) override {}

 private:
  std::uint64_t count_;
  std::uint64_t payload_bytes_;
  bool reuse_buffer_;
  const std::atomic<bool>* stop_requested_{nullptr};
  const std::vector<PortSpec> inputs_{};
  const std::vector<PortSpec> outputs_{{"output", "core.bytes"}};
};

class IdentityNode final : public Node {
 public:
  const std::vector<PortSpec>& input_ports() const noexcept override { return inputs_; }
  const std::vector<PortSpec>& output_ports() const noexcept override { return outputs_; }

  void process(std::span<const Message> inputs, Emitter& emitter) override {
    emitter.emit(0, inputs.front());
  }

 private:
  const std::vector<PortSpec> inputs_{{"input", "core.any"}};
  const std::vector<PortSpec> outputs_{{"output", "core.any"}};
};

class DelayNode final : public Node {
 public:
  explicit DelayNode(std::string_view parameters)
      : microseconds_(json_u64(parameters, "microseconds", 0)) {}

  const std::vector<PortSpec>& input_ports() const noexcept override { return inputs_; }
  const std::vector<PortSpec>& output_ports() const noexcept override { return outputs_; }

  void process(std::span<const Message> inputs, Emitter& emitter) override {
    if (microseconds_ > 0) {
      std::this_thread::sleep_for(std::chrono::microseconds(microseconds_));
    }
    emitter.emit(0, inputs.front());
  }

 private:
  std::uint64_t microseconds_;
  const std::vector<PortSpec> inputs_{{"input", "core.any"}};
  const std::vector<PortSpec> outputs_{{"output", "core.any"}};
};

class CounterSink final : public Node {
 public:
  const std::vector<PortSpec>& input_ports() const noexcept override { return inputs_; }
  const std::vector<PortSpec>& output_ports() const noexcept override { return outputs_; }

  void process(std::span<const Message> inputs, Emitter&) override {
    ++count_;
    checksum_ ^= inputs.front().sequence + inputs.front().payload.size();
  }

  void close() override {
    // The host report contains the authoritative count. The volatile checksum
    // keeps the compiler from optimizing the data path away in benchmarks.
    volatile std::uint64_t keep = checksum_;
    (void)keep;
  }

 private:
  std::uint64_t count_{0};
  std::uint64_t checksum_{0};
  const std::vector<PortSpec> inputs_{{"input", "core.any"}};
  const std::vector<PortSpec> outputs_{};
};

}  // namespace

std::unique_ptr<Node> create_builtin_node(std::string_view uses, std::string_view parameters_json) {
  if (uses == "native.synthetic_source") {
    return std::make_unique<SyntheticSource>(parameters_json);
  }
  if (uses == "native.identity") {
    return std::make_unique<IdentityNode>();
  }
  if (uses == "native.delay") {
    return std::make_unique<DelayNode>(parameters_json);
  }
  if (uses == "native.counter_sink") {
    return std::make_unique<CounterSink>();
  }
  throw std::runtime_error("Unknown native built-in node: " + std::string(uses));
}

}  // namespace nodrix
