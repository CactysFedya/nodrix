#pragma once

#include <memory>
#include <string_view>

#include "nodrix/node.hpp"

namespace nodrix {

std::unique_ptr<Node> create_builtin_node(std::string_view uses, std::string_view parameters_json);

}  // namespace nodrix
