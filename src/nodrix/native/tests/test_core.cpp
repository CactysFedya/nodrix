#include <cassert>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

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

  constexpr std::uint64_t concurrent_messages = 100'000;
  nodrix::SpscQueue<std::uint64_t> concurrent_spsc(1024);
  std::atomic<std::uint64_t> spsc_sum{0};
  std::thread spsc_producer([&] {
    for (std::uint64_t value = 1;
         value <= concurrent_messages;
         ++value) {
      while (!concurrent_spsc.try_push(value)) {
        std::this_thread::yield();
      }
    }
  });
  std::thread spsc_consumer([&] {
    for (std::uint64_t count = 0;
         count < concurrent_messages;) {
      std::uint64_t value = 0;
      if (concurrent_spsc.try_pop(value)) {
        spsc_sum.fetch_add(value, std::memory_order_relaxed);
        ++count;
      } else {
        std::this_thread::yield();
      }
    }
  });
  spsc_producer.join();
  spsc_consumer.join();
  assert(
      spsc_sum.load(std::memory_order_relaxed) ==
      concurrent_messages * (concurrent_messages + 1) / 2);

  constexpr std::uint64_t producer_count = 2;
  constexpr std::uint64_t per_producer = 50'000;
  constexpr std::uint64_t total_mpmc =
      producer_count * per_producer;
  nodrix::MpmcQueue<nodrix::Message> concurrent_mpmc(1024);
  std::atomic<std::uint64_t> consumed{0};
  std::atomic<std::uint64_t> mpmc_sum{0};
  std::vector<std::thread> workers;
  for (std::uint64_t producer = 0;
       producer < producer_count;
       ++producer) {
    workers.emplace_back([&, producer] {
      for (std::uint64_t index = 1;
           index <= per_producer;
           ++index) {
        nodrix::Message item;
        item.sequence = producer * per_producer + index;
        while (!concurrent_mpmc.try_push(std::move(item))) {
          std::this_thread::yield();
        }
      }
    });
  }
  for (std::uint64_t consumer = 0; consumer < 2; ++consumer) {
    workers.emplace_back([&] {
      while (consumed.load(std::memory_order_acquire) <
             total_mpmc) {
        nodrix::Message item;
        if (concurrent_mpmc.try_pop(item)) {
          mpmc_sum.fetch_add(
              item.sequence, std::memory_order_relaxed);
          consumed.fetch_add(1, std::memory_order_release);
        } else {
          std::this_thread::yield();
        }
      }
    });
  }
  for (auto& worker : workers) worker.join();
  assert(consumed.load(std::memory_order_relaxed) == total_mpmc);
  assert(
      mpmc_sum.load(std::memory_order_relaxed) ==
      total_mpmc * (total_mpmc + 1) / 2);

#if !defined(_WIN32)
  const std::string name = "/nodrix_test_" + std::to_string(static_cast<long long>(::getpid()));
  auto owner = nodrix::SharedMemoryRegion::create(name, 4096);
  auto peer = nodrix::SharedMemoryRegion::open(name, 4096);
  std::memset(owner.data(), 0x7B, owner.size());
  assert(static_cast<const unsigned char*>(peer.data())[100] == 0x7B);
#endif

  return 0;
}
