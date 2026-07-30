from __future__ import annotations


from .cv_types import ManagedBuffer, MemoryType

try:
    from ._native_buffer import BufferPool as NativeBufferPool, NativeBuffer
except Exception:  # pragma: no cover - extension is built during installation
    NativeBufferPool = None
    NativeBuffer = None


class BufferPool:
    """Aligned reusable native memory pool with a pure-Python compatibility path."""

    def __init__(self, block_size: int, max_cached: int = 32, alignment: int = 64) -> None:
        if block_size <= 0:
            raise ValueError("block_size must be positive")
        self.block_size = int(block_size)
        self.max_cached = int(max_cached)
        self.alignment = int(alignment)
        self._native = (
            NativeBufferPool(self.block_size, self.max_cached, self.alignment)
            if NativeBufferPool is not None
            else None
        )
        self._fallback_allocations = 0

    @property
    def native(self) -> bool:
        return self._native is not None

    def acquire(self, size: int | None = None, *, readonly: bool = False) -> ManagedBuffer:
        requested = self.block_size if size is None else int(size)
        if requested <= 0:
            raise ValueError("size must be positive")
        if self._native is not None:
            value = self._native.acquire(size=requested, readonly=readonly)
        else:
            value = bytearray(requested)
            self._fallback_allocations += 1
        return ManagedBuffer(
            owner=value,
            readonly=readonly,
            memory_type=MemoryType.CPU,
            device="cpu",
        )

    def stats(self) -> dict[str, int | bool]:
        if self._native is not None:
            return {"native": True, **dict(self._native.stats())}
        return {
            "native": False,
            "block_size": self.block_size,
            "allocations": self._fallback_allocations,
            "reuses": 0,
        }
