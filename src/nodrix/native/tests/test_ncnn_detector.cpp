#include <cassert>
#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>

#include "../src/ncnn_detector_plugin.cpp"

namespace {

bool near(float left, float right) {
  return std::fabs(left - right) < 1.0e-5F;
}

void test_unicode_and_config_validation() {
  const auto config = parse_config(
      R"({"model":"models/\u041c\u043e\u0434\u0435\u043b\u044c",)"
      R"("imgsz":320,"mean":[0,0,0],"norm":[0.1,0.2,0.3]})");
  assert(config.model == "models/\xD0\x9C\xD0\xBE\xD0\xB4\xD0\xB5"
                         "\xD0\xBB\xD1\x8C");
  assert(config.width == 320);
  assert(config.height == 320);

  bool rejected = false;
  try {
    (void)parse_config(
        R"({"model":"model","imgsz":320,"norm":[0.5]})");
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  assert(rejected);

  rejected = false;
  try {
    (void)parse_config(
        R"({"model":"model","imgsz":320,"threads":0})");
  } catch (const std::invalid_argument&) {
    rejected = true;
  }
  assert(rejected);
}

void test_ultralytics_decode_and_nms() {
  Config config;
  config.output_format = "ultralytics";
  config.num_classes = 2;
  config.conf = 0.2F;
  config.iou = 0.5F;
  config.max_det = 10;

  ncnn::Mat output(
      3,
      6,
      {
          20.F, 20.F, 20.F, 20.F, 0.90F, 0.10F,
          21.F, 21.F, 20.F, 20.F, 0.80F, 0.20F,
          70.F, 70.F, 10.F, 10.F, 0.10F, 0.95F,
      });
  const auto detections = decode(output, config);
  assert(detections.size() == 2);
  assert(detections[0].class_id == 1);
  assert(near(detections[0].score, 0.95F));
  assert(detections[1].class_id == 0);
  assert(near(detections[1].score, 0.90F));
}

void test_objectness_and_transposed_output() {
  Config config;
  config.output_format = "ultralytics";
  config.has_objectness = "true";
  config.num_classes = 2;
  config.conf = 0.25F;
  config.max_det = 10;

  ncnn::Mat objectness(
      1,
      7,
      {10.F, 12.F, 4.F, 6.F, 0.5F, 0.2F, 0.8F});
  const auto first = decode(objectness, config);
  assert(first.size() == 1);
  assert(first[0].class_id == 1);
  assert(near(first[0].score, 0.4F));

  config.has_objectness = "false";
  ncnn::Mat transposed(
      6,
      2,
      {
          20.F, 80.F,
          20.F, 80.F,
          10.F, 12.F,
          10.F, 12.F,
          0.9F, 0.1F,
          0.1F, 0.85F,
      });
  const auto second = decode(transposed, config);
  assert(second.size() == 2);
  assert(second[0].class_id == 0);
  assert(second[1].class_id == 1);
}

void test_one_dimensional_output_is_one_candidate() {
  Config config;
  config.output_format = "ultralytics";
  config.num_classes = 2;
  config.conf = 0.2F;
  ncnn::Mat output(
      std::vector<float>{20.F, 20.F, 10.F, 10.F, 0.8F, 0.1F});
  const auto detections = decode(output, config);
  assert(detections.size() == 1);
  assert(detections[0].class_id == 0);
  assert(near(detections[0].score, 0.8F));
}

void test_xyxy_and_class_filter() {
  Config config;
  config.output_format = "auto";
  config.classes = {2};
  config.conf = 0.1F;
  config.max_det = 5;
  ncnn::Mat output(
      2,
      6,
      {
          1.F, 2.F, 10.F, 20.F, 0.9F, 2.F,
          2.F, 3.F, 11.F, 21.F, 0.8F, 1.F,
      });
  const auto detections = decode(output, config);
  assert(detections.size() == 1);
  assert(detections[0].class_id == 2);
  assert(near(detections[0].x1, 1.F));
  assert(near(detections[0].y2, 20.F));
}

}  // namespace

int main() {
  test_unicode_and_config_validation();
  test_ultralytics_decode_and_nms();
  test_objectness_and_transposed_output();
  test_one_dimensional_output_is_one_candidate();
  test_xyxy_and_class_filter();
  return 0;
}
