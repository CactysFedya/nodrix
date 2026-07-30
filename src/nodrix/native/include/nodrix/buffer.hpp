#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <new>
#include <stdexcept>
#include <utility>

namespace nodrix {

class Buffer final {
 public:
  using Deleter = void (*)(void*, std::size_t, void*) noexcept;

  Buffer() noexcept = default;

  static Buffer allocate(std::size_t size, std::size_t alignment = 64) {
    if (size == 0) return {};
    if (alignment < alignof(void*)) alignment = alignof(void*);
    void* data = nullptr;
#if defined(_WIN32)
    data = _aligned_malloc(size, alignment);
    if (data == nullptr) throw std::bad_alloc{};
    auto deleter = +[](void* ptr, std::size_t, void*) noexcept { _aligned_free(ptr); };
#else
    if (::posix_memalign(&data, alignment, size) != 0) throw std::bad_alloc{};
    auto deleter = +[](void* ptr, std::size_t, void*) noexcept { std::free(ptr); };
#endif
    return Buffer(new ControlBlock(data, size, deleter, nullptr));
  }

  static Buffer wrap(void* data, std::size_t size, Deleter deleter, void* context = nullptr) {
    if (data == nullptr || size == 0) return {};
    if (deleter == nullptr) throw std::invalid_argument("Buffer::wrap requires a deleter");
    return Buffer(new ControlBlock(data, size, deleter, context));
  }

  Buffer(const Buffer& other) noexcept : control_(other.control_) { retain(); }
  Buffer(Buffer&& other) noexcept : control_(std::exchange(other.control_, nullptr)) {}

  Buffer& operator=(const Buffer& other) noexcept {
    if (this == &other) return *this;
    release();
    control_ = other.control_;
    retain();
    return *this;
  }

  Buffer& operator=(Buffer&& other) noexcept {
    if (this == &other) return *this;
    release();
    control_ = std::exchange(other.control_, nullptr);
    return *this;
  }

  ~Buffer() { release(); }

  [[nodiscard]] std::byte* data() noexcept {
    return control_ ? static_cast<std::byte*>(control_->data) : nullptr;
  }
  [[nodiscard]] const std::byte* data() const noexcept {
    return control_ ? static_cast<const std::byte*>(control_->data) : nullptr;
  }
  [[nodiscard]] std::size_t size() const noexcept { return control_ ? control_->size : 0; }
  [[nodiscard]] bool empty() const noexcept { return size() == 0; }
  [[nodiscard]] explicit operator bool() const noexcept { return control_ != nullptr; }
  [[nodiscard]] std::uint32_t use_count() const noexcept {
    return control_ ? control_->references.load(std::memory_order_relaxed) : 0;
  }
  [[nodiscard]] void* owner_handle() const noexcept { return control_; }

  /*
   * C ABI bridge helpers. owner_handle() is opaque outside this class. A
   * plugin that stores a buffer after process() returns calls retain_owner()
   * and must eventually call release_owner().
   */
  static void retain_owner(void* opaque) noexcept {
    auto* control = static_cast<ControlBlock*>(opaque);
    if (control) {
      control->references.fetch_add(1, std::memory_order_relaxed);
    }
  }

  static void release_owner(void* opaque) noexcept {
    release_control(static_cast<ControlBlock*>(opaque));
  }

 private:
  struct alignas(64) ControlBlock {
    ControlBlock(void* ptr, std::size_t bytes, Deleter fn, void* ctx) noexcept
        : data(ptr), size(bytes), deleter(fn), context(ctx) {}

    std::atomic<std::uint32_t> references{1};
    void* data;
    std::size_t size;
    Deleter deleter;
    void* context;
  };

  explicit Buffer(ControlBlock* control) noexcept : control_(control) {}

  void retain() noexcept {
    if (control_) control_->references.fetch_add(1, std::memory_order_relaxed);
  }

  void release() noexcept {
    ControlBlock* control = std::exchange(control_, nullptr);
    release_control(control);
  }

  static void release_control(ControlBlock* control) noexcept {
    if (control == nullptr) return;
    if (control->references.fetch_sub(1, std::memory_order_acq_rel) == 1) {
      control->deleter(control->data, control->size, control->context);
      delete control;
    }
  }

  ControlBlock* control_{nullptr};
};

}  // namespace nodrix
