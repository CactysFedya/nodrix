from __future__ import annotations

import threading
import time

from nodrix import viewer
from nodrix.viewer import OpenCVReader


class _BlockingCapture:
    def __init__(self) -> None:
        self.read_started = threading.Event()
        self.allow_read_finish = threading.Event()
        self.release_called = threading.Event()
        self.release_during_read = False
        self._reading = False

    def isOpened(self) -> bool:
        return True

    def set(self, _prop: int, _value: float) -> bool:
        return True

    def get(self, _prop: int) -> float:
        return 30.0

    def read(self):
        self._reading = True
        self.read_started.set()
        assert self.allow_read_finish.wait(timeout=2.0)
        self._reading = False
        return False, None

    def release(self) -> None:
        if self._reading:
            self.release_during_read = True
        self.release_called.set()


def test_opencv_reader_releases_capture_after_read_finishes(monkeypatch) -> None:
    capture = _BlockingCapture()
    monkeypatch.setattr(viewer.cv2, "VideoCapture", lambda *_args, **_kwargs: capture)

    reader = OpenCVReader("0", realtime=False)
    reader.start()
    assert capture.read_started.wait(timeout=1.0)

    closer = threading.Thread(target=reader.close)
    closer.start()
    time.sleep(0.05)

    assert not capture.release_called.is_set()

    capture.allow_read_finish.set()
    closer.join(timeout=2.0)

    assert not closer.is_alive()
    assert capture.release_called.wait(timeout=1.0)
    assert not capture.release_during_read
    assert reader.capture is None
