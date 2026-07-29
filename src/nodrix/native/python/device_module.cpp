#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cerrno>
#include <cstring>
#include <cstdint>
#include <string>

#if defined(__linux__)
#include <dirent.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <unistd.h>
#endif

namespace {

PyObject* py_bool(bool value) { return PyBool_FromLong(value ? 1 : 0); }

void dict_set_owned(PyObject* dict, const char* key, PyObject* value) {
  if (value == nullptr) return;
  PyDict_SetItemString(dict, key, value);
  Py_DECREF(value);
}

#if defined(__linux__)
std::string c_string(const __u8* value, std::size_t size) {
  const char* begin = reinterpret_cast<const char*>(value);
  std::size_t length = 0;
  while (length < size && begin[length] != '\0') ++length;
  return std::string(begin, length);
}

PyObject* v4l2_probe(PyObject*, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {"device", nullptr};
  const char* device = "/dev/video0";
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|s", const_cast<char**>(keywords), &device)) {
    return nullptr;
  }
  const int fd = ::open(device, O_RDWR | O_NONBLOCK | O_CLOEXEC);
  if (fd < 0) return PyErr_SetFromErrnoWithFilename(PyExc_OSError, device);
  v4l2_capability capability{};
  if (::ioctl(fd, VIDIOC_QUERYCAP, &capability) < 0) {
    const int saved = errno;
    ::close(fd);
    errno = saved;
    return PyErr_SetFromErrnoWithFilename(PyExc_OSError, device);
  }
  ::close(fd);
  const std::uint32_t caps = capability.device_caps ? capability.device_caps : capability.capabilities;
  PyObject* result = PyDict_New();
  dict_set_owned(result, "device", PyUnicode_FromString(device));
  dict_set_owned(result, "driver", PyUnicode_FromString(c_string(capability.driver, sizeof(capability.driver)).c_str()));
  dict_set_owned(result, "card", PyUnicode_FromString(c_string(capability.card, sizeof(capability.card)).c_str()));
  dict_set_owned(result, "bus_info", PyUnicode_FromString(c_string(capability.bus_info, sizeof(capability.bus_info)).c_str()));
  dict_set_owned(result, "version", PyLong_FromUnsignedLong(capability.version));
  dict_set_owned(result, "capabilities", PyLong_FromUnsignedLong(caps));
  dict_set_owned(result, "video_capture", py_bool((caps & V4L2_CAP_VIDEO_CAPTURE) != 0));
  dict_set_owned(result, "video_capture_mplane", py_bool((caps & V4L2_CAP_VIDEO_CAPTURE_MPLANE) != 0));
  dict_set_owned(result, "streaming", py_bool((caps & V4L2_CAP_STREAMING) != 0));
  dict_set_owned(result, "readwrite", py_bool((caps & V4L2_CAP_READWRITE) != 0));
  return result;
}

bool path_exists(const char* path) { return ::access(path, F_OK) == 0; }

PyObject* native_device_doctor(PyObject*, PyObject*) {
  PyObject* result = PyDict_New();
  dict_set_owned(result, "platform", PyUnicode_FromString("linux"));
  dict_set_owned(result, "v4l2_headers", py_bool(true));
  dict_set_owned(result, "dma_heap", py_bool(path_exists("/dev/dma_heap")));
  dict_set_owned(result, "dri", py_bool(path_exists("/dev/dri")));
  dict_set_owned(result, "video0", py_bool(path_exists("/dev/video0")));

  const char* libraries[] = {"libavformat.so", "libavformat.so.61", "libavformat.so.60", "libavformat.so.59"};
  void* handle = nullptr;
  const char* loaded = nullptr;
  for (const char* library : libraries) {
    handle = ::dlopen(library, RTLD_LAZY | RTLD_LOCAL);
    if (handle != nullptr) {
      loaded = library;
      break;
    }
  }
  dict_set_owned(result, "libavformat", py_bool(handle != nullptr));
  if (loaded != nullptr) dict_set_owned(result, "libavformat_library", PyUnicode_FromString(loaded));
  if (handle != nullptr) {
    using VersionFunction = unsigned (*)();
    auto* version = reinterpret_cast<VersionFunction>(::dlsym(handle, "avformat_version"));
    if (version != nullptr) dict_set_owned(result, "libavformat_version", PyLong_FromUnsignedLong(version()));
    ::dlclose(handle);
  }
  return result;
}
#else
PyObject* v4l2_probe(PyObject*, PyObject*, PyObject*) {
  PyErr_SetString(PyExc_NotImplementedError, "V4L2 is available only on Linux");
  return nullptr;
}
PyObject* native_device_doctor(PyObject*, PyObject*) {
  PyObject* result = PyDict_New();
  dict_set_owned(result, "platform", PyUnicode_FromString("unsupported"));
  dict_set_owned(result, "v4l2_headers", py_bool(false));
  return result;
}
#endif

PyMethodDef methods[] = {
    {"v4l2_probe", reinterpret_cast<PyCFunction>(v4l2_probe), METH_VARARGS | METH_KEYWORDS,
     "Query a Linux V4L2 device without starting a capture stream."},
    {"device_doctor", native_device_doctor, METH_NOARGS,
     "Report native device-memory and libav capabilities."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native_device",
    "Nodrix native device-memory capability module.",
    -1,
    methods,
};

}  // namespace

PyMODINIT_FUNC PyInit__native_device() { return PyModule_Create(&module); }
