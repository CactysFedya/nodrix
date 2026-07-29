#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <new>
#include <string>
#include <vector>

namespace {

struct BufferView {
  Py_buffer view{};
  bool acquired{false};

  ~BufferView() {
    if (acquired) PyBuffer_Release(&view);
  }

  bool acquire(PyObject* object, int itemsize, const char* label) {
    if (PyObject_GetBuffer(object, &view, PyBUF_CONTIG_RO | PyBUF_FORMAT) != 0) {
      return false;
    }
    acquired = true;
    if (view.itemsize != itemsize) {
      PyErr_Format(
          PyExc_TypeError,
          "%s must use %d-byte elements; got itemsize=%zd",
          label,
          itemsize,
          view.itemsize);
      return false;
    }
    return true;
  }
};

float box_iou(const float* lhs, const float* rhs) {
  const float left = std::max(lhs[0], rhs[0]);
  const float top = std::max(lhs[1], rhs[1]);
  const float right = std::min(lhs[2], rhs[2]);
  const float bottom = std::min(lhs[3], rhs[3]);
  const float width = std::max(0.0F, right - left);
  const float height = std::max(0.0F, bottom - top);
  const float intersection = width * height;
  const float lhs_area = std::max(0.0F, lhs[2] - lhs[0]) * std::max(0.0F, lhs[3] - lhs[1]);
  const float rhs_area = std::max(0.0F, rhs[2] - rhs[0]) * std::max(0.0F, rhs[3] - rhs[1]);
  const float denominator = lhs_area + rhs_area - intersection;
  return denominator > 0.0F ? intersection / denominator : 0.0F;
}

PyObject* append_index_list(const std::vector<unsigned char>& used, bool want_used) {
  PyObject* result = PyList_New(0);
  if (result == nullptr) return nullptr;
  for (std::size_t index = 0; index < used.size(); ++index) {
    if ((used[index] != 0) != want_used) continue;
    PyObject* value = PyLong_FromSize_t(index);
    if (value == nullptr || PyList_Append(result, value) != 0) {
      Py_XDECREF(value);
      Py_DECREF(result);
      return nullptr;
    }
    Py_DECREF(value);
  }
  return result;
}

PyObject* greedy_iou_assignment(PyObject*, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {
      "track_boxes",
      "detection_boxes",
      "track_classes",
      "detection_classes",
      "minimum_iou",
      "class_agnostic",
      nullptr,
  };

  PyObject* track_boxes_object = nullptr;
  PyObject* detection_boxes_object = nullptr;
  PyObject* track_classes_object = nullptr;
  PyObject* detection_classes_object = nullptr;
  double minimum_iou = 0.0;
  int class_agnostic = 0;
  if (!PyArg_ParseTupleAndKeywords(
          args,
          kwargs,
          "OOOOd|p",
          const_cast<char**>(keywords),
          &track_boxes_object,
          &detection_boxes_object,
          &track_classes_object,
          &detection_classes_object,
          &minimum_iou,
          &class_agnostic)) {
    return nullptr;
  }

  BufferView track_boxes;
  BufferView detection_boxes;
  BufferView track_classes;
  BufferView detection_classes;
  if (!track_boxes.acquire(track_boxes_object, 4, "track_boxes") ||
      !detection_boxes.acquire(detection_boxes_object, 4, "detection_boxes") ||
      !track_classes.acquire(track_classes_object, 4, "track_classes") ||
      !detection_classes.acquire(detection_classes_object, 4, "detection_classes")) {
    return nullptr;
  }

  if (track_boxes.view.len % static_cast<Py_ssize_t>(sizeof(float) * 4) != 0 ||
      detection_boxes.view.len % static_cast<Py_ssize_t>(sizeof(float) * 4) != 0) {
    PyErr_SetString(PyExc_ValueError, "box buffers must contain N*4 float32 values");
    return nullptr;
  }

  const std::size_t track_count =
      static_cast<std::size_t>(track_boxes.view.len) / (sizeof(float) * 4);
  const std::size_t detection_count =
      static_cast<std::size_t>(detection_boxes.view.len) / (sizeof(float) * 4);
  if (track_classes.view.len != static_cast<Py_ssize_t>(track_count * sizeof(std::int32_t)) ||
      detection_classes.view.len != static_cast<Py_ssize_t>(detection_count * sizeof(std::int32_t))) {
    PyErr_SetString(PyExc_ValueError, "class buffers must have one int32 value per box");
    return nullptr;
  }

  const auto* track_box_data = static_cast<const float*>(track_boxes.view.buf);
  const auto* detection_box_data = static_cast<const float*>(detection_boxes.view.buf);
  const auto* track_class_data = static_cast<const std::int32_t*>(track_classes.view.buf);
  const auto* detection_class_data = static_cast<const std::int32_t*>(detection_classes.view.buf);

  std::vector<float> scores(track_count * detection_count, -1.0F);
  std::vector<unsigned char> used_tracks(track_count, 0);
  std::vector<unsigned char> used_detections(detection_count, 0);

  Py_BEGIN_ALLOW_THREADS
  for (std::size_t track = 0; track < track_count; ++track) {
    for (std::size_t detection = 0; detection < detection_count; ++detection) {
      if (!class_agnostic && track_class_data[track] != detection_class_data[detection]) {
        continue;
      }
      scores[track * detection_count + detection] =
          box_iou(track_box_data + track * 4, detection_box_data + detection * 4);
    }
  }
  Py_END_ALLOW_THREADS

  PyObject* matches = PyList_New(0);
  if (matches == nullptr) return nullptr;

  while (track_count > 0 && detection_count > 0) {
    float best_score = -1.0F;
    std::size_t best_track = 0;
    std::size_t best_detection = 0;
    for (std::size_t track = 0; track < track_count; ++track) {
      if (used_tracks[track]) continue;
      for (std::size_t detection = 0; detection < detection_count; ++detection) {
        if (used_detections[detection]) continue;
        const float score = scores[track * detection_count + detection];
        if (score > best_score) {
          best_score = score;
          best_track = track;
          best_detection = detection;
        }
      }
    }
    if (best_score < static_cast<float>(minimum_iou)) break;

    used_tracks[best_track] = 1;
    used_detections[best_detection] = 1;
    PyObject* pair = Py_BuildValue("(nn)", static_cast<Py_ssize_t>(best_track),
                                   static_cast<Py_ssize_t>(best_detection));
    if (pair == nullptr || PyList_Append(matches, pair) != 0) {
      Py_XDECREF(pair);
      Py_DECREF(matches);
      return nullptr;
    }
    Py_DECREF(pair);
  }

  PyObject* unmatched_tracks = append_index_list(used_tracks, false);
  PyObject* unmatched_detections = append_index_list(used_detections, false);
  if (unmatched_tracks == nullptr || unmatched_detections == nullptr) {
    Py_DECREF(matches);
    Py_XDECREF(unmatched_tracks);
    Py_XDECREF(unmatched_detections);
    return nullptr;
  }

  PyObject* result = PyTuple_New(3);
  if (result == nullptr) {
    Py_DECREF(matches);
    Py_DECREF(unmatched_tracks);
    Py_DECREF(unmatched_detections);
    return nullptr;
  }
  PyTuple_SET_ITEM(result, 0, matches);
  PyTuple_SET_ITEM(result, 1, unmatched_tracks);
  PyTuple_SET_ITEM(result, 2, unmatched_detections);
  return result;
}

PyObject* backend_info(PyObject*, PyObject*) {
  return Py_BuildValue(
      "{s:s,s:s,s:s}",
      "backend",
      "cpp20",
      "algorithm",
      "greedy-iou-assignment",
      "optimization",
      "O3-native-buffer-protocol");
}

PyMethodDef methods[] = {
    {"greedy_iou_assignment",
     reinterpret_cast<PyCFunction>(greedy_iou_assignment),
     METH_VARARGS | METH_KEYWORDS,
     "Run deterministic class-aware greedy IoU assignment in native C++20."},
    {"backend_info", backend_info, METH_NOARGS, "Describe the native tracking backend."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native_tracking",
    "Native tracking primitives for Nodrix Vision.",
    -1,
    methods,
};

}  // namespace

PyMODINIT_FUNC PyInit__native_tracking() { return PyModule_Create(&module); }
