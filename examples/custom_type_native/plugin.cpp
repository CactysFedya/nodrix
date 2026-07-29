#include <cstring>
#include <span>
#include <string_view>
#include <vector>

#include "nodrix/plugin.hpp"
#include "generated/demo_telemetry.hpp"

class IncrementTemperature final : public nodrix::Node {
 public:
  const std::vector<nodrix::PortSpec>& input_ports() const noexcept override { return inputs_; }
  const std::vector<nodrix::PortSpec>& output_ports() const noexcept override { return outputs_; }

  void process(std::span<const nodrix::Message> inputs, nodrix::Emitter& emitter) override {
    const auto& input = inputs.front();
    if (input.payload.size() != sizeof(nodrix::types::Telemetry)) return;
    auto output = input;
    output.payload = nodrix::Buffer::allocate(sizeof(nodrix::types::Telemetry));
    std::memcpy(output.payload.data(), input.payload.data(), input.payload.size());
    auto* value = reinterpret_cast<nodrix::types::Telemetry*>(output.payload.data());
    value->temperature += 1.0f;
    emitter.emit(0, std::move(output));
  }

 private:
  const std::vector<nodrix::PortSpec> inputs_{{"input", "demo.Telemetry"}};
  const std::vector<nodrix::PortSpec> outputs_{{"output", "demo.Telemetry"}};
};

NODRIX_DECLARE_PLUGIN(
  if (std::string_view(node_type ? node_type : "") == "demo.increment_temperature") {
    return new IncrementTemperature();
  }
  return nullptr;
)
