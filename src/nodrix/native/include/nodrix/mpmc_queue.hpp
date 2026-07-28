#pragma once

#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <new>
#include <thread>
#include <utility>

#include "nodrix/spsc_queue.hpp"

namespace nodrix {

// Dmitry Vyukov-style bounded queue. It is used only for overwrite policies,
// where the producer may also remove the oldest item while the consumer runs.
template <typename T>
class MpmcQueue final {
 public:
  explicit MpmcQueue(std::size_t requested_capacity)
      : capacity_(std::bit_ceil(requested_capacity < 2 ? std::size_t{2} : requested_capacity)),
        mask_(capacity_ - 1),
        cells_(std::make_unique<Cell[]>(capacity_)) {
    for (std::size_t i = 0; i < capacity_; ++i) {
      cells_[i].sequence.store(i, std::memory_order_relaxed);
    }
  }

  MpmcQueue(const MpmcQueue&) = delete;
  MpmcQueue& operator=(const MpmcQueue&) = delete;

  ~MpmcQueue() {
    T item;
    while (try_pop(item)) {
    }
  }

  template <typename U>
  bool try_push(U&& item) {
    Cell* cell;
    std::size_t position = enqueue_pos_.load(std::memory_order_relaxed);
    for (;;) {
      cell = &cells_[position & mask_];
      const std::size_t sequence = cell->sequence.load(std::memory_order_acquire);
      const std::intptr_t difference = static_cast<std::intptr_t>(sequence) -
                                       static_cast<std::intptr_t>(position);
      if (difference == 0) {
        if (enqueue_pos_.compare_exchange_weak(position, position + 1,
                                               std::memory_order_relaxed)) {
          break;
        }
      } else if (difference < 0) {
        return false;
      } else {
        position = enqueue_pos_.load(std::memory_order_relaxed);
      }
    }
    new (&cell->storage) T(std::forward<U>(item));
    cell->sequence.store(position + 1, std::memory_order_release);
    return true;
  }

  bool try_pop(T& out) {
    Cell* cell;
    std::size_t position = dequeue_pos_.load(std::memory_order_relaxed);
    for (;;) {
      cell = &cells_[position & mask_];
      const std::size_t sequence = cell->sequence.load(std::memory_order_acquire);
      const std::intptr_t difference = static_cast<std::intptr_t>(sequence) -
                                       static_cast<std::intptr_t>(position + 1);
      if (difference == 0) {
        if (dequeue_pos_.compare_exchange_weak(position, position + 1,
                                               std::memory_order_relaxed)) {
          break;
        }
      } else if (difference < 0) {
        return false;
      } else {
        position = dequeue_pos_.load(std::memory_order_relaxed);
      }
    }
    T* value = std::launder(reinterpret_cast<T*>(&cell->storage));
    out = std::move(*value);
    value->~T();
    cell->sequence.store(position + capacity_, std::memory_order_release);
    return true;
  }

  template <typename U>
  void push_blocking(U&& item) {
    std::uint32_t spins = 0;
    while (!try_push(std::forward<U>(item))) {
      if (++spins < 256) cpu_relax();
      else {
        spins = 0;
        std::this_thread::yield();
      }
    }
  }

  void pop_blocking(T& item) {
    std::uint32_t spins = 0;
    while (!try_pop(item)) {
      if (++spins < 256) cpu_relax();
      else {
        spins = 0;
        std::this_thread::yield();
      }
    }
  }

  [[nodiscard]] std::size_t size_approx() const noexcept {
    const auto enqueue = enqueue_pos_.load(std::memory_order_acquire);
    const auto dequeue = dequeue_pos_.load(std::memory_order_acquire);
    return enqueue - dequeue;
  }

 private:
  struct Cell {
    std::atomic<std::size_t> sequence{0};
    alignas(T) std::byte storage[sizeof(T)];
  };

  const std::size_t capacity_;
  const std::size_t mask_;
  std::unique_ptr<Cell[]> cells_;
  alignas(64) std::atomic<std::size_t> enqueue_pos_{0};
  alignas(64) std::atomic<std::size_t> dequeue_pos_{0};
};

}  // namespace nodrix
