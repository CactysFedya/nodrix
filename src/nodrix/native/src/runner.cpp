#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#include "nodrix/builtin_nodes.hpp"
#include "nodrix/mpmc_queue.hpp"
#include "nodrix/node.hpp"
#include "nodrix/spsc_queue.hpp"

#ifndef NODRIX_NATIVE_VERSION
#define NODRIX_NATIVE_VERSION "unknown"
#endif

namespace vp = nodrix;
namespace fs = std::filesystem;

namespace {

enum class QueuePolicy { Block, Latest, DropOldest, DropNewest };

QueuePolicy parse_policy(std::string_view value) {
  if (value == "block") return QueuePolicy::Block;
  if (value == "latest") return QueuePolicy::Latest;
  if (value == "drop_oldest") return QueuePolicy::DropOldest;
  if (value == "drop_newest") return QueuePolicy::DropNewest;
  throw std::runtime_error("Unsupported queue policy: " + std::string(value));
}

std::string json_escape(std::string_view value) {
  std::ostringstream out;
  for (const unsigned char ch : value) {
    switch (ch) {
      case '\\': out << "\\\\"; break;
      case '"': out << "\\\""; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (ch < 0x20) {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch)
              << std::dec;
        } else {
          out << static_cast<char>(ch);
        }
    }
  }
  return out.str();
}

std::string hex_decode(std::string_view value) {
  if (value.size() % 2 != 0) throw std::runtime_error("Invalid hexadecimal plan field");
  std::string result;
  result.reserve(value.size() / 2);
  auto nibble = [](char ch) -> unsigned {
    if (ch >= '0' && ch <= '9') return static_cast<unsigned>(ch - '0');
    if (ch >= 'a' && ch <= 'f') return static_cast<unsigned>(ch - 'a' + 10);
    if (ch >= 'A' && ch <= 'F') return static_cast<unsigned>(ch - 'A' + 10);
    throw std::runtime_error("Invalid hexadecimal digit");
  };
  for (std::size_t i = 0; i < value.size(); i += 2) {
    result.push_back(static_cast<char>((nibble(value[i]) << 4U) | nibble(value[i + 1])));
  }
  return result;
}

std::vector<std::string> split_tabs(const std::string& line) {
  std::vector<std::string> fields;
  std::size_t begin = 0;
  for (;;) {
    const std::size_t pos = line.find('\t', begin);
    if (pos == std::string::npos) {
      fields.push_back(line.substr(begin));
      break;
    }
    fields.push_back(line.substr(begin, pos - begin));
    begin = pos + 1;
  }
  return fields;
}

struct NodeDef {
  std::string name;
  std::string uses;
  std::string parameters_json;
};

struct EdgeDef {
  std::string source_node;
  std::string source_port;
  std::string target_node;
  std::string target_port;
  std::size_t capacity{8};
  QueuePolicy policy{QueuePolicy::Block};
};

struct Plan {
  std::string pipeline_name;
  std::string run_dir;
  std::vector<NodeDef> nodes;
  std::vector<EdgeDef> edges;
};

Plan read_plan(const fs::path& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("Cannot open plan: " + path.string());
  std::string line;
  if (!std::getline(input, line) || line != "NODRIX_NATIVE_PLAN_V1") {
    throw std::runtime_error("Unsupported native plan format");
  }
  Plan plan;
  while (std::getline(input, line)) {
    if (line.empty()) continue;
    const auto fields = split_tabs(line);
    if (fields[0] == "END") break;
    if (fields[0] == "PIPELINE" && fields.size() == 2) {
      plan.pipeline_name = hex_decode(fields[1]);
    } else if (fields[0] == "RUN_DIR" && fields.size() == 2) {
      plan.run_dir = hex_decode(fields[1]);
    } else if (fields[0] == "NODE" && fields.size() == 4) {
      plan.nodes.push_back({hex_decode(fields[1]), hex_decode(fields[2]), hex_decode(fields[3])});
    } else if (fields[0] == "EDGE" && fields.size() == 7) {
      plan.edges.push_back({hex_decode(fields[1]), hex_decode(fields[2]), hex_decode(fields[3]),
                            hex_decode(fields[4]), static_cast<std::size_t>(std::stoull(fields[5])),
                            parse_policy(fields[6])});
    } else {
      throw std::runtime_error("Malformed plan line: " + line);
    }
  }
  if (plan.pipeline_name.empty()) plan.pipeline_name = "native-pipeline";
  if (plan.run_dir.empty()) throw std::runtime_error("Native plan has no run directory");
  return plan;
}

class DynamicLibrary final {
 public:
  explicit DynamicLibrary(const fs::path& path) : path_(path) {
#if defined(_WIN32)
    handle_ = LoadLibraryA(path.string().c_str());
    if (!handle_) throw std::runtime_error("LoadLibrary failed: " + path.string());
#else
    handle_ = ::dlopen(path.string().c_str(), RTLD_NOW | RTLD_LOCAL);
    if (!handle_) throw std::runtime_error("dlopen failed: " + std::string(::dlerror()));
#endif
  }
  DynamicLibrary(const DynamicLibrary&) = delete;
  DynamicLibrary& operator=(const DynamicLibrary&) = delete;
  ~DynamicLibrary() {
#if defined(_WIN32)
    if (handle_) FreeLibrary(static_cast<HMODULE>(handle_));
#else
    if (handle_) ::dlclose(handle_);
#endif
  }

  template <typename T>
  T symbol(const char* name) const {
#if defined(_WIN32)
    auto result = reinterpret_cast<T>(GetProcAddress(static_cast<HMODULE>(handle_), name));
#else
    ::dlerror();
    auto result = reinterpret_cast<T>(::dlsym(handle_, name));
#endif
    if (!result) throw std::runtime_error("Missing plugin symbol " + std::string(name) + " in " + path_.string());
    return result;
  }

 private:
  fs::path path_;
  void* handle_{nullptr};
};

struct NodeHolder {
  vp::Node* pointer{nullptr};
  std::function<void(vp::Node*)> destroy;

  NodeHolder() = default;
  NodeHolder(vp::Node* node, std::function<void(vp::Node*)> fn)
      : pointer(node), destroy(std::move(fn)) {}
  NodeHolder(const NodeHolder&) = delete;
  NodeHolder& operator=(const NodeHolder&) = delete;
  NodeHolder(NodeHolder&& other) noexcept
      : pointer(std::exchange(other.pointer, nullptr)), destroy(std::move(other.destroy)) {}
  NodeHolder& operator=(NodeHolder&& other) noexcept {
    if (this == &other) return *this;
    reset();
    pointer = std::exchange(other.pointer, nullptr);
    destroy = std::move(other.destroy);
    return *this;
  }
  ~NodeHolder() { reset(); }
  void reset() noexcept {
    if (pointer) {
      try { destroy(pointer); } catch (...) {}
      pointer = nullptr;
    }
  }
  vp::Node* operator->() noexcept { return pointer; }
  const vp::Node* operator->() const noexcept { return pointer; }
};

struct NodeStats {
  std::uint64_t process_calls{0};
  std::uint64_t output_messages{0};
  std::uint64_t errors{0};
  std::uint64_t total_process_ns{0};
  std::uint64_t min_process_ns{std::numeric_limits<std::uint64_t>::max()};
  std::uint64_t max_process_ns{0};

  void observe(std::uint64_t duration) noexcept {
    ++process_calls;
    total_process_ns += duration;
    min_process_ns = std::min(min_process_ns, duration);
    max_process_ns = std::max(max_process_ns, duration);
  }
};

struct EdgeStats {
  std::uint64_t enqueued{0};
  std::uint64_t dequeued{0};
  std::uint64_t dropped{0};
  std::size_t max_depth{0};
};

class Edge final {
 public:
  Edge(EdgeDef definition, std::atomic<bool>& stop)
      : definition_(std::move(definition)), stop_(stop) {
    if (definition_.policy == QueuePolicy::Latest || definition_.policy == QueuePolicy::DropOldest) {
      mpmc_ = std::make_unique<vp::MpmcQueue<vp::Message>>(definition_.capacity);
    } else {
      spsc_ = std::make_unique<vp::SpscQueue<vp::Message>>(definition_.capacity);
    }
  }

  bool publish(vp::Message message) {
    if (message.end_of_stream) return publish_eos(std::move(message));
    bool accepted = false;
    switch (definition_.policy) {
      case QueuePolicy::Block:
        accepted = push_until(std::move(message));
        break;
      case QueuePolicy::DropNewest:
        accepted = try_push(std::move(message));
        if (!accepted) ++stats_.dropped;
        break;
      case QueuePolicy::Latest:
      case QueuePolicy::DropOldest: {
        vp::Message stale;
        while (!(accepted = try_push(std::move(message)))) {
          if (try_pop(stale)) ++stats_.dropped;
          else vp::cpu_relax();
        }
        break;
      }
    }
    if (accepted) {
      ++stats_.enqueued;
      stats_.max_depth = std::max(stats_.max_depth, size_approx());
    }
    return accepted;
  }

  bool consume(vp::Message& message) {
    std::uint32_t spins = 0;
    while (!try_pop(message)) {
      if (stop_.load(std::memory_order_acquire) && size_approx() == 0) return false;
      if (++spins < 512) vp::cpu_relax();
      else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    ++stats_.dequeued;
    return true;
  }

  const EdgeDef& definition() const noexcept { return definition_; }
  const EdgeStats& stats() const noexcept { return stats_; }

 private:
  template <typename U>
  bool try_push(U&& message) {
    if (spsc_) return spsc_->try_push(std::forward<U>(message));
    return mpmc_->try_push(std::forward<U>(message));
  }

  bool try_pop(vp::Message& message) {
    if (spsc_) return spsc_->try_pop(message);
    return mpmc_->try_pop(message);
  }

  std::size_t size_approx() const noexcept {
    return spsc_ ? spsc_->size_approx() : mpmc_->size_approx();
  }

  bool push_until(vp::Message message) {
    std::uint32_t spins = 0;
    while (!try_push(std::move(message))) {
      if (stop_.load(std::memory_order_acquire)) return false;
      if (++spins < 512) vp::cpu_relax();
      else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    return true;
  }

  bool publish_eos(vp::Message message) {
    // EOS is never discarded. For overwrite queues, old data is removed only
    // if needed to guarantee graph shutdown.
    std::uint32_t spins = 0;
    while (!try_push(std::move(message))) {
      if (definition_.policy == QueuePolicy::Latest || definition_.policy == QueuePolicy::DropOldest) {
        vp::Message stale;
        if (try_pop(stale)) ++stats_.dropped;
      } else if (stop_.load(std::memory_order_acquire)) {
        return false;
      } else if (++spins < 512) {
        vp::cpu_relax();
      } else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    ++stats_.enqueued;
    stats_.max_depth = std::max(stats_.max_depth, size_approx());
    return true;
  }

  EdgeDef definition_;
  std::atomic<bool>& stop_;
  std::unique_ptr<vp::SpscQueue<vp::Message>> spsc_;
  std::unique_ptr<vp::MpmcQueue<vp::Message>> mpmc_;
  EdgeStats stats_{};
};

struct LoadedNode {
  std::string name;
  std::string uses;
  std::string parameters_json;
  NodeHolder node;
  std::vector<Edge*> inputs;
  std::vector<std::vector<Edge*>> outputs;
  NodeStats stats;
};

class NodeEmitter final : public vp::Emitter {
 public:
  explicit NodeEmitter(LoadedNode& owner) : owner_(owner) {}

  void emit(std::size_t output_port, vp::Message message) override {
    if (output_port >= owner_.outputs.size()) throw std::runtime_error("Output port index out of range");
    auto& edges = owner_.outputs[output_port];
    if (edges.empty()) return;
    ++owner_.stats.output_messages;
    for (std::size_t i = 0; i < edges.size(); ++i) {
      if (i + 1 == edges.size()) edges[i]->publish(std::move(message));
      else edges[i]->publish(message);
    }
  }

  void close_outputs() {
    for (auto& port_edges : owner_.outputs) {
      for (Edge* edge : port_edges) edge->publish(vp::Message::eos());
    }
  }

 private:
  LoadedNode& owner_;
};

std::pair<fs::path, std::string> parse_plugin_reference(std::string_view uses) {
  constexpr std::string_view prefix = "native:";
  if (!uses.starts_with(prefix)) throw std::runtime_error("Invalid native plugin reference");
  const std::string_view body = uses.substr(prefix.size());
  const std::size_t separator = body.rfind('#');
  if (separator == std::string_view::npos) {
    throw std::runtime_error("Native plugin must use native:/path/library#node-type syntax");
  }
  return {fs::path(std::string(body.substr(0, separator))), std::string(body.substr(separator + 1))};
}

class Runtime final {
 public:
  explicit Runtime(Plan plan) : plan_(std::move(plan)) {}

  void build() {
    nodes_.reserve(plan_.nodes.size());
    for (const NodeDef& definition : plan_.nodes) {
      NodeHolder holder;
      if (definition.uses.starts_with("native.")) {
        auto builtin = vp::create_builtin_node(definition.uses, definition.parameters_json);
        vp::Node* raw = builtin.release();
        holder = NodeHolder(raw, [](vp::Node* node) { delete node; });
      } else if (definition.uses.starts_with("native:")) {
        auto [path, node_type] = parse_plugin_reference(definition.uses);
        auto library = std::make_unique<DynamicLibrary>(path);
        const auto abi = library->symbol<vp::PluginAbiVersionFn>("nodrix_plugin_abi_version");
        if (abi() != vp::kPluginAbiVersion) throw std::runtime_error("Nodrix plugin ABI version mismatch");
        const auto create = library->symbol<vp::CreateNodeFn>("nodrix_create_node");
        const auto destroy = library->symbol<vp::DestroyNodeFn>("nodrix_destroy_node");
        vp::Node* raw = create(node_type.c_str(), definition.parameters_json.c_str());
        if (!raw) throw std::runtime_error("Plugin refused node type: " + node_type);
        holder = NodeHolder(raw, [destroy](vp::Node* node) { destroy(node); });
        libraries_.push_back(std::move(library));
      } else {
        throw std::runtime_error("Native engine cannot load node: " + definition.uses);
      }
      LoadedNode loaded;
      loaded.name = definition.name;
      loaded.uses = definition.uses;
      loaded.parameters_json = definition.parameters_json;
      loaded.node = std::move(holder);
      loaded.inputs.resize(loaded.node->input_ports().size(), nullptr);
      loaded.outputs.resize(loaded.node->output_ports().size());
      if (!node_index_.emplace(loaded.name, nodes_.size()).second) {
        throw std::runtime_error("Duplicate node name: " + loaded.name);
      }
      nodes_.push_back(std::move(loaded));
    }

    edges_.reserve(plan_.edges.size());
    for (const EdgeDef& definition : plan_.edges) {
      auto source_it = node_index_.find(definition.source_node);
      auto target_it = node_index_.find(definition.target_node);
      if (source_it == node_index_.end() || target_it == node_index_.end()) {
        throw std::runtime_error("Edge references unknown node");
      }
      LoadedNode& source = nodes_[source_it->second];
      LoadedNode& target = nodes_[target_it->second];
      const auto output_index = port_index(source.node->output_ports(), definition.source_port);
      const auto input_index = port_index(target.node->input_ports(), definition.target_port);
      const auto& output_type = source.node->output_ports()[output_index].type;
      const auto& input_type = target.node->input_ports()[input_index].type;
      if (!(output_type == input_type || output_type == "core.any" || input_type == "core.any")) {
        throw std::runtime_error("Type mismatch: " + output_type + " -> " + input_type);
      }
      if (target.inputs[input_index] != nullptr) {
        throw std::runtime_error("Input already connected: " + target.name + "." + definition.target_port);
      }
      edges_.push_back(std::make_unique<Edge>(definition, stop_));
      Edge* edge = edges_.back().get();
      source.outputs[output_index].push_back(edge);
      target.inputs[input_index] = edge;
    }

    for (LoadedNode& node : nodes_) {
      for (std::size_t i = 0; i < node.inputs.size(); ++i) {
        if (node.inputs[i] == nullptr) {
          throw std::runtime_error("Unconnected input: " + node.name + "." + node.node->input_ports()[i].name);
        }
      }
    }
  }

  int run() {
    const auto start = std::chrono::steady_clock::now();
    for (LoadedNode& node : nodes_) {
      node.node->open({node.name, node.parameters_json, plan_.run_dir});
    }

    std::vector<std::thread> threads;
    threads.reserve(nodes_.size());
    for (LoadedNode& node : nodes_) {
      threads.emplace_back([this, &node] { run_node(node); });
    }
    for (auto& thread : threads) thread.join();

    for (auto it = nodes_.rbegin(); it != nodes_.rend(); ++it) {
      try { it->node->close(); } catch (...) { ++it->stats.errors; }
    }
    const auto finish = std::chrono::steady_clock::now();
    const double duration = std::chrono::duration<double>(finish - start).count();
    write_report(duration);
    if (first_error_) {
      try { std::rethrow_exception(first_error_); }
      catch (const std::exception& error) {
        std::cerr << "Nodrix native runtime failed: " << error.what() << '\n';
      }
      return 1;
    }
    return 0;
  }

 private:
  static std::size_t port_index(const std::vector<vp::PortSpec>& ports, const std::string& name) {
    for (std::size_t i = 0; i < ports.size(); ++i) {
      if (ports[i].name == name) return i;
    }
    throw std::runtime_error("Unknown port: " + name);
  }

  void run_node(LoadedNode& loaded) noexcept {
    NodeEmitter emitter(loaded);
    try {
      if (loaded.node->is_source()) {
        loaded.node->run_source(emitter);
      } else {
        run_processor(loaded, emitter);
      }
      loaded.node->flush(emitter);
    } catch (...) {
      ++loaded.stats.errors;
      {
        std::lock_guard lock(error_mutex_);
        if (!first_error_) first_error_ = std::current_exception();
      }
      stop_.store(true, std::memory_order_release);
    }
    emitter.close_outputs();
  }

  void run_processor(LoadedNode& loaded, NodeEmitter& emitter) {
    std::vector<vp::Message> current(loaded.inputs.size());
    std::vector<bool> have(loaded.inputs.size(), false);
    for (;;) {
      if (!receive_synchronized(loaded, current, have)) return;
      const auto begin = std::chrono::steady_clock::now();
      loaded.node->process(std::span<const vp::Message>(current.data(), current.size()), emitter);
      const auto end = std::chrono::steady_clock::now();
      loaded.stats.observe(static_cast<std::uint64_t>(
          std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count()));
      std::fill(have.begin(), have.end(), false);
    }
  }

  bool receive_synchronized(LoadedNode& loaded, std::vector<vp::Message>& current,
                            std::vector<bool>& have) {
    if (loaded.inputs.size() == 1) {
      if (!loaded.inputs[0]->consume(current[0])) return false;
      return !current[0].end_of_stream;
    }

    for (;;) {
      for (std::size_t i = 0; i < loaded.inputs.size(); ++i) {
        if (!have[i]) {
          if (!loaded.inputs[i]->consume(current[i])) return false;
          if (current[i].end_of_stream) return false;
          have[i] = true;
        }
      }
      std::uint64_t maximum = 0;
      for (const auto& message : current) maximum = std::max(maximum, message.sequence);
      bool aligned = true;
      for (std::size_t i = 0; i < current.size(); ++i) {
        while (current[i].sequence < maximum) {
          if (!loaded.inputs[i]->consume(current[i])) return false;
          if (current[i].end_of_stream) return false;
        }
        if (current[i].sequence != maximum) aligned = false;
      }
      if (aligned) return true;
    }
  }

  void write_report(double duration_seconds) {
    fs::create_directories(plan_.run_dir);
    const fs::path report_path = fs::path(plan_.run_dir) / "native-run.json";
    std::ofstream report(report_path);
    if (!report) throw std::runtime_error("Cannot write native report");

    std::uint64_t maximum_messages = 0;
    for (const auto& node : nodes_) maximum_messages = std::max(maximum_messages, node.stats.process_calls);

    report << "{\n"
           << "  \"pipeline\": \"" << json_escape(plan_.pipeline_name) << "\",\n"
           << "  \"engine\": \"native-cpp20\",\n"
           << "  \"status\": \"" << (first_error_ ? "failed" : "completed") << "\",\n"
           << "  \"run_dir\": \"" << json_escape(plan_.run_dir) << "\",\n"
           << "  \"duration_seconds\": " << std::setprecision(12) << duration_seconds << ",\n"
           << "  \"messages_per_second\": "
           << (duration_seconds > 0 ? static_cast<double>(maximum_messages) / duration_seconds : 0.0) << ",\n"
           << "  \"nodes\": {\n";
    for (std::size_t i = 0; i < nodes_.size(); ++i) {
      const auto& node = nodes_[i];
      const double mean_ms = node.stats.process_calls
                                 ? static_cast<double>(node.stats.total_process_ns) /
                                       static_cast<double>(node.stats.process_calls) / 1e6
                                 : 0.0;
      const double min_ms = node.stats.process_calls ? node.stats.min_process_ns / 1e6 : 0.0;
      report << "    \"" << json_escape(node.name) << "\": {"
             << "\"uses\": \"" << json_escape(node.uses) << "\", "
             << "\"messages\": " << node.stats.process_calls << ", "
             << "\"outputs\": " << node.stats.output_messages << ", "
             << "\"errors\": " << node.stats.errors << ", "
             << "\"mean_ms\": " << mean_ms << ", "
             << "\"min_ms\": " << min_ms << ", "
             << "\"max_ms\": " << node.stats.max_process_ns / 1e6 << "}"
             << (i + 1 == nodes_.size() ? "\n" : ",\n");
    }
    report << "  },\n  \"edges\": [\n";
    for (std::size_t i = 0; i < edges_.size(); ++i) {
      const auto& edge = *edges_[i];
      const auto& def = edge.definition();
      const auto& stats = edge.stats();
      report << "    {\"from\": \"" << json_escape(def.source_node + "." + def.source_port)
             << "\", \"to\": \"" << json_escape(def.target_node + "." + def.target_port)
             << "\", \"enqueued\": " << stats.enqueued
             << ", \"dequeued\": " << stats.dequeued
             << ", \"dropped\": " << stats.dropped
             << ", \"max_depth\": " << stats.max_depth << "}"
             << (i + 1 == edges_.size() ? "\n" : ",\n");
    }
    report << "  ]\n}\n";
  }

  Plan plan_;
  std::atomic<bool> stop_{false};
  std::vector<std::unique_ptr<DynamicLibrary>> libraries_;
  std::vector<LoadedNode> nodes_;
  std::vector<std::unique_ptr<Edge>> edges_;
  std::unordered_map<std::string, std::size_t> node_index_;
  std::mutex error_mutex_;
  std::exception_ptr first_error_;
};

}  // namespace

int main(int argc, char** argv) {
  try {
    fs::path plan_path;
    for (int i = 1; i < argc; ++i) {
      const std::string_view argument(argv[i]);
      if (argument == "--plan" && i + 1 < argc) {
        plan_path = argv[++i];
      } else if (argument == "--version") {
        std::cout << "nodrix-native-runner " << NODRIX_NATIVE_VERSION << '\n';
        return 0;
      } else {
        throw std::runtime_error("Usage: nodrix-native-runner --plan PLAN");
      }
    }
    if (plan_path.empty()) throw std::runtime_error("Missing --plan");
    Runtime runtime(read_plan(plan_path));
    runtime.build();
    return runtime.run();
  } catch (const std::exception& error) {
    std::cerr << "Nodrix native runner error: " << error.what() << '\n';
    return 2;
  }
}
