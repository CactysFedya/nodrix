#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace ncnn {

class Mat {
 public:
  static constexpr int PIXEL_BGR2RGB = 1;

  Mat() = default;

  explicit Mat(std::vector<float> values)
      : dims(1),
        w(static_cast<int>(values.size())),
        h(1),
        c(1),
        elempack(1),
        elemsize(sizeof(float)),
        values_(std::move(values)) {}

  Mat(int rows, int columns, std::vector<float> values)
      : dims(2),
        w(columns),
        h(rows),
        c(1),
        elempack(1),
        elemsize(sizeof(float)),
        values_(std::move(values)) {}

  bool empty() const noexcept { return values_.empty(); }

  const float* row(int index) const {
    return values_.data() + static_cast<std::size_t>(index * w);
  }

  static Mat from_pixels(const std::uint8_t*, int, int width, int height) {
    return Mat(height, width, std::vector<float>(
                                 static_cast<std::size_t>(width * height)));
  }

  void substract_mean_normalize(const float*, const float*) {}

  int dims{};
  int w{};
  int h{};
  int c{};
  int elempack{1};
  std::size_t elemsize{sizeof(float)};

 private:
  std::vector<float> values_;
};

class Extractor {
 public:
  void set_num_threads(int) {}
  int input(const char*, const Mat&) { return 0; }
  int extract(const char*, Mat&) { return 0; }
};

class Net {
 public:
  struct Options {
    int num_threads{};
    bool use_vulkan_compute{};
    bool lightmode{};
    bool use_fp16_packed{};
    bool use_fp16_storage{};
    bool use_fp16_arithmetic{};
  };

  int load_param(const char*) { return 0; }
  int load_model(const char*) { return 0; }
  Extractor create_extractor() const { return {}; }
  void clear() {}

  Options opt;
};

}  // namespace ncnn
