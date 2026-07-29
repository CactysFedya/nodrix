# Networking

Отдельный agent запускать не требуется.

Publisher:

```bash
nodrix run
```

Subscriber:

```bash
nodrix stream list
nodrix stream echo /camera/front
```

Discovery использует multicast только для имён, типов и endpoint. Данные идут
напрямую между runtime-процессами.

Если multicast заблокирован:

```text
nodrix://192.168.1.50:7420/camera/front
```


## Видеопросмотр

```bash
nodrix stream list
nodrix-viewer /camera/front/preview --fps 30
```

Viewer запрашивает индивидуальный QoS `latest:1`, поэтому медленный экран не блокирует publisher.
