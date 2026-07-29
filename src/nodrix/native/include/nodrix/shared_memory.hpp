#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>

#if defined(_WIN32)
#error "SharedMemoryRegion currently supports POSIX platforms"
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace nodrix {

class SharedMemoryRegion final {
 public:
  static SharedMemoryRegion create(std::string name, std::size_t size) {
    if (name.empty() || name.front() != '/') name.insert(name.begin(), '/');
    const int fd = ::shm_open(name.c_str(), O_CREAT | O_EXCL | O_RDWR, 0600);
    if (fd < 0) throw std::runtime_error("shm_open(create) failed");
    if (::ftruncate(fd, static_cast<off_t>(size)) != 0) {
      ::close(fd);
      ::shm_unlink(name.c_str());
      throw std::runtime_error("ftruncate failed");
    }
    void* data = ::mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (data == MAP_FAILED) {
      ::close(fd);
      ::shm_unlink(name.c_str());
      throw std::runtime_error("mmap failed");
    }
    return SharedMemoryRegion(std::move(name), fd, data, size, true);
  }

  static SharedMemoryRegion open(std::string name, std::size_t size) {
    if (name.empty() || name.front() != '/') name.insert(name.begin(), '/');
    const int fd = ::shm_open(name.c_str(), O_RDWR, 0600);
    if (fd < 0) throw std::runtime_error("shm_open(open) failed");
    void* data = ::mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (data == MAP_FAILED) {
      ::close(fd);
      throw std::runtime_error("mmap failed");
    }
    return SharedMemoryRegion(std::move(name), fd, data, size, false);
  }

  SharedMemoryRegion() noexcept = default;
  SharedMemoryRegion(const SharedMemoryRegion&) = delete;
  SharedMemoryRegion& operator=(const SharedMemoryRegion&) = delete;
  SharedMemoryRegion(SharedMemoryRegion&& other) noexcept { *this = std::move(other); }
  SharedMemoryRegion& operator=(SharedMemoryRegion&& other) noexcept {
    if (this == &other) return *this;
    reset();
    name_ = std::move(other.name_);
    fd_ = std::exchange(other.fd_, -1);
    data_ = std::exchange(other.data_, nullptr);
    size_ = std::exchange(other.size_, 0);
    owner_ = std::exchange(other.owner_, false);
    return *this;
  }
  ~SharedMemoryRegion() { reset(); }

  [[nodiscard]] void* data() noexcept { return data_; }
  [[nodiscard]] const void* data() const noexcept { return data_; }
  [[nodiscard]] std::size_t size() const noexcept { return size_; }
  [[nodiscard]] const std::string& name() const noexcept { return name_; }

 private:
  SharedMemoryRegion(std::string name, int fd, void* data, std::size_t size, bool owner)
      : name_(std::move(name)), fd_(fd), data_(data), size_(size), owner_(owner) {}

  void reset() noexcept {
    if (data_) ::munmap(data_, size_);
    if (fd_ >= 0) ::close(fd_);
    if (owner_ && !name_.empty()) ::shm_unlink(name_.c_str());
    data_ = nullptr;
    fd_ = -1;
    size_ = 0;
    owner_ = false;
  }

  std::string name_;
  int fd_{-1};
  void* data_{nullptr};
  std::size_t size_{0};
  bool owner_{false};
};

}  // namespace nodrix
