#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cstddef>
#include <cstdint>

PyObject* frame_mean(PyObject*, PyObject* object) {
  Py_buffer view{};
  if (PyObject_GetBuffer(object, &view, PyBUF_CONTIG_RO) != 0) return nullptr;
  const auto* bytes = static_cast<const std::uint8_t*>(view.buf);
  const std::size_t size = static_cast<std::size_t>(view.len);
  std::uint64_t sum = 0;
  Py_BEGIN_ALLOW_THREADS
  for (std::size_t i = 0; i < size; ++i) sum += bytes[i];
  Py_END_ALLOW_THREADS
  PyBuffer_Release(&view);
  return PyFloat_FromDouble(size ? static_cast<double>(sum) / static_cast<double>(size) : 0.0);
}

PyMethodDef methods[] = {
    {"frame_mean", reinterpret_cast<PyCFunction>(frame_mean), METH_O,
     "Calculate uint8 frame mean directly through the Python buffer protocol."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_frame_mean_native",
    "Native backend for the migration example.",
    -1,
    methods,
};

PyMODINIT_FUNC PyInit__frame_mean_native() { return PyModule_Create(&module); }
