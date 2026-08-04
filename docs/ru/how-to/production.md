# Подготовка к production

## Фиксируйте версии

- Зафиксируйте `plyctl==2.3.0a1` или точный commit.
- Храните workspace, manifests, provider packages и hardware configs в Git.
- Сохраняйте `plyctl workspace show --json` вместе с deployment artifacts.

## Проверяйте до запуска

```bash
plyctl env check
plyctl validate
plyctl inspect
plyctl plan
plyctl prepare
```

## Разделяйте semantics путей

- Запись без потерь: `block` и достаточная capacity.
- Preview/control real-time: небольшие очереди `latest` или `drop_oldest` только там, где потеря допустима.
- Большие ROS 2 payload оставляйте в DDS, если Plyctl нужен только для orchestration и health.

## Безопасность extensions

- Metadata-first discovery.
- Allowlist provider.
- Проверка подписей и trust store.
- Process isolation для недоверенного native-кода.

## Эксплуатация

```bash
plyctl up
plyctl ps
plyctl top
plyctl logs -f
plyctl down --timeout 15
```

При incident собирайте `.nodrix/logs/`, resolved workspace, runtime metrics и ROS 2 diagnostics.

## Проверяйте failure modes

- отсутствующий setup script;
- недоступный device/model;
- ошибка import provider;
- crash дочернего процесса;
- shutdown по SIGINT;
- переполнение lossless queue;
- отсутствие ROS topic;
- stale supervisor state после reboot.
