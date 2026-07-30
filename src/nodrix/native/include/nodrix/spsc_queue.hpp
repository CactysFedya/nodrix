#pragma once

#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <new>
#include <stdexcept>
#include <thread>
#include <utility>

#if defined(_MSC_VER) && (defined(_M_X64) || defined(_M_IX86))
#include <intrin.h>
#endif

namespace nodrix {

inline void cpu_relax() noexcept {
#if defined(_MSC_VER) && (defined(_M_X64) || defined(_M_IX86))
  _mm_pause();
#elif defined(__x86_64__) || defined(__i386)
  __builtin_ia32_pause();
#elif (defined(__aarch64__) || defined(__arm__)) && \
    (defined(__GNUC__) || defined(__clang__))
  asm volatile("yield" ::: "memory");
#else
  std::atomic_signal_fence(std::memory_order_seq_cst);
#endif
}

template <typename T>
class SpscQueue final {
 public:
  explicit SpscQueue(std::size_t requested_capacity)
      : capacity_(std::bit_ceil(requested_capacity < 2 ? std::size_t{2} : requested_capacity)),
        mask_(capacity_ - 1),
        storage_(std::make_unique<Slot[]>(capacity_)) {
    if (!std::has_single_bit(capacity_)) throw std::logic_error("capacity must be power of two");
  }

  SpscQueue(const SpscQueue&) = delete;
  SpscQueue& operator=(const SpscQueue&) = delete;

  ~SpscQueue() {
    T item;
    while (try_pop(item)) {
    }
  }

  [[nodiscard]] bool try_push(const T& value) { return emplace(value); }
  [[nodiscard]] bool try_push(T&& value) { return emplace(std::move(value)); }

  template <typename U>
  bool push_blocking(U&& value) {
    std::uint32_t spins = 0;
    while (!emplace(std::forward<U>(value))) {
      if (++spins < 256) {
        cpu_relax();
      } else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    return true;
  }

  [[nodiscard]] bool try_pop(T& out) {
    const std::size_t tail = tail_.load(std::memory_order_relaxed);
    if (tail == head_.load(std::memory_order_acquire)) return false;
    Slot& slot = storage_[tail & mask_];
    T* value = std::launder(reinterpret_cast<T*>(&slot.storage));
    out = std::move(*value);
    value->~T();
    tail_.store(tail + 1, std::memory_order_release);
    return true;
  }

  bool pop_blocking(T& out) {
    std::uint32_t spins = 0;
    while (!try_pop(out)) {
      if (++spins < 256) {
        cpu_relax();
      } else {
        spins = 0;
        std::this_thread::yield();
      }
    }
    return true;
  }

  [[nodiscard]] std::size_t size_approx() const noexcept {
    const std::size_t head = head_.load(std::memory_order_acquire);
    const std::size_t tail = tail_.load(std::memory_order_acquire);
    return head - tail;
  }

  [[nodiscard]] std::size_t capacity() const noexcept { return capacity_; }

 private:
  struct Slot {
    alignas(T) std::byte storage[sizeof(T)];
  };

  template <typename U>
  bool emplace(U&& value) {
    const std::size_t head = head_.load(std::memory_order_relaxed);
    if (head - tail_.load(std::memory_order_acquire) >= capacity_) return false;
    Slot& slot = storage_[head & mask_];
    new (&slot.storage) T(std::forward<U>(value));
    head_.store(head + 1, std::memory_order_release);
    return true;
  }

  const std::size_t capacity_;
  const std::size_t mask_;
  std::unique_ptr<Slot[]> storage_;
  alignas(64) std::atomic<std::size_t> head_{0};
  alignas(64) std::atomic<std::size_t> tail_{0};
};

}  // namespace nodrix
