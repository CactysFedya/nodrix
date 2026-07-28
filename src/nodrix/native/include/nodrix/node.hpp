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

constexpr std::uint32_t kPluginAbiVersion = 0x00010000;  // ABI 1.0
constexpr std::uint64_t kPluginFeatureTypedPorts = 1ull << 0;
constexpr std::uint64_t kPluginFeatureMemoryDomains = 1ull << 1;
constexpr std::uint64_t kPluginFeatures = kPluginFeatureTypedPorts | kPluginFeatureMemoryDomains;
using PluginAbiVersionFn = std::uint32_t (*)();
using PluginFeaturesFn = std::uint64_t (*)();
using CreateNodeFn = Node* (*)(const char* node_type, const char* parameters_json);
using DestroyNodeFn = void (*)(Node* node);

}  // namespace nodrix
