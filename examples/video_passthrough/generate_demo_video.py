from pathlib import Path

import cv2
import numpy as np


out = Path(__file__).with_name("input.mp4")
writer = cv2.VideoWriter(
    str(out),
    cv2.VideoWriter_fourcc(*"mp4v"),
    30.0,
    (320, 180),
)
if not writer.isOpened():
    raise RuntimeError(f"Cannot create {out}")

for i in range(60):
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    x = 10 + (i * 4) % 240
    cv2.rectangle(frame, (x, 50), (x + 60, 120), (255, 255, 255), -1)
    cv2.putText(frame, f"frame {i}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    writer.write(frame)

writer.release()
print(out)
