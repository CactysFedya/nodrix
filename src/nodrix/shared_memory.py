from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
from multiprocessing.shared_memory import SharedMemory
import sys
import threading
from typing import Any
import uuid

from .cv_types import ManagedBuffer, MemoryType


_MAX_PORTABLE_SHM_NAME = 27


def _portable_shared_memory_name(name: str | None) -> str | None:
    """Return a shared-memory name portable across Linux and macOS."""
    if name is None:
        return None

    cleaned = "".join(
        character
        if character.isalnum() or character in {"-", "_"}
        else "-"
        for character in str(name).lstrip("/")
    )

    if len(cleaned) <= _MAX_PORTABLE_SHM_NAME:
        return cleaned

    digest = hashlib.blake2s(
        cleaned.encode("utf-8"),
        digest_size=6,
    ).hexdigest()

    prefix_length = _MAX_PORTABLE_SHM_NAME - len(digest) - 1
    return cleaned[:prefix_length] + "-" + digest


def _open_shared_memory(
    *,
    name: str | None = None,
    create: bool = False,
    size: int = 0,
) -> SharedMemory:
    """Open shared memory on Python 3.11+.

    The track parameter was added in Python 3.13. Plyctl manages the
    lifetime of its shared-memory segments explicitly, so tracking is
    disabled when the interpreter supports that option.
    """
    kwargs: dict[str, Any] = {
        "name": _portable_shared_memory_name(name),
        "create": create,
        "size": size,
    }
    if sys.version_info >= (3, 13):
        kwargs["track"] = False
    return SharedMemory(**kwargs)


@dataclass(frozen=True, slots=True)
class SharedBufferDescriptor:
    name: str
    size: int
    offset: int = 0
    readonly: bool = True
    generation: int = 0


class SharedMemoryLease:
    """Keeps a shared-memory mapping alive and optionally returns a pool block."""

    __slots__ = ("shm", "descriptor", "_pool", "_block", "_released")

    def __init__(
        self,
        shm: SharedMemory,
        descriptor: SharedBufferDescriptor,
        *,
        pool: "SharedBufferPool | None" = None,
        block: int | None = None,
    ) -> None:
        self.shm = shm
        self.descriptor = descriptor
        self._pool = pool
        self._block = block
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._pool is not None and self._block is not None:
            self._pool._release(self._block)
            return
        try:
            self.shm.close()
        except BufferError:
            # A NumPy/memoryview consumer still owns a view. The mapping will be
            # closed when the process exits; the name may already be unlinked.
            pass

    def __del__(self) -> None:  # pragma: no cover - GC timing is implementation-specific
        self.release()


class SharedBufferPool:
    """Preallocated fixed-block POSIX shared-memory pool.

    The pool creates one segment and returns offset-based blocks. A buffer that
    is already backed by this pool can cross a process boundary by descriptor
    only; no payload copy is required.
    """

    def __init__(
        self,
        block_size: int,
        capacity: int = 8,
        *,
        name: str | None = None,
        alignment: int = 64,
    ) -> None:
        if block_size <= 0 or capacity <= 0:
            raise ValueError("block_size and capacity must be positive")
        self.block_size = int(block_size)
        self.capacity = int(capacity)
        self.alignment = int(alignment)
        self.name = _portable_shared_memory_name(name or ("nodrix-" + uuid.uuid4().hex))
        self._shm = _open_shared_memory(name=self.name, create=True, size=self.block_size * self.capacity)
        self.name = self._shm.name
        self._condition = threading.Condition()
        self._free = deque(range(self.capacity))
        self._generation = [0] * self.capacity
        self._closed = False
        self._acquires = 0
        self._reuses = 0
        self._waits = 0
        self._peak_in_use = 0

    def acquire(self, size: int | None = None, *, readonly: bool = False, block: bool = True) -> ManagedBuffer:
        requested = self.block_size if size is None else int(size)
        if requested <= 0 or requested > self.block_size:
            raise ValueError(f"requested size must be within 1..{self.block_size}")
        with self._condition:
            while not self._free and not self._closed:
                if not block:
                    raise BufferError("Plyctl shared buffer pool is exhausted")
                self._waits += 1
                self._condition.wait()
            if self._closed:
                raise RuntimeError("Plyctl shared buffer pool is closed")
            index = self._free.popleft()
            self._generation[index] += 1
            self._acquires += 1
            if self._acquires > self.capacity:
                self._reuses += 1
            self._peak_in_use = max(self._peak_in_use, self.capacity - len(self._free))
        offset = index * self.block_size
        descriptor = SharedBufferDescriptor(
            name=self.name,
            size=requested,
            offset=offset,
            readonly=readonly,
            generation=self._generation[index],
        )
        lease = SharedMemoryLease(self._shm, descriptor, pool=self, block=index)
        return ManagedBuffer(
            owner=self._shm.buf[offset : offset + requested],
            readonly=readonly,
            memory_type=MemoryType.SHARED,
            device="shm",
            offset=0,
            length=requested,
            lease=lease,
        )

    def _release(self, index: int) -> None:
        with self._condition:
            if self._closed:
                return
            if index not in self._free:
                self._free.append(index)
                self._condition.notify()

    def stats(self) -> dict[str, int | str]:
        with self._condition:
            return {
                "name": self.name,
                "block_size": self.block_size,
                "capacity": self.capacity,
                "available": len(self._free),
                "in_use": self.capacity - len(self._free),
                "peak_in_use": self._peak_in_use,
                "acquires": self._acquires,
                "reuses": self._reuses,
                "waits": self._waits,
            }

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        try:
            self._shm.close()
        except BufferError:
            pass
        try:
            self._shm.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "SharedBufferPool":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - GC timing is implementation-specific
        try:
            self.close()
        except Exception:
            pass


class OneShotSharedBuffer:
    """One message-sized segment used for process outputs and oversized inputs."""

    def __init__(self, size: int, *, readonly: bool = False) -> None:
        self.shm = _open_shared_memory(create=True, size=size)
        self.descriptor = SharedBufferDescriptor(self.shm.name, size, 0, readonly, 1)
        self.lease = SharedMemoryLease(self.shm, self.descriptor)

    def buffer(self) -> ManagedBuffer:
        return ManagedBuffer(
            owner=self.shm.buf[: self.descriptor.size],
            readonly=self.descriptor.readonly,
            memory_type=MemoryType.SHARED,
            device="shm",
            offset=0,
            length=self.descriptor.size,
            lease=self.lease,
        )

    def unlink(self) -> None:
        try:
            self.shm.unlink()
        except FileNotFoundError:
            pass


def descriptor_for_buffer(buffer: ManagedBuffer) -> SharedBufferDescriptor | None:
    descriptor = getattr(buffer, "_descriptor_hint", None)
    lease = getattr(buffer, "lease", None)
    if descriptor is None:
        descriptor = getattr(lease, "descriptor", None)
    if descriptor is None:
        descriptor = getattr(getattr(buffer, "_shared_resource", None), "descriptor", None)
    if buffer.memory_type == MemoryType.SHARED and isinstance(descriptor, SharedBufferDescriptor):
        return SharedBufferDescriptor(
            name=descriptor.name,
            size=buffer.nbytes,
            offset=descriptor.offset + buffer.offset,
            readonly=buffer.readonly,
            generation=descriptor.generation,
        )
    return None


def open_shared_buffer(descriptor: SharedBufferDescriptor, *, unlink: bool = False) -> ManagedBuffer:
    shm = _open_shared_memory(name=descriptor.name, create=False)
    if unlink:
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
    lease = SharedMemoryLease(shm, descriptor)
    return ManagedBuffer(
        owner=shm.buf[descriptor.offset : descriptor.offset + descriptor.size],
        readonly=descriptor.readonly,
        memory_type=MemoryType.SHARED,
        device="shm",
        offset=0,
        length=descriptor.size,
        lease=lease,
    )
