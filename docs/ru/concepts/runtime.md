# Runtime и data plane

Plyctl разделяет управление графом и transport сообщений, поддерживая Python/native nodes, provider resources и внешние applications.

## Элементы

- **Node** — обработчик с типизированными ports.
- **Edge** — связь с queue и memory policy.
- **Message** — immutable envelope с type, payload, sequence, timestamps, correlation и metadata.
- **Resource/session** — pipeline-scoped объект provider.
- **Managed application** — внешний процесс под управлением runtime.

## Lifecycle

```text
configure/open → start → process/produce → drain/flush → stop/close
```

Новые lifecycle-методы адаптируются к старым `open`, `flush`, `close`, сохраняя совместимость 2.x.

## Backpressure

- `block` — lossless, producer ждёт;
- `drop_oldest` — ограниченный поток, удаляется старый item;
- `latest` — сохраняется только самое свежее значение.

Policy выбирается для каждого пути отдельно.

## Memory

Runtime планирует Python memory, managed buffers, shared memory и native paths. Payload внутри `Message` удерживается по ссылке; после emission его нельзя изменять без явного контракта типа.

## External middleware

Plyctl не обязан переносить каждый ROS 2 message в Python-граф. Point clouds и IMU могут оставаться в DDS, а Plyctl управляет lifecycle, health, logs и metrics.
