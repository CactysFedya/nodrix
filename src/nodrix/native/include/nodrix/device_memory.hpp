#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <utility>

namespace nodrix {

enum class MemoryDomain : std::uint8_t {
  cpu,
  pinned_cpu,
  shared,
  dma_buf,
  cuda,
  rocm,
  vulkan,
  opencl,
  metal,
  npu,
  dlpack,
  external = 255,
};

struct DmaBufPlane {
  int fd{-1};
  std::uint64_t offset{0};
  std::uint64_t length{0};
  std::uint32_t stride{0};
  std::uint32_t bytes_used{0};
};

struct DeviceBufferDescriptor {
  using Retain = void (*)(void*);
  using Release = void (*)(void*);

  MemoryDomain domain{MemoryDomain::cpu};
  std::uint64_t device_index{0};
  std::uint64_t handle{0};
  std::uint64_t size{0};
  std::uint64_t offset{0};
  std::uint64_t flags{0};
  void* owner{nullptr};
  Retain retain{nullptr};
  Release release{nullptr};

  DeviceBufferDescriptor() noexcept = default;
  DeviceBufferDescriptor(const DeviceBufferDescriptor& other) noexcept
      : domain(other.domain),
        device_index(other.device_index),
        handle(other.handle),
        size(other.size),
        offset(other.offset),
        flags(other.flags),
        owner(other.owner),
        retain(other.retain),
        release(other.release) {
    if (owner && retain) retain(owner);
  }
  DeviceBufferDescriptor(DeviceBufferDescriptor&& other) noexcept
      : domain(other.domain),
        device_index(other.device_index),
        handle(other.handle),
        size(other.size),
        offset(other.offset),
        flags(other.flags),
        owner(std::exchange(other.owner, nullptr)),
        retain(other.retain),
        release(other.release) {}
  DeviceBufferDescriptor& operator=(
      const DeviceBufferDescriptor& other) noexcept {
    if (this == &other) return *this;
    reset();
    domain = other.domain;
    device_index = other.device_index;
    handle = other.handle;
    size = other.size;
    offset = other.offset;
    flags = other.flags;
    owner = other.owner;
    retain = other.retain;
    release = other.release;
    if (owner && retain) retain(owner);
    return *this;
  }
  DeviceBufferDescriptor& operator=(DeviceBufferDescriptor&& other) noexcept {
    if (this == &other) return *this;
    reset();
    domain = other.domain;
    device_index = other.device_index;
    handle = other.handle;
    size = other.size;
    offset = other.offset;
    flags = other.flags;
    owner = std::exchange(other.owner, nullptr);
    retain = other.retain;
    release = other.release;
    return *this;
  }
  ~DeviceBufferDescriptor() { reset(); }

  void reset() noexcept {
    void* value = std::exchange(owner, nullptr);
    if (value && release) release(value);
  }
};

constexpr std::string_view memory_domain_name(MemoryDomain domain) noexcept {
  switch (domain) {
    case MemoryDomain::cpu: return "cpu";
    case MemoryDomain::pinned_cpu: return "pinned_cpu";
    case MemoryDomain::shared: return "shared";
    case MemoryDomain::dma_buf: return "dma_buf";
    case MemoryDomain::cuda: return "cuda";
    case MemoryDomain::rocm: return "rocm";
    case MemoryDomain::vulkan: return "vulkan";
    case MemoryDomain::opencl: return "opencl";
    case MemoryDomain::metal: return "metal";
    case MemoryDomain::npu: return "npu";
    case MemoryDomain::dlpack: return "dlpack";
    case MemoryDomain::external: return "external";
  }
  return "unknown";
}

}  // namespace nodrix
