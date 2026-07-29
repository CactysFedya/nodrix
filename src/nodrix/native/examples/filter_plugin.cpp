#include <cstdint>
#include <memory>
#include <string_view>
#include <vector>

#include "nodrix/plugin.hpp"

namespace {

class EveryNthFilter final : public nodrix::Node {
 public:
  explicit EveryNthFilter(std::uint64_t every) : every_(every == 0 ? 1 : every) {}

  const std::vector<nodrix::PortSpec>& input_ports() const noexcept override { return inputs_; }
  const std::vector<nodrix::PortSpec>& output_ports() const noexcept override { return outputs_; }

  void process(std::span<const nodrix::Message> inputs, nodrix::Emitter& emitter) override {
    if (inputs.front().sequence % every_ == 0) emitter.emit(0, inputs.front());
  }

 private:
  std::uint64_t every_;
  const std::vector<nodrix::PortSpec> inputs_{{"input", "core.any"}};
  const std::vector<nodrix::PortSpec> outputs_{{"output", "core.any"}};
};


class FramePassThrough final : public nodrix::Node {
 public:
  const std::vector<nodrix::PortSpec>& input_ports() const noexcept override { return inputs_; }
  const std::vector<nodrix::PortSpec>& output_ports() const noexcept override { return outputs_; }
  void process(std::span<const nodrix::Message> inputs, nodrix::Emitter& emitter) override {
    if (!inputs.empty()) emitter.emit(0, inputs.front());
  }
 private:
  const std::vector<nodrix::PortSpec> inputs_{{"frame", "vision.frame"}};
  const std::vector<nodrix::PortSpec> outputs_{{"frame", "vision.frame"}};
};

std::uint64_t parse_every(std::string_view json) {
  const auto key = json.find("\"every\"");
  if (key == std::string_view::npos) return 2;
  const auto colon = json.find(':', key);
  if (colon == std::string_view::npos) return 2;
  std::uint64_t result = 0;
  for (std::size_t i = colon + 1; i < json.size(); ++i) {
    const char ch = json[i];
    if (ch >= '0' && ch <= '9') result = result * 10 + static_cast<unsigned>(ch - '0');
    else if (result > 0) break;
  }
  return result == 0 ? 2 : result;
}

}  // namespace

NODRIX_DECLARE_PLUGIN(
  const std::string_view type(node_type ? node_type : "");
  if (type == "demo.every_nth") {
    return new EveryNthFilter(parse_every(parameters_json ? parameters_json : "{}"));
  }
  if (type == "demo.frame_passthrough") {
    return new FramePassThrough();
  }
  return nullptr;
)
