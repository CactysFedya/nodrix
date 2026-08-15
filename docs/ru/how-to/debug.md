# Диагностика pipeline

Используйте порядок, который отделяет static errors от environment и runtime failures.

## 1. Resolution

```bash
plyctl workspace show
plyctl context show
plyctl env show
```

Проверьте alias pipeline, context, setup sources, profile и view.

## 2. Preflight

```bash
plyctl env check
plyctl prepare
```

Ошибка `file` или `command` относится к окружению, а не к графу.

## 3. Graph validation

```bash
plyctl validate [PIPELINE]
plyctl inspect [PIPELINE]
plyctl plan [PIPELINE]
```

Типичные причины:

- неверный `apiVersion`;
- отсутствует обязательный раздел Manifest API v2;
- не найден node/provider;
- неверное имя порта;
- несовместимые типы портов;
- provider требует отсутствующую feature;
- некорректная queue или memory policy.

## 4. Дополнительная диагностика

```bash
plyctl explain [PIPELINE]
plyctl diagnose [PIPELINE]
plyctl device doctor
plyctl data doctor PATH
```

Точные параметры смотрите через `--help`.

## 5. Foreground run

```bash
plyctl run [PIPELINE]
```

Используйте foreground до стабилизации startup.

## 6. Ошибка фонового startup

```bash
plyctl logs -n 300
cat .nodrix/supervisor.json
```
