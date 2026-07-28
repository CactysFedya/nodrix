# Nodrix 1.1.0: полный путь от проекта до запуска

## 1. Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "nodrix[media,viewer]==1.1.0"
nodrix --version
```

На Raspberry Pi без интернета исходный пакет устанавливается так, если зависимости уже перенесены:

```bash
pip install nodrix-1.1.0.tar.gz --no-build-isolation --no-deps
```

## 2. Создание проекта

Пустой каркас:

```bash
nodrix init my_project
```

Рабочий пример создаётся только по явному шаблону:

```bash
nodrix init vision_app --template vision
nodrix init media_app --template media
nodrix init device_app --template device
```

## 3. Компактный pipeline

```yaml
name: raspberry-rtsp-preview
profile: realtime-low-latency

nodes:
  camera:
    use: media.ffmpeg_source
    uri: ${RTSP_URL}

  encoder:
    use: media.ffmpeg_encoder
    codec: h264
    encoder: auto

flow:
  - camera.frame -> encoder.frame

publish:
  /camera/front/h264:
    from: encoder.encoded
    access: token
```

Компактный manifest разворачивается до canonical-конфигурации до построения графа и не добавляет runtime-overhead.

## 4. Просмотр реально применённых настроек

```bash
nodrix inspect pipeline.yaml --resolved
nodrix config show pipeline.yaml
nodrix config explain nodes.encoder.encoder --pipeline pipeline.yaml
```

Порядок разрешения:

```text
schema defaults
→ runtime profile
→ pipeline.yaml
→ --profile / --set
```

## 5. Разовые переопределения

```bash
nodrix run pipeline.yaml \
  --set nodes.encoder.crf=18 \
  --set nodes.encoder.keyint=30
```

Переопределения сохраняются в resolved manifest текущего запуска. `--locked` намеренно нельзя совмещать с `--profile` или `--set`: lock должен соответствовать точному запускаемому manifest.

## 6. Профили

```bash
nodrix config profiles
```

Доступны:

- `realtime-low-latency` — `latest:1`, минимальная задержка;
- `realtime-balanced` — небольшой буфер и контролируемый drop;
- `lossless-recording` — `block`, запись без потерь;
- `maximum-throughput` — большие очереди для offline;
- `debug` — строгая типизация и частая телеметрия.

Любой edge может переопределить профиль:

```yaml
flow:
  - from: encoder.encoded
    to: writer.frame
    queue:
      capacity: 16
      policy: block
```

## 7. Проверка и запуск

```bash
nodrix validate pipeline.yaml --strict
nodrix inspect pipeline.yaml --memory
nodrix run pipeline.yaml --metrics-listen 0.0.0.0:9464
```

## 8. CPU, память и очереди по узлам

В другом терминале:

```bash
nodrix top --interval 1
```

Также доступны:

```bash
nodrix status
nodrix health --watch
nodrix metrics --format prometheus
```

Для `execution.isolation: process` Nodrix показывает собственные PID, CPU и RSS узла. Для in-process узлов показываются CPU time узла, owned/shared/queue buffers и общий RSS executor — без выдуманного разделения общей памяти.

## 9. Автоматический encoder

```bash
nodrix media select-encoder h264
```

`encoder: auto` выполняет реальный FFmpeg probe и выбирает работающий hardware backend, затем программный fallback.

## 10. Viewer со статистикой publisher

```bash
export NODRIX_STREAM_TOKEN='секрет'
nodrix-viewer /camera/front/h264 --publisher-stats
```

Viewer показывает RX/display FPS, latency, bitrate, subscribers, stream drops, CPU узлов и температуру устройства, если publisher запущен с endpoint метрик на порту 9464.

## 11. Воспроизводимый запуск

```bash
nodrix lock
nodrix lock --check
nodrix run --locked
```

## 12. Артефакты

```bash
nodrix runs list
nodrix runs show <run-id>
nodrix runs logs <run-id>
nodrix runs compare <run-a> <run-b>
```

Каждый запуск содержит source manifest, resolved manifest, lock, status, метрики и итоговый отчёт.
