#include <cstdlib>
#include <span>

#include "nodrix/cpp_plugin.hpp"

namespace {

void require(bool condition) {
  if (!condition) {
    std::abort();
  }
}

class Identity final : public nodrix::c_api::Node {
 public:
  std::span<const nodrix_port_v2> input_ports()
      const noexcept override {
    return inputs_;
  }

  std::span<const nodrix_port_v2> output_ports()
      const noexcept override {
    return outputs_;
  }

  nodrix_status_v2 process(
      std::span<const nodrix_message_v2> inputs,
      const nodrix::c_api::Emitter& emitter) override {
    if (inputs.size() != 1) {
      return NODRIX_STATUS_INVALID_ARGUMENT;
    }
    emitter.emit(0, inputs.front());
    return NODRIX_STATUS_OK;
  }

 private:
  const nodrix_port_v2 inputs_[1]{
      {
          sizeof(nodrix_port_v2),
          "input",
          "core.any",
          "any",
          0,
          0,
      },
  };
  const nodrix_port_v2 outputs_[1]{
      {
          sizeof(nodrix_port_v2),
          "output",
          "core.any",
          "any",
          0,
          0,
      },
  };
};

}  // namespace

int main() {
  nodrix_node_api_v2 undersized{};
  undersized.struct_size =
      NODRIX_NODE_API_V2_REQUIRED_SIZE - 1;
  require(
      nodrix::c_api::export_node(
          new Identity(), &undersized) ==
      NODRIX_STATUS_INVALID_ARGUMENT);

  nodrix_node_api_v2 api{};
  api.struct_size = sizeof(api);
  require(
      nodrix::c_api::export_node(new Identity(), &api) ==
      NODRIX_STATUS_OK);
  require(api.struct_size == sizeof(api));
  require(api.abi_version == NODRIX_C_ABI_VERSION);
  require(api.input_count(api.instance) == 1);
  require(api.output_count(api.instance) == 1);
  api.destroy(api.instance);
  return 0;
}
