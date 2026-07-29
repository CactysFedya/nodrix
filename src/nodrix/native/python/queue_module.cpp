#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <new>
#include <string>
#include <vector>

namespace {

enum class Policy { Block, Latest, DropOldest, DropNewest };

struct QueueState {
  explicit QueueState(std::size_t capacity, Policy policy)
      : ring(capacity, nullptr), capacity(capacity), policy(policy) {}

  std::vector<PyObject*> ring;
  std::size_t capacity;
  Policy policy;
  std::size_t head{0};
  std::size_t tail{0};
  std::size_t size{0};
  bool closed{false};
  std::uint64_t enqueued{0};
  std::uint64_t dequeued{0};
  std::uint64_t dropped{0};
  std::size_t max_depth{0};
  std::mutex mutex;
  std::condition_variable not_empty;
  std::condition_variable not_full;
};

typedef struct {
  PyObject_HEAD
  QueueState* state;
} BoundedQueueObject;

Policy parse_policy(const char* value) {
  const std::string text(value ? value : "block");
  if (text == "block") return Policy::Block;
  if (text == "latest") return Policy::Latest;
  if (text == "drop_oldest") return Policy::DropOldest;
  if (text == "drop_newest") return Policy::DropNewest;
  throw std::invalid_argument("policy must be block, latest, drop_oldest, or drop_newest");
}

void drop_oldest_locked(QueueState& state) {
  PyObject* stale = state.ring[state.head];
  state.ring[state.head] = nullptr;
  state.head = (state.head + 1) % state.capacity;
  --state.size;
  ++state.dropped;
  Py_XDECREF(stale);  // All public methods enter with the GIL held.
}

PyObject* BoundedQueue_new(PyTypeObject* type, PyObject*, PyObject*) {
  auto* self = reinterpret_cast<BoundedQueueObject*>(type->tp_alloc(type, 0));
  if (self != nullptr) self->state = nullptr;
  return reinterpret_cast<PyObject*>(self);
}

int BoundedQueue_init(BoundedQueueObject* self, PyObject* args, PyObject* kwargs) {
  static const char* keywords[] = {"capacity", "policy", nullptr};
  Py_ssize_t capacity = 0;
  const char* policy_text = "block";
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "n|s", const_cast<char**>(keywords),
                                   &capacity, &policy_text)) {
    return -1;
  }
  if (capacity < 1) {
    PyErr_SetString(PyExc_ValueError, "capacity must be at least 1");
    return -1;
  }
  try {
    delete self->state;
    self->state = new QueueState(static_cast<std::size_t>(capacity), parse_policy(policy_text));
  } catch (const std::exception& exc) {
    PyErr_SetString(PyExc_ValueError, exc.what());
    return -1;
  }
  return 0;
}

void BoundedQueue_dealloc(BoundedQueueObject* self) {
  if (self->state != nullptr) {
    {
      std::lock_guard<std::mutex> lock(self->state->mutex);
      self->state->closed = true;
      for (PyObject*& item : self->state->ring) {
        Py_XDECREF(item);
        item = nullptr;
      }
      self->state->size = 0;
    }
    self->state->not_empty.notify_all();
    self->state->not_full.notify_all();
    delete self->state;
    self->state = nullptr;
  }
  Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}

PyObject* BoundedQueue_put(BoundedQueueObject* self, PyObject* item) {
  if (self->state == nullptr) {
    PyErr_SetString(PyExc_RuntimeError, "queue is not initialized");
    return nullptr;
  }
  QueueState& state = *self->state;
  Py_INCREF(item);  // Queue owns this reference after acceptance.
  std::unique_lock<std::mutex> lock(state.mutex);

  if (state.policy == Policy::Block) {
    while (!state.closed && state.size == state.capacity) {
      PyThreadState* thread_state = PyEval_SaveThread();
      state.not_full.wait(lock, [&] { return state.closed || state.size < state.capacity; });
      lock.unlock();
      PyEval_RestoreThread(thread_state);
      lock.lock();
    }
  } else if (state.size == state.capacity) {
    if (state.policy == Policy::DropNewest) {
      ++state.dropped;
      lock.unlock();
      Py_DECREF(item);
      Py_RETURN_FALSE;
    }
    // latest and drop_oldest both evict queued stale data. With capacity > 1,
    // latest collapses the complete backlog to the newest message.
    if (state.policy == Policy::Latest) {
      while (state.size > 0) drop_oldest_locked(state);
    } else {
      drop_oldest_locked(state);
    }
  }

  if (state.closed) {
    lock.unlock();
    Py_DECREF(item);
    Py_RETURN_FALSE;
  }
  state.ring[state.tail] = item;
  state.tail = (state.tail + 1) % state.capacity;
  ++state.size;
  ++state.enqueued;
  state.max_depth = std::max(state.max_depth, state.size);
  lock.unlock();
  state.not_empty.notify_one();
  Py_RETURN_TRUE;
}


PyObject* BoundedQueue_put_control(BoundedQueueObject* self, PyObject* item) {
  if (self->state == nullptr) {
    PyErr_SetString(PyExc_RuntimeError, "queue is not initialized");
    return nullptr;
  }
  QueueState& state = *self->state;
  Py_INCREF(item);
  std::unique_lock<std::mutex> lock(state.mutex);
  while (!state.closed && state.size == state.capacity) {
    PyThreadState* thread_state = PyEval_SaveThread();
    state.not_full.wait(lock, [&] { return state.closed || state.size < state.capacity; });
    lock.unlock();
    PyEval_RestoreThread(thread_state);
    lock.lock();
  }
  if (state.closed) {
    lock.unlock();
    Py_DECREF(item);
    Py_RETURN_FALSE;
  }
  state.ring[state.tail] = item;
  state.tail = (state.tail + 1) % state.capacity;
  ++state.size;
  ++state.enqueued;
  state.max_depth = std::max(state.max_depth, state.size);
  lock.unlock();
  state.not_empty.notify_one();
  Py_RETURN_TRUE;
}

PyObject* BoundedQueue_get(BoundedQueueObject* self, PyObject*) {
  if (self->state == nullptr) {
    PyErr_SetString(PyExc_RuntimeError, "queue is not initialized");
    return nullptr;
  }
  QueueState& state = *self->state;
  std::unique_lock<std::mutex> lock(state.mutex);
  while (!state.closed && state.size == 0) {
    PyThreadState* thread_state = PyEval_SaveThread();
    state.not_empty.wait(lock, [&] { return state.closed || state.size > 0; });
    lock.unlock();
    PyEval_RestoreThread(thread_state);
    lock.lock();
  }
  if (state.size == 0) {
    Py_RETURN_NONE;
  }
  PyObject* item = state.ring[state.head];
  state.ring[state.head] = nullptr;
  state.head = (state.head + 1) % state.capacity;
  --state.size;
  ++state.dequeued;
  lock.unlock();
  state.not_full.notify_one();
  return item;  // Transfer the queue's owned reference to the caller.
}

PyObject* BoundedQueue_try_get(BoundedQueueObject* self, PyObject*) {
  if (self->state == nullptr) {
    PyErr_SetString(PyExc_RuntimeError, "queue is not initialized");
    return nullptr;
  }
  QueueState& state = *self->state;
  std::unique_lock<std::mutex> lock(state.mutex);
  if (state.size == 0) Py_RETURN_NONE;
  PyObject* item = state.ring[state.head];
  state.ring[state.head] = nullptr;
  state.head = (state.head + 1) % state.capacity;
  --state.size;
  ++state.dequeued;
  lock.unlock();
  state.not_full.notify_one();
  return item;
}

PyObject* BoundedQueue_close(BoundedQueueObject* self, PyObject*) {
  if (self->state != nullptr) {
    {
      std::lock_guard<std::mutex> lock(self->state->mutex);
      self->state->closed = true;
    }
    self->state->not_empty.notify_all();
    self->state->not_full.notify_all();
  }
  Py_RETURN_NONE;
}

PyObject* BoundedQueue_qsize(BoundedQueueObject* self, PyObject*) {
  if (self->state == nullptr) return PyLong_FromLong(0);
  std::lock_guard<std::mutex> lock(self->state->mutex);
  return PyLong_FromSize_t(self->state->size);
}

PyObject* BoundedQueue_stats(BoundedQueueObject* self, PyObject*) {
  if (self->state == nullptr) return PyDict_New();
  std::lock_guard<std::mutex> lock(self->state->mutex);
  PyObject* result = PyDict_New();
  if (result == nullptr) return nullptr;
  auto set_u64 = [&](const char* key, std::uint64_t value) {
    PyObject* object = PyLong_FromUnsignedLongLong(value);
    if (object != nullptr) {
      PyDict_SetItemString(result, key, object);
      Py_DECREF(object);
    }
  };
  set_u64("enqueued", self->state->enqueued);
  set_u64("dequeued", self->state->dequeued);
  set_u64("dropped", self->state->dropped);
  set_u64("max_depth", self->state->max_depth);
  set_u64("depth", self->state->size);
  return result;
}

PyMethodDef BoundedQueue_methods[] = {
    {"put", reinterpret_cast<PyCFunction>(BoundedQueue_put), METH_O,
     "Put an object into the bounded queue and return whether it was accepted."},
    {"put_control", reinterpret_cast<PyCFunction>(BoundedQueue_put_control), METH_O,
     "Put a control message without applying data-drop policies."},
    {"get", reinterpret_cast<PyCFunction>(BoundedQueue_get), METH_NOARGS,
     "Block until an object is available; return None after close."},
    {"try_get", reinterpret_cast<PyCFunction>(BoundedQueue_try_get), METH_NOARGS,
     "Return an object immediately, or None if the queue is empty."},
    {"close", reinterpret_cast<PyCFunction>(BoundedQueue_close), METH_NOARGS,
     "Close the queue and wake blocked producers/consumers."},
    {"qsize", reinterpret_cast<PyCFunction>(BoundedQueue_qsize), METH_NOARGS,
     "Return the current queue depth."},
    {"stats", reinterpret_cast<PyCFunction>(BoundedQueue_stats), METH_NOARGS,
     "Return queue counters."},
    {nullptr, nullptr, 0, nullptr},
};

PyTypeObject BoundedQueueType = {
    PyVarObject_HEAD_INIT(nullptr, 0)
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_native_queue",
    "Native bounded queues for Nodrix's Python/C++ hybrid runtime.",
    -1,
    nullptr,
};

}  // namespace

PyMODINIT_FUNC PyInit__native_queue() {
  BoundedQueueType.tp_name = "nodrix._native_queue.BoundedQueue";
  BoundedQueueType.tp_basicsize = sizeof(BoundedQueueObject);
  BoundedQueueType.tp_itemsize = 0;
  BoundedQueueType.tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE;
  BoundedQueueType.tp_doc = "C++ bounded queue that stores Python objects by reference.";
  BoundedQueueType.tp_methods = BoundedQueue_methods;
  BoundedQueueType.tp_init = reinterpret_cast<initproc>(BoundedQueue_init);
  BoundedQueueType.tp_new = BoundedQueue_new;
  BoundedQueueType.tp_dealloc = reinterpret_cast<destructor>(BoundedQueue_dealloc);
  if (PyType_Ready(&BoundedQueueType) < 0) return nullptr;
  PyObject* result = PyModule_Create(&module);
  if (result == nullptr) return nullptr;
  Py_INCREF(&BoundedQueueType);
  if (PyModule_AddObject(result, "BoundedQueue", reinterpret_cast<PyObject*>(&BoundedQueueType)) < 0) {
    Py_DECREF(&BoundedQueueType);
    Py_DECREF(result);
    return nullptr;
  }
  return result;
}
