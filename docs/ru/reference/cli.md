# Справочник CLI

Основная команда — `plyctl`. `nodrix` остаётся compatibility alias в серии 2.x.

```bash
plyctl --help
plyctl COMMAND --help
```

## Workspace и context

| Команда | Назначение |
|---|---|
| `plyctl workspace init [DIRECTORY] [--force]` | Создать workspace. |
| `plyctl workspace show [--json]` | Показать итоговый resolution. |
| `plyctl context list` | Список contexts. |
| `plyctl context show` | Активный context. |
| `plyctl use NAME` | Сохранить active context. |

## Environment

| Команда | Назначение |
|---|---|
| `plyctl env show [--json]` | Setup scripts и merged variables. |
| `plyctl env export` | Shell exports. |
| `plyctl env check` | Preflight checks. |
| `plyctl prepare` | Resolve + checks + build environment. |
| `plyctl shell` | Интерактивный shell в окружении workspace. |

## Выполнение

| Команда | Назначение |
|---|---|
| `plyctl run [PIPELINE]` | Foreground run. |
| `plyctl up [PIPELINE] [--profile NAME] [--force]` | Background supervisor. |
| `plyctl down [--timeout SECONDS]` | Остановка process group. |
| `plyctl restart [PIPELINE]` | Перезапуск. |
| `plyctl ps` | Статус supervisor. |
| `plyctl logs [-n N] [-f]` | Чтение/follow log. |
| `plyctl top` | Runtime metrics с выбранным view. |

## Graph inspection

| Команда | Назначение |
|---|---|
| `plyctl validate [PIPELINE]` | Manifest, graph, ports, types, provider. |
| `plyctl inspect [PIPELINE]` | Компоненты и связи. |
| `plyctl plan [PIPELINE]` | Execution/memory plan. |
| `plyctl explain [PIPELINE]` | Объяснение resolved behavior. |
| `plyctl diagnose [PIPELINE]` | Структурированная диагностика. |
| `plyctl optimize [PIPELINE]` | Анализ оптимизации. |
| `plyctl benchmark ...` | Benchmark по параметрам команды. |

## Provider и catalog

```bash
plyctl provider list
plyctl provider info PROVIDER_ID
plyctl provider doctor PROVIDER_ID
plyctl catalog ...
```

Подкоманды уточняйте через `--help` в текущем commit.

## Data, device, recording, media

```bash
plyctl data doctor PATH
plyctl device doctor
plyctl device v4l2-probe
plyctl recording info PATH
plyctl recording repair PATH
plyctl media doctor
plyctl media probe INPUT
plyctl media select-encoder h264
plyctl media record ...
```

Часть команд зависит от optional capabilities.

## Наблюдение за выполнением System

`plyctl system run` отображает lifecycle и состояние наблюдения для каждой
System и каждого execution scope. Вложенные System отображаются деревом.
Строка дочерней System сохраняет имя instance и имя разрешённого definition,
например `lidar → livox-mid360` под `rpi5-mapping`.

Lifecycle и observation являются разными понятиями:

- `state` описывает ход выполнения: prepared, running, stopping, stopped,
  completed или failed;
- `ready` принимает значение `yes`, `no` или `unknown`;
- `health` принимает значение `healthy`, `degraded`, `unhealthy` или `unknown`;
- `message` объясняет наиболее важную ошибку, деградацию или неопределённость.

Изменение health или readiness выводится даже тогда, когда lifecycle остаётся
в состоянии `RUNNING`. Если backend не предоставляет observation, CLI выводит
`observation=unavailable`.

Observation является живым состоянием выполнения и не сохраняется как поле
декларативного System YAML.
