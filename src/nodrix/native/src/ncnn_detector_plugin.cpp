#include <algorithm>
#include <array>
#include <cmath>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <limits>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

#include <net.h>

#include "nodrix/cpp_plugin.hpp"
#include "nodrix/message.hpp"

namespace fs = std::filesystem;

namespace {

struct Detection {
  float x1{};
  float y1{};
  float x2{};
  float y2{};
  float score{};
  std::int32_t class_id{};
  std::size_t order{};
};

struct Config {
  std::string model;
  std::string param;
  std::string bin;
  std::string input_blob{"in0"};
  std::string output_blob{"out0"};
  std::string output_format{"auto"};
  std::string has_objectness{"auto"};
  std::string backend{"cpu"};
  int width{320};
  int height{320};
  int threads{4};
  int max_det{150};
  int num_classes{-1};
  float conf{0.25F};
  float iou{0.45F};
  bool class_agnostic{false};
  std::vector<int> classes;
  std::vector<float> mean;
  std::vector<float> norm{1.0F / 255.0F, 1.0F / 255.0F, 1.0F / 255.0F};
};

std::size_t find_value(std::string_view json, std::string_view key) {
  const std::string quoted = "\"" + std::string(key) + "\"";
  const auto key_pos = json.find(quoted);
  if (key_pos == std::string_view::npos) return std::string_view::npos;
  const auto colon = json.find(':', key_pos + quoted.size());
  if (colon == std::string_view::npos) return std::string_view::npos;
  auto pos = colon + 1;
  while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
  return pos;
}

int hex_digit(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  return -1;
}

bool read_hex_quad(std::string_view json, std::size_t start,
                   std::uint32_t& result) {
  if (start + 4 > json.size()) return false;
  result = 0;
  for (std::size_t offset = 0; offset < 4; ++offset) {
    const int digit = hex_digit(json[start + offset]);
    if (digit < 0) return false;
    result = (result << 4U) | static_cast<std::uint32_t>(digit);
  }
  return true;
}

void append_utf8(std::string& output, std::uint32_t codepoint) {
  if (codepoint <= 0x7FU) {
    output.push_back(static_cast<char>(codepoint));
  } else if (codepoint <= 0x7FFU) {
    output.push_back(static_cast<char>(0xC0U | (codepoint >> 6U)));
    output.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
  } else if (codepoint <= 0xFFFFU) {
    output.push_back(static_cast<char>(0xE0U | (codepoint >> 12U)));
    output.push_back(
        static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
  } else {
    output.push_back(static_cast<char>(0xF0U | (codepoint >> 18U)));
    output.push_back(
        static_cast<char>(0x80U | ((codepoint >> 12U) & 0x3FU)));
    output.push_back(
        static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
  }
}

std::string json_string(std::string_view json, std::string_view key, std::string fallback = {}) {
  const auto pos = find_value(json, key);
  if (pos == std::string_view::npos || pos >= json.size() || json[pos] != '"') return fallback;
  std::string result;
  for (std::size_t index = pos + 1; index < json.size(); ++index) {
    const char ch = json[index];
    if (ch == '"') return result;
    if (ch == '\\' && index + 1 < json.size()) {
      const char escaped = json[++index];
      switch (escaped) {
        case '"': result.push_back('"'); break;
        case '\\': result.push_back('\\'); break;
        case '/': result.push_back('/'); break;
        case 'b': result.push_back('\b'); break;
        case 'f': result.push_back('\f'); break;
        case 'n': result.push_back('\n'); break;
        case 'r': result.push_back('\r'); break;
        case 't': result.push_back('\t'); break;
        case 'u': {
          std::uint32_t codepoint = 0;
          if (!read_hex_quad(json, index + 1, codepoint)) return fallback;
          index += 4;
          if (codepoint >= 0xD800U && codepoint <= 0xDBFFU) {
            if (index + 6 >= json.size() || json[index + 1] != '\\' ||
                json[index + 2] != 'u') {
              return fallback;
            }
            std::uint32_t low = 0;
            if (!read_hex_quad(json, index + 3, low) ||
                low < 0xDC00U || low > 0xDFFFU) {
              return fallback;
            }
            index += 6;
            codepoint =
                0x10000U + ((codepoint - 0xD800U) << 10U) +
                (low - 0xDC00U);
          } else if (codepoint >= 0xDC00U && codepoint <= 0xDFFFU) {
            return fallback;
          }
          append_utf8(result, codepoint);
          break;
        }
        default: return fallback;
      }
    } else {
      result.push_back(ch);
    }
  }
  return fallback;
}

template <typename T>
T json_number(std::string_view json, std::string_view key, T fallback) {
  const auto pos = find_value(json, key);
  if (pos == std::string_view::npos) return fallback;
  try {
    std::size_t used = 0;
    const std::string tail(json.substr(pos));
    if constexpr (std::is_integral_v<T>) {
      const long long value = std::stoll(tail, &used);
      return used ? static_cast<T>(value) : fallback;
    } else {
      const double value = std::stod(tail, &used);
      return used ? static_cast<T>(value) : fallback;
    }
  } catch (...) {
    return fallback;
  }
}

bool json_bool(std::string_view json, std::string_view key, bool fallback) {
  const auto pos = find_value(json, key);
  if (pos == std::string_view::npos) return fallback;
  const auto tail = json.substr(pos);
  if (tail.starts_with("true")) return true;
  if (tail.starts_with("false")) return false;
  return fallback;
}

template <typename T>
std::vector<T> json_array(std::string_view json, std::string_view key) {
  const auto pos = find_value(json, key);
  if (pos == std::string_view::npos || pos >= json.size() || json[pos] != '[') return {};
  const auto end = json.find(']', pos + 1);
  if (end == std::string_view::npos) return {};
  std::vector<T> result;
  std::size_t cursor = pos + 1;
  while (cursor < end) {
    while (cursor < end && (std::isspace(static_cast<unsigned char>(json[cursor])) || json[cursor] == ',')) ++cursor;
    if (cursor >= end) break;
    try {
      std::size_t used = 0;
      const std::string tail(json.substr(cursor, end - cursor));
      if constexpr (std::is_integral_v<T>) {
        result.push_back(static_cast<T>(std::stoll(tail, &used)));
      } else {
        result.push_back(static_cast<T>(std::stod(tail, &used)));
      }
      if (!used) break;
      cursor += used;
    } catch (...) {
      break;
    }
  }
  return result;
}

Config parse_config(std::string_view json) {
  Config result;
  result.model = json_string(json, "model");
  result.param = json_string(json, "param", json_string(json, "param_path"));
  result.bin = json_string(json, "bin", json_string(json, "bin_path"));
  result.input_blob = json_string(json, "input_blob", result.input_blob);
  result.output_blob = json_string(json, "output_blob", result.output_blob);
  result.output_format = json_string(json, "output_format", result.output_format);
  result.backend = json_string(json, "backend", result.backend);
  if (result.output_format == "xyxy") result.output_format = "xyxy_score_class";
  if (result.output_format == "yolo") result.output_format = "ultralytics";
  result.has_objectness = json_string(json, "has_objectness", result.has_objectness);
  const int size = json_number<int>(json, "imgsz", 0);
  result.width = json_number<int>(json, "width", size > 0 ? size : result.width);
  result.height = json_number<int>(json, "height", size > 0 ? size : result.height);
  result.threads = json_number<int>(json, "threads", result.threads);
  result.max_det = json_number<int>(json, "max_det", result.max_det);
  result.num_classes = json_number<int>(json, "num_classes", result.num_classes);
  result.conf = json_number<float>(json, "conf", json_number<float>(json, "confidence", result.conf));
  result.iou = json_number<float>(json, "iou", result.iou);
  result.class_agnostic = json_bool(json, "class_agnostic", false);
  result.classes = json_array<int>(json, "classes");
  const auto mean = json_array<float>(json, "mean");
  const auto norm = json_array<float>(json, "norm");
  if (!mean.empty()) result.mean = mean;
  if (!norm.empty()) result.norm = norm;
  if (result.backend != "cpu" && result.backend != "auto") {
    throw std::invalid_argument("native NCNN detector backend must be cpu or auto");
  }
  if (result.output_format != "auto" &&
      result.output_format != "xyxy_score_class" &&
      result.output_format != "ultralytics") {
    throw std::invalid_argument(
        "output_format must be auto, xyxy_score_class, or ultralytics");
  }
  if (result.has_objectness != "auto" &&
      result.has_objectness != "true" &&
      result.has_objectness != "false" &&
      result.has_objectness != "1" &&
      result.has_objectness != "0" &&
      result.has_objectness != "yes" &&
      result.has_objectness != "no") {
    throw std::invalid_argument(
        "has_objectness must be auto, true, or false");
  }
  if (result.width <= 0 || result.height <= 0) throw std::invalid_argument("imgsz or positive width/height is required");
  if (result.threads <= 0) {
    throw std::invalid_argument("threads must be >= 1");
  }
  if (result.max_det <= 0) {
    throw std::invalid_argument("max_det must be >= 1");
  }
  if (result.num_classes < -1) {
    throw std::invalid_argument("num_classes must be >= 0 when specified");
  }
  if (result.conf < 0.0F || result.conf > 1.0F) throw std::invalid_argument("conf must be in [0,1]");
  if (result.iou < 0.0F || result.iou > 1.0F) throw std::invalid_argument("iou must be in [0,1]");
  if (!result.mean.empty() && result.mean.size() != 3) {
    throw std::invalid_argument("mean must contain exactly three values");
  }
  if (!result.norm.empty() && result.norm.size() != 3) {
    throw std::invalid_argument("norm must contain exactly three values");
  }
  if (std::any_of(result.classes.begin(), result.classes.end(),
                  [](int value) { return value < 0; })) {
    throw std::invalid_argument("classes must contain non-negative IDs");
  }
  return result;
}

std::pair<fs::path, fs::path> resolve_model(const Config& config) {
  if (!config.param.empty() || !config.bin.empty()) {
    if (config.param.empty() || config.bin.empty()) throw std::invalid_argument("both param and bin are required");
    return {fs::absolute(config.param), fs::absolute(config.bin)};
  }
  if (config.model.empty()) throw std::invalid_argument("model, or param and bin, is required");
  fs::path model = fs::absolute(config.model);
  if (fs::is_directory(model)) {
    std::vector<fs::path> params;
    std::vector<fs::path> bins;
    for (const auto& item : fs::directory_iterator(model)) {
      if (!item.is_regular_file()) continue;
      if (item.path().extension() == ".param") params.push_back(item.path());
      if (item.path().extension() == ".bin") bins.push_back(item.path());
    }
    if (params.size() != 1 || bins.size() != 1) {
      throw std::runtime_error("NCNN model directory must contain exactly one .param and one .bin file");
    }
    return {params.front(), bins.front()};
  }
  if (model.extension() == ".param") {
    auto bin = model;
    bin.replace_extension(".bin");
    return {model, bin};
  }
  if (model.extension() == ".bin") {
    auto param = model;
    param.replace_extension(".param");
    return {param, model};
  }
  fs::path param = fs::path(model.string() + ".param");
  fs::path bin = fs::path(model.string() + ".bin");
  if (!fs::is_regular_file(param) || !fs::is_regular_file(bin)) {
    param = fs::path(model.string() + ".ncnn.param");
    bin = fs::path(model.string() + ".ncnn.bin");
  }
  return {param, bin};
}

float iou(const Detection& a, const Detection& b) {
  const float x1 = std::max(a.x1, b.x1);
  const float y1 = std::max(a.y1, b.y1);
  const float x2 = std::min(a.x2, b.x2);
  const float y2 = std::min(a.y2, b.y2);
  const float w = std::max(0.0F, x2 - x1);
  const float h = std::max(0.0F, y2 - y1);
  const float intersection = w * h;
  const float area_a = std::max(0.0F, a.x2 - a.x1) * std::max(0.0F, a.y2 - a.y1);
  const float area_b = std::max(0.0F, b.x2 - b.x1) * std::max(0.0F, b.y2 - b.y1);
  const float total = area_a + area_b - intersection;
  return total > 0.0F ? intersection / total : 0.0F;
}

bool allowed_class(const Config& config, int class_id) {
  return config.classes.empty() || std::find(config.classes.begin(), config.classes.end(), class_id) != config.classes.end();
}

struct MatrixView {
  const ncnn::Mat* mat{};
  int rows{};
  int cols{};
  bool transpose{};
  bool one_dimensional{};

  float value(int row, int column) const {
    if (one_dimensional) return mat->row(0)[column];
    if (!transpose) return mat->row(row)[column];
    return mat->row(column)[row];
  }
};

MatrixView matrix_view(const ncnn::Mat& output, int num_classes) {
  if (output.empty()) throw std::runtime_error("NCNN returned an empty output tensor");
  if (output.elempack != 1 || output.elemsize != sizeof(float)) {
    throw std::runtime_error("NCNN output must be unpacked float32");
  }
  int rows = 0;
  int cols = 0;
  if (output.dims == 2) {
    rows = output.h;
    cols = output.w;
  } else if (output.dims == 3 && output.c == 1) {
    rows = output.h;
    cols = output.w;
  } else if (output.dims == 1) {
    return {&output, 1, output.w, false, true};
  } else {
    throw std::runtime_error("NCNN YOLO output must reduce to a 2-D float matrix");
  }

  const auto expected = [num_classes](int value) {
    return value == 6 || (num_classes >= 0 && (value == num_classes + 4 || value == num_classes + 5));
  };
  const bool row_features = expected(rows);
  const bool column_features = expected(cols);
  bool transpose = false;
  if (row_features && !column_features) transpose = true;
  else if (!column_features && rows <= 512 && cols > rows) transpose = true;
  return {
      &output,
      transpose ? cols : rows,
      transpose ? rows : cols,
      transpose,
      false,
  };
}

bool looks_like_xyxy(const MatrixView& matrix) {
  if (matrix.cols != 6 || matrix.rows == 0) return false;
  int valid = 0;
  int score_like = 0;
  int class_like = 0;
  int box_like = 0;
  for (int row = 0; row < matrix.rows; ++row) {
    std::array<float, 6> values{};
    bool finite = true;
    for (int column = 0; column < 6; ++column) {
      values[column] = matrix.value(row, column);
      finite = finite && std::isfinite(values[column]);
    }
    if (!finite) continue;
    ++valid;
    if (values[4] >= 0.0F && values[4] <= 1.0F) ++score_like;
    if (values[5] >= 0.0F && std::fabs(values[5] - std::round(values[5])) <= 1.0e-4F) ++class_like;
    if (values[2] > values[0] && values[3] > values[1]) ++box_like;
  }
  if (!valid) return false;
  return score_like * 100 >= valid * 95 && class_like * 100 >= valid * 95 && box_like * 2 >= valid;
}

std::vector<Detection> decode(const ncnn::Mat& output, const Config& config) {
  const auto matrix = matrix_view(output, config.num_classes);
  const bool xyxy = config.output_format == "xyxy_score_class" ||
                    (config.output_format == "auto" && looks_like_xyxy(matrix));
  if (!xyxy && matrix.cols < 5) throw std::runtime_error("YOLO output has fewer than five features");

  bool has_objectness = false;
  if (!xyxy) {
    if (config.has_objectness == "true" || config.has_objectness == "1" || config.has_objectness == "yes") {
      has_objectness = true;
    } else if (config.has_objectness == "false" || config.has_objectness == "0" || config.has_objectness == "no") {
      has_objectness = false;
    } else if (config.num_classes >= 0) {
      has_objectness = matrix.cols == config.num_classes + 5;
    }
  }
  const int class_start = has_objectness ? 5 : 4;
  if (!xyxy && class_start >= matrix.cols) throw std::runtime_error("YOLO output has no class scores");

  std::vector<Detection> candidates;
  candidates.reserve(static_cast<std::size_t>(matrix.rows));
  for (int row = 0; row < matrix.rows; ++row) {
    Detection item;
    item.order = static_cast<std::size_t>(row);
    if (xyxy) {
      item.x1 = matrix.value(row, 0);
      item.y1 = matrix.value(row, 1);
      item.x2 = matrix.value(row, 2);
      item.y2 = matrix.value(row, 3);
      item.score = matrix.value(row, 4);
      item.class_id = static_cast<std::int32_t>(std::lround(matrix.value(row, 5)));
    } else {
      int best_class = 0;
      float best_score = -std::numeric_limits<float>::infinity();
      for (int column = class_start; column < matrix.cols; ++column) {
        const float value = matrix.value(row, column);
        if (value > best_score) {
          best_score = value;
          best_class = column - class_start;
        }
      }
      item.score = best_score * (has_objectness ? matrix.value(row, 4) : 1.0F);
      item.class_id = best_class;
      const float cx = matrix.value(row, 0);
      const float cy = matrix.value(row, 1);
      const float width = matrix.value(row, 2);
      const float height = matrix.value(row, 3);
      item.x1 = cx - width * 0.5F;
      item.y1 = cy - height * 0.5F;
      item.x2 = cx + width * 0.5F;
      item.y2 = cy + height * 0.5F;
    }
    const bool finite = std::isfinite(item.x1) && std::isfinite(item.y1) && std::isfinite(item.x2) &&
                        std::isfinite(item.y2) && std::isfinite(item.score);
    if (!finite || item.score < config.conf || item.x2 <= item.x1 || item.y2 <= item.y1 ||
        !allowed_class(config, item.class_id)) {
      continue;
    }
    candidates.push_back(item);
  }

  std::stable_sort(candidates.begin(), candidates.end(), [](const Detection& left, const Detection& right) {
    if (left.score != right.score) return left.score > right.score;
    return left.order < right.order;
  });
  std::vector<Detection> selected;
  selected.reserve(std::min<std::size_t>(candidates.size(), static_cast<std::size_t>(config.max_det)));
  for (const auto& candidate : candidates) {
    bool suppress = false;
    for (const auto& accepted : selected) {
      if (!config.class_agnostic && accepted.class_id != candidate.class_id) continue;
      if (iou(accepted, candidate) > config.iou) {
        suppress = true;
        break;
      }
    }
    if (!suppress) {
      selected.push_back(candidate);
      if (selected.size() >= static_cast<std::size_t>(config.max_det)) break;
    }
  }
  return selected;
}

class NcnnDetector final : public nodrix::c_api::Node {
 public:
  explicit NcnnDetector(std::string_view parameters) : config_(parse_config(parameters)) {}

  std::span<const nodrix_port_v2> input_ports() const noexcept override { return inputs_; }
  std::span<const nodrix_port_v2> output_ports() const noexcept override { return outputs_; }

  nodrix_status_v2 open(const nodrix_node_context_v2&) override {
    const auto [param, bin] = resolve_model(config_);
    if (!fs::is_regular_file(param) || !fs::is_regular_file(bin)) {
      throw std::runtime_error("NCNN model files are missing: " + param.string() + " / " + bin.string());
    }
    net_.opt.num_threads = config_.threads;
    net_.opt.use_vulkan_compute = false;
    net_.opt.lightmode = true;
    net_.opt.use_fp16_packed = true;
    net_.opt.use_fp16_storage = true;
    net_.opt.use_fp16_arithmetic = false;
    const int param_status = net_.load_param(param.string().c_str());
    const int model_status = net_.load_model(bin.string().c_str());
    if (param_status != 0 || model_status != 0) {
      throw std::runtime_error("NCNN failed to load model: param=" + std::to_string(param_status) +
                               " bin=" + std::to_string(model_status));
    }
    return NODRIX_STATUS_OK;
  }

  nodrix_status_v2 process(std::span<const nodrix_message_v2> inputs,
                           const nodrix::c_api::Emitter& emitter) override {
    if (inputs.size() != 1 || !inputs[0].present) return NODRIX_STATUS_INVALID_ARGUMENT;
    const auto& input = inputs[0];
    const std::size_t expected = static_cast<std::size_t>(config_.width) *
                                 static_cast<std::size_t>(config_.height) * 3U;
    if (!input.payload.data || input.payload.size != expected) {
      throw std::runtime_error(
          "native NCNN detector expects an exact contiguous BGR8 payload "
          "matching imgsz");
    }

    ncnn::Mat tensor = ncnn::Mat::from_pixels(
        input.payload.data, ncnn::Mat::PIXEL_BGR2RGB, config_.width, config_.height);
    const float* mean = config_.mean.empty() ? nullptr : config_.mean.data();
    const float* norm = config_.norm.empty() ? nullptr : config_.norm.data();
    tensor.substract_mean_normalize(mean, norm);

    ncnn::Extractor extractor = net_.create_extractor();
    const int input_status = extractor.input(config_.input_blob.c_str(), tensor);
    if (input_status != 0) throw std::runtime_error("NCNN rejected input blob with status " + std::to_string(input_status));
    ncnn::Mat output;
    const int output_status = extractor.extract(config_.output_blob.c_str(), output);
    if (output_status != 0) throw std::runtime_error("NCNN output extraction failed with status " + std::to_string(output_status));

    const auto detections = decode(output, config_);
    encode_payload(detections);

    nodrix_message_v2 message{};
    message.struct_size = sizeof(message);
    message.type_id = nodrix::fnv1a_64("vision.detections");
    message.sequence = input.sequence;
    message.source_timestamp_ns = input.source_timestamp_ns;
    message.runtime_timestamp_ns = input.runtime_timestamp_ns;
    message.correlation = input.correlation;
    message.present = 1;
    message.payload.struct_size = sizeof(nodrix_buffer_v2);
    message.payload.data = payload_.data();
    message.payload.size = payload_.size();
    message.payload.memory = {
        sizeof(nodrix_memory_handle_v2), NODRIX_MEMORY_HOST, 0, 0, 0,
        static_cast<std::uint64_t>(payload_.size()),
        NODRIX_MEMORY_FLAG_HOST_VISIBLE | NODRIX_MEMORY_FLAG_READ_ONLY,
        nullptr, nullptr, nullptr};
    emitter.emit(0, message);
    return NODRIX_STATUS_OK;
  }

  nodrix_status_v2 close() override {
    net_.clear();
    payload_.clear();
    return NODRIX_STATUS_OK;
  }

 private:
  void encode_payload(const std::vector<Detection>& detections) {
    constexpr std::array<std::uint8_t, 4> magic{'N', 'D', 'T', '2'};
    const std::uint16_t version = 1;
    const std::uint16_t flags = 0;
    const std::uint32_t count = static_cast<std::uint32_t>(detections.size());
    const std::uint32_t reserved = 0;
    const std::size_t header_size = 16;
    payload_.resize(header_size + detections.size() * (16 + 4 + 4));
    std::size_t offset = 0;
    auto append = [&](const void* data, std::size_t size) {
      std::memcpy(payload_.data() + offset, data, size);
      offset += size;
    };
    append(magic.data(), magic.size());
    append(&version, sizeof(version));
    append(&flags, sizeof(flags));
    append(&count, sizeof(count));
    append(&reserved, sizeof(reserved));
    for (const auto& item : detections) {
      const std::array<float, 4> box{item.x1, item.y1, item.x2, item.y2};
      append(box.data(), sizeof(box));
    }
    for (const auto& item : detections) append(&item.score, sizeof(item.score));
    for (const auto& item : detections) append(&item.class_id, sizeof(item.class_id));
  }

  Config config_;
  ncnn::Net net_;
  std::vector<std::uint8_t> payload_;
  const nodrix_port_v2 inputs_[1]{{sizeof(nodrix_port_v2), "frame", "vision.frame", "cpu", 0, 0}};
  const nodrix_port_v2 outputs_[1]{{sizeof(nodrix_port_v2), "detections", "vision.detections", "cpu", 0, 0}};
};

}  // namespace

extern "C" NODRIX_C_EXPORT std::uint32_t nodrix_plugin_abi_version_v2(void) {
  return NODRIX_C_ABI_VERSION;
}

extern "C" NODRIX_C_EXPORT std::uint64_t nodrix_plugin_features_v2(void) {
  return NODRIX_C_FEATURE_TYPED_PORTS |
         NODRIX_C_FEATURE_MEMORY_DOMAINS |
         NODRIX_C_FEATURE_ZERO_COPY_BUFFERS |
         NODRIX_C_FEATURE_CORRELATION |
         NODRIX_C_FEATURE_DEVICE_HANDLES;
}

extern "C" NODRIX_C_EXPORT nodrix_status_v2 nodrix_plugin_create_v2(
    std::uint32_t host_abi_version,
    const char* node_type,
    const char* parameters_json,
    nodrix_node_api_v2* output) {
  if (host_abi_version != NODRIX_C_ABI_VERSION) return NODRIX_STATUS_ABI_MISMATCH;
  if (!node_type || std::string_view(node_type) != "vision.ncnn_detector") return NODRIX_STATUS_UNSUPPORTED;
  try {
    return nodrix::c_api::export_node(new NcnnDetector(parameters_json ? parameters_json : "{}"), output);
  } catch (...) {
    return NODRIX_STATUS_RUNTIME_ERROR;
  }
}
