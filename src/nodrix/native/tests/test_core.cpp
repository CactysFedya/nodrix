#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>

#include "nodrix/buffer.hpp"
#include "nodrix/device_memory.hpp"
#include "nodrix/message.hpp"
#include "nodrix/mpmc_queue.hpp"
#include "nodrix/spsc_queue.hpp"
#if !defined(_WIN32)
#include "nodrix/shared_memory.hpp"
#include <unistd.h>
#endif

int main() {
  static_assert(nodrix::memory_domain_name(nodrix::MemoryDomain::dma_buf) == "dma_buf");
  nodrix::DeviceBufferDescriptor descriptor;
  descriptor.domain = nodrix::MemoryDomain::cuda;
  descriptor.device_index = 0;
  descriptor.size = 4096;
  assert(descriptor.size == 4096);

  auto buffer = nodrix::Buffer::allocate(4096);
  assert(buffer.size() == 4096);
  std::memset(buffer.data(), 0x2A, buffer.size());
  {
    auto copy = buffer;
    assert(copy.data() == buffer.data());
    assert(buffer.use_count() == 2);
  }
  assert(buffer.use_count() == 1);

  nodrix::SpscQueue<nodrix::Message> queue(8);
  nodrix::Message message;
  message.sequence = 42;
  message.payload = buffer;
  assert(queue.try_push(message));
  nodrix::Message output;
  assert(queue.try_pop(output));
  assert(output.sequence == 42);
  assert(output.payload.data() == buffer.data());

  nodrix::MpmcQueue<nodrix::Message> overwrite_queue(8);
  for (std::uint64_t i = 0; i < 8; ++i) {
    nodrix::Message item;
    item.sequence = i;
    assert(overwrite_queue.try_push(std::move(item)));
  }
  nodrix::Message rejected;
  rejected.sequence = 99;
  assert(!overwrite_queue.try_push(std::move(rejected)));
  nodrix::Message oldest;
  assert(overwrite_queue.try_pop(oldest));
  assert(oldest.sequence == 0);

#if !defined(_WIN32)
  const std::string name = "/nodrix_test_" + std::to_string(static_cast<long long>(::getpid()));
  auto owner = nodrix::SharedMemoryRegion::create(name, 4096);
  auto peer = nodrix::SharedMemoryRegion::open(name, 4096);
  std::memset(owner.data(), 0x7B, owner.size());
  assert(static_cast<const unsigned char*>(peer.data())[100] == 0x7B);
#endif

  return 0;
}
