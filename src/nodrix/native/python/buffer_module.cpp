#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <new>
#include <vector>

namespace {

void* aligned_allocate(std::size_t size, std::size_t alignment) {
#if defined(_WIN32)
  return _aligned_malloc(size, alignment);
#else
  void* data = nullptr;
  if (::posix_memalign(&data, alignment, size) != 0) return nullptr;
  return data;
#endif
}

void aligned_release(void* data) noexcept {
#if defined(_WIN32)
  _aligned_free(data);
#else
  std::free(data);
#endif
}

struct PoolState {
  PoolState(std::size_t bytes, std::size_t cached, std::size_t align)
      : block_size(bytes), max_cached(cached), alignment(align) {}
  ~PoolState() {
    for (void* block : free_blocks) aligned_release(block);
  }

  void* acquire(std::size_t size) {
    std::lock_guard<std::mutex> lock(mutex);
    ++acquires;
    if (size == block_size && !free_blocks.empty()) {
      void* block = free_blocks.back();
      free_blocks.pop_back();
      ++reuses;
      in_use += size;
      peak_in_use = std::max(peak_in_use, in_use);
      return block;
    }
    void* block = aligned_allocate(size, alignment);
    if (block == nullptr) throw std::bad_alloc{};
    ++allocations;
    in_use += size;
    peak_in_use = std::max(peak_in_use, in_use);
    return block;
  }

  void release(void* data, std::size_t size) noexcept {
    if (data == nullptr) return;
    std::lock_guard<std::mutex> lock(mutex);
    if (in_use >= size) in_use -= size;
    ++releases;
    if (size == block_size && free_blocks.size() < max_cached) {
      free_blocks.push_back(data);
    } else {
      aligned_release(data);
    }
  }

  std::size_t block_size;
  std::size_t max_cached;
  std::size_t alignment;
  std::vector<void*> free_blocks;
  std::mutex mutex;
  std::uint64_t acquires{0};
  std::uint64_t releases{0};
  std::uint64_t allocations{0};
  std::uint64_t reuses{0};
  std::size_t in_use{0};
  std::size_t peak_in_use{0};
};

typedef struct {
  PyObject_HEAD
  std::shared_ptr<PoolState>* pool;
} BufferPoolObject;

typedef struct {
  PyObject_HEAD
  std::shared_ptr<PoolState>* pool;
  void* data;
  Py_ssize_t size;
  int readonly;
  int released;
} NativeBufferObject;

PyTypeObject BufferPoolType = {PyVarObject_HEAD_INIT(nullptr, 0)};
PyTypeObject NativeBufferType = {PyVarObject_HEAD_INIT(nullptr, 0)};

void NativeBuffer_release_storage(NativeBufferObject* self) noexcept {
  if (!self->released && self->data != nullptr && self->pool != nullptr) {
    (*self->pool)->release(self->data, static_cast<std::size_t>(self->size));
    self->data = nullptr;
    self->released = 1;
  }
}

PyObject* NativeBuffer_new(PyTypeObject* type, PyObject*, PyObject*) {
  auto* self = reinterpret_cast<NativeBufferObject*>(type->tp_alloc(type, 0));
  if (self != nullptr) {
    self->pool = nullptr;
    self->data = nullptr;
    self->size = 0;
    self->readonly = 0;
    self->released = 1;
  }
  return reinterpret_cast<PyObject*>(self);
}

void NativeBuffer_dealloc(NativeBufferObject* self) {
  NativeBuffer_release_storage(self);
  delete self->pool;
  self->pool = nullptr;
  Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}

int NativeBuffer_getbuffer(NativeBufferObject* self, Py_buffer* view, int flags) {
  if (self->released || self->data == nullptr) {
    PyErr_SetString(PyExc_BufferError, "Nodrix buffer has been released");
    return -1;
  }
  return PyBuffer_FillInfo(
      view, reinterpret_cast<PyObject*>(self), self->data, self->size,
      self->readonly, flags);
}

void NativeBuffer_releasebuffer(NativeBufferObject*, Py_buffer*) {}

PyObject* NativeBuffer_release(NativeBufferObject* self, PyObject*) {
  NativeBuffer_release_storage(self);
  Py_RETURN_NONE;
}

PyObject* NativeBuffer_get_nbytes(NativeBufferObject* self, void*) {
  return PyLong_FromSsize_t(self->released ? 0 : self->size);
}

PyObject* NativeBuffer_get_readonly(NativeBufferObject* self, void*) {
  return PyBool_FromLong(self->readonly);
}

PyMethodDef NativeBuffer_methods[] = {
    {"release", reinterpret_cast<PyCFunction>(NativeBuffer_release), METH_NOARGS,
     "Return the storage to its native buffer pool."},
    {nullptr, nullptr, 0, nullptr},
};

PyGetSetDef NativeBuffer_getset[] = {
    {const_cast<char*>("nbytes"), reinterpret_cast<getter>(NativeBuffer_get_nbytes), nullptr,
     const_cast<char*>("Buffer size in bytes."), nullptr},
    {const_cast<char*>("readonly"), reinterpret_cast<getter>(NativeBuffer_get_readonly), nullptr,
     const_cast<char*>("Whether the buffer is read-only."), nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

PyBufferProcs NativeBuffer_buffer_procs = {
    reinterpret_cast<getbufferproc>(NativeBuffer_getbuffer),
    reinterpret_cast<releasebufferproc>(NativeBuffer_releasebuffer),
};

PyObject* BufferPool_new(PyTypeObject* type, PyObject*, PyObject*) {
  auto* self = reinterpret_cast<BufferPoolObject*>(type->tp_alloc(type, 0));
  if (self != nullptr) self->pool = nullptr;
  return reinterpret_cast<PyObject*>(self);
}

int BufferPool_init(BufferPoolObject* self, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {"block_size", "max_cached", "alignment", nullptr};
  Py_ssize_t block_size = 0;
  Py_ssize_t max_cached = 32;
  Py_ssize_t alignment = 64;
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "n|nn", const_cast<char**>(keywords),
                                   &block_size, &max_cached, &alignment)) {
    return -1;
  }
  if (block_size <= 0 || max_cached < 0 || alignment < static_cast<Py_ssize_t>(sizeof(void*))) {
    PyErr_SetString(PyExc_ValueError, "invalid block_size, max_cached, or alignment");
    return -1;
  }
  delete self->pool;
  self->pool = new std::shared_ptr<PoolState>(std::make_shared<PoolState>(
      static_cast<std::size_t>(block_size), static_cast<std::size_t>(max_cached),
      static_cast<std::size_t>(alignment)));
  return 0;
}

void BufferPool_dealloc(BufferPoolObject* self) {
  delete self->pool;
  self->pool = nullptr;
  Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}

PyObject* BufferPool_acquire(BufferPoolObject* self, PyObject* args, PyObject* kwargs) {
  if (self->pool == nullptr) {
    PyErr_SetString(PyExc_RuntimeError, "buffer pool is not initialized");
    return nullptr;
  }
  static const char* keywords[] = {"size", "readonly", nullptr};
  Py_ssize_t size = static_cast<Py_ssize_t>((*self->pool)->block_size);
  int readonly = 0;
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|np", const_cast<char**>(keywords),
                                   &size, &readonly)) {
    return nullptr;
  }
  if (size <= 0) {
    PyErr_SetString(PyExc_ValueError, "size must be positive");
    return nullptr;
  }
  auto* result = reinterpret_cast<NativeBufferObject*>(NativeBufferType.tp_alloc(&NativeBufferType, 0));
  if (result == nullptr) return nullptr;
  try {
    result->pool = new std::shared_ptr<PoolState>(*self->pool);
    result->data = (*self->pool)->acquire(static_cast<std::size_t>(size));
    result->size = size;
    result->readonly = readonly;
    result->released = 0;
  } catch (const std::exception& exc) {
    delete result->pool;
    result->pool = nullptr;
    Py_DECREF(reinterpret_cast<PyObject*>(result));
    PyErr_SetString(PyExc_MemoryError, exc.what());
    return nullptr;
  }
  return reinterpret_cast<PyObject*>(result);
}

PyObject* BufferPool_stats(BufferPoolObject* self, PyObject*) {
  if (self->pool == nullptr) return PyDict_New();
  auto& pool = **self->pool;
  std::lock_guard<std::mutex> lock(pool.mutex);
  PyObject* result = PyDict_New();
  auto set = [&](const char* key, unsigned long long value) {
    PyObject* object = PyLong_FromUnsignedLongLong(value);
    if (object != nullptr) {
      PyDict_SetItemString(result, key, object);
      Py_DECREF(object);
    }
  };
  set("block_size", pool.block_size);
  set("cached", pool.free_blocks.size());
  set("acquires", pool.acquires);
  set("releases", pool.releases);
  set("allocations", pool.allocations);
  set("reuses", pool.reuses);
  set("in_use_bytes", pool.in_use);
  set("peak_in_use_bytes", pool.peak_in_use);
  return result;
}

PyMethodDef BufferPool_methods[] = {
    {"acquire", reinterpret_cast<PyCFunction>(BufferPool_acquire), METH_VARARGS | METH_KEYWORDS,
     "Acquire an aligned native buffer without copying."},
    {"stats", reinterpret_cast<PyCFunction>(BufferPool_stats), METH_NOARGS,
     "Return pool allocation/reuse counters."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native_buffer",
    "Managed aligned buffer pools for Nodrix.",
    -1,
    nullptr,
};

}  // namespace

PyMODINIT_FUNC PyInit__native_buffer() {
  NativeBufferType.tp_name = "nodrix._native_buffer.NativeBuffer";
  NativeBufferType.tp_basicsize = sizeof(NativeBufferObject);
  NativeBufferType.tp_flags = Py_TPFLAGS_DEFAULT;
  NativeBufferType.tp_doc = "Native aligned buffer implementing Python's buffer protocol.";
  NativeBufferType.tp_new = NativeBuffer_new;
  NativeBufferType.tp_dealloc = reinterpret_cast<destructor>(NativeBuffer_dealloc);
  NativeBufferType.tp_methods = NativeBuffer_methods;
  NativeBufferType.tp_getset = NativeBuffer_getset;
  NativeBufferType.tp_as_buffer = &NativeBuffer_buffer_procs;
  if (PyType_Ready(&NativeBufferType) < 0) return nullptr;

  BufferPoolType.tp_name = "nodrix._native_buffer.BufferPool";
  BufferPoolType.tp_basicsize = sizeof(BufferPoolObject);
  BufferPoolType.tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE;
  BufferPoolType.tp_doc = "Reusable aligned native buffer pool.";
  BufferPoolType.tp_new = BufferPool_new;
  BufferPoolType.tp_init = reinterpret_cast<initproc>(BufferPool_init);
  BufferPoolType.tp_dealloc = reinterpret_cast<destructor>(BufferPool_dealloc);
  BufferPoolType.tp_methods = BufferPool_methods;
  if (PyType_Ready(&BufferPoolType) < 0) return nullptr;

  PyObject* result = PyModule_Create(&module);
  if (result == nullptr) return nullptr;
  Py_INCREF(&NativeBufferType);
  Py_INCREF(&BufferPoolType);
  if (PyModule_AddObject(result, "NativeBuffer", reinterpret_cast<PyObject*>(&NativeBufferType)) < 0 ||
      PyModule_AddObject(result, "BufferPool", reinterpret_cast<PyObject*>(&BufferPoolType)) < 0) {
    Py_DECREF(result);
    return nullptr;
  }
  return result;
}
