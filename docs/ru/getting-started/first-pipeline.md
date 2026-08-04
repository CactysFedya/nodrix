# Первый pipeline

Создайте `pipelines/demo.yaml`:

```yaml
apiVersion: plyctl.dev/v2
kind: Pipeline
metadata:
  name: demo
runtime:
  mode: offline
  engine: unified
  type_validation: first
nodes:
  source:
    uses: core.synthetic_source
    parameters: {count: 5}
  delay:
    uses: core.delay
    parameters: {milliseconds: 2}
  console:
    uses: sink.console
edges:
  - from: source.output
    to: delay.input
    queue: {capacity: 8, policy: block}
  - from: delay.output
    to: console.input
    queue: {capacity: 8, policy: block}
streams: {exports: []}
fragments: {}
recording: {}
security: {}
placement: {}
```

Проверьте alias в `nodrix.yaml`:

```yaml
pipelines:
  demo: pipelines/demo.yaml
```

## Проверка до запуска

```bash
plyctl validate demo
plyctl inspect demo
plyctl plan demo
```

- `validate` проверяет структуру manifest, ссылки на узлы, порты и ограничения графа;
- `inspect` показывает разрешённые компоненты и связи;
- `plan` объясняет план выполнения и памяти.

## Запуск в терминале

```bash
plyctl run demo
```

Во время разработки это предпочтительный режим: вывод виден сразу, а `Ctrl+C` инициирует штатное завершение.

## Фоновый запуск

```bash
plyctl up demo
plyctl ps
plyctl logs -f
plyctl down
```

Supervisor хранит состояние в `.nodrix/supervisor.json`, а общий stdout/stderr — в `.nodrix/logs/runtime.log`.

## Политики очередей

Для lossless offline-пути используйте `block`. Для real-time preview, где важен только свежий кадр:

```yaml
queue:
  capacity: 1
  policy: latest
```

Не используйте `latest` на пути записи данных.
