# Nodrix 1.0.1: полный путь от проекта до production-запуска

## 1. Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install nodrix-1.0.1.tar.gz
nodrix --version
```

Для Raspberry Pi и Linux ARM64 устанавливайте исходный `tar.gz`, чтобы нативные расширения собрали оптимальный код под текущую архитектуру.

## 2. Создание проекта

Пустой проект:

```bash
nodrix init my_project
```

Он содержит структуру, но не демонстрационную реализацию. Рабочий пример создаётся явно:

```bash
nodrix init vision_app --template vision
nodrix init media_app --template media
nodrix init device_app --template device
```

## 3. Реализация узла

```python
from nodrix import Message, Node

class Detector(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"detections": "vision.detections"}

    def configure(self, context):
        super().configure(context)
        self.model = load_model()

    def process(self, inputs):
        frame_message = inputs["frame"]
        detections = run_model(frame_message.payload)
        return {
            "detections": frame_message.with_updates(
                type="vision.detections",
                payload=detections,
            )
        }
```

Старые методы `open`, `flush`, `close` также поддерживаются.

## 4. Произвольный pipeline

Трекер не обязателен:

```yaml
nodes:
  camera:
    uses: media.ffmpeg_source
    parameters:
      uri: rtsp://192.168.1.20/live

  detector:
    uses: ./nodes/detector.py:Detector

  preview:
    uses: media.ffmpeg_encoder
    parameters:
      codec: h264
      encoder: libx264

edges:
  - from: camera.frame
    to: detector.frame
    queue: {capacity: 1, policy: latest}

  - from: camera.frame
    to: preview.frame
    queue: {capacity: 1, policy: latest}
```

Один output может иметь несколько независимых веток.

## 5. Защищённый поток на ноутбук

```yaml
streams:
  bind_host: 0.0.0.0
  exports:
    - name: /camera/front/h264
      from: preview.encoded
      queue: {capacity: 1, policy: latest}
      access:
        mode: token
        token_env: NODRIX_STREAM_TOKEN
        allow_ips: ["192.168.1.0/24"]
```

На устройстве:

```bash
export NODRIX_STREAM_TOKEN='случайный-длинный-токен'
nodrix run
```

На ноутбуке:

```bash
export NODRIX_STREAM_TOKEN='случайный-длинный-токен'
nodrix stream list
nodrix-viewer /camera/front/h264
```

Viewer хранит только последний кадр и не создаёт очередь старого видео.

## 6. Проверка перед запуском

```bash
nodrix validate --strict
nodrix inspect --memory
```

Исправьте ошибки типов, памяти, циклов, открытых streams и небезопасных watchdog-настроек.

## 7. Фиксация окружения

```bash
nodrix lock
nodrix lock --check
```

После изменения модели, кода, `.so`, конфигурации или типа проверка покажет расхождение.

## 8. Production-запуск

```bash
nodrix run --locked --metrics-listen 127.0.0.1:9464
```

Метрики доступны по адресу `/metrics`, JSON — `/metrics.json`.

## 9. Health и диагностика

В другом терминале:

```bash
nodrix status
nodrix health --watch
nodrix metrics --format prometheus
```

Для потенциально нестабильной модели:

```yaml
execution:
  isolation: process
failure:
  policy: restart
  max_restarts: 3
health:
  timeout_ms: 2000
  on_timeout: restart
resources:
  memory_limit_mb: 2048
  max_message_bytes: 67108864
```

## 10. Артефакты

```bash
nodrix runs list
nodrix runs show <run-id>
nodrix runs logs <run-id>
nodrix runs compare <run-a> <run-b>
```

В каталоге запуска сохраняются manifest, lock, окружение, метрики, ошибки, outputs и итоговый summary.

## 11. Создание пакета узлов

```bash
nodrix init cobra-perception --template package
cd cobra-perception
```

Опишите узлы в `nodrix.package.yaml`, затем:

```bash
nodrix package build .
nodrix package install dist/cobra-perception-1.0.0.ndpkg
```

В pipeline:

```yaml
nodes:
  detector:
    uses: cobra-perception/detector
```

## 12. C++ plugin

```bash
nodrix node create tracker --language cpp
cmake -S nodes/tracker -B nodes/tracker/build -DCMAKE_BUILD_TYPE=Release
cmake --build nodes/tracker/build --parallel
nodrix native inspect nodes/tracker/build/libtracker.so
```

Plugin должен показывать ABI 1.0 и совместимость `yes`.

## 13. Запись и воспроизведение

```bash
nodrix record /camera/front/h264 /detector/detections --output experiment.ndrx --duration 60
nodrix recording info experiment.ndrx
nodrix play experiment.ndrx --as-fast-as-possible
```

## 14. Рекомендуемая архитектура для робота

```text
Camera/LiDAR source
├── локальный zero-copy → inference
├── shared memory → изолированный тяжёлый узел
├── encoder → защищённый LAN stream → laptop viewer
└── recorder → .ndrx
```

Сетевой Viewer, recorder и detector должны иметь независимые очереди. Для realtime-preview используйте `latest`, для критичной записи — `block` с рассчитанной ёмкостью.
