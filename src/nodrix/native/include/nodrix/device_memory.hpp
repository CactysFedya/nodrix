#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>

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
  external,
};

struct DmaBufPlane {
  int fd{-1};
  std::uint64_t offset{0};
  std::uint64_t length{0};
  std::uint32_t stride{0};
  std::uint32_t bytes_used{0};
};

struct DeviceBufferDescriptor {
  MemoryDomain domain{MemoryDomain::cpu};
  std::uint32_t device_index{0};
  std::uint64_t size{0};
  std::uint64_t offset{0};
  std::array<std::byte, 64> opaque_handle{};
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
    case MemoryDomain::external: return "external";
  }
  return "unknown";
}

}  // namespace nodrix
