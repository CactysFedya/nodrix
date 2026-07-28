# Nodrix 0.6.0

Версия добавляет отдельный низколатентный `nodrix-viewer`, тип
`vision.encoded_frame`, JPEG encoder/decoder и индивидуальный QoS для каждого
сетевого подписчика.

Главная схема:

```text
Camera raw Frame
├── local zero-copy → Detector
└── JPEG encoder → named stream → Nodrix Viewer
```

Поддерживаются имя stream, `nodrix://` URI, номер камеры, `/dev/video*`,
локальный файл, RTSP и HTTP/MJPEG.

Проверено 27 автоматическими тестами, включая полный сетевой путь JPEG publisher
→ Nodrix stream → headless viewer.

Подробности: `docs/RELEASE_0.6.0.md`.
