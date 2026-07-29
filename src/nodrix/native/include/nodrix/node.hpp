#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "nodrix/message.hpp"

namespace nodrix {

struct PortSpec final {
  std::string name;
  std::string type;
  std::string memory{"any"};
};

struct NodeContext final {
  std::string name;
  std::string parameters_json;
  std::string run_dir;
  std::string device{"auto"};
};

class Emitter {
 public:
  virtual ~Emitter() = default;
  virtual void emit(std::size_t output_port, Message message) = 0;
};

class Node {
 public:
  virtual ~Node() = default;

  virtual const std::vector<PortSpec>& input_ports() const noexcept = 0;
  virtual const std::vector<PortSpec>& output_ports() const noexcept = 0;
  virtual bool is_source() const noexcept { return false; }

  virtual void open(const NodeContext&) {}
  virtual void run_source(Emitter&) {}
  virtual void process(std::span<const Message>, Emitter&) = 0;
  virtual void flush(Emitter&) {}
  virtual void close() noexcept {}
};

}  // namespace nodrix
