# Nodrix Viewer

Установка:

```bash
pip install "nodrix[viewer]"
```

Открыть поток по имени:

```bash
nodrix-viewer /camera/front/preview
```

По явному адресу:

```bash
nodrix-viewer nodrix://192.168.1.50:7420/camera/front/preview --fps 30
```

Другие источники:

```bash
nodrix-viewer 0
nodrix-viewer /dev/video0
nodrix-viewer ./video.mp4
nodrix-viewer rtsp://camera/live
```

Viewer использует очередь `latest:1`, постоянно вычитывает stream и не
накапливает старые кадры. Overlay показывает receive/display FPS, sequence,
разрешение, число перезаписанных кадров и задержку при синхронизированных часах.

Клавиши: `Q`/`Esc` — выход, `S` — снимок.

Подробнее: `docs/VIEWER.md`.
