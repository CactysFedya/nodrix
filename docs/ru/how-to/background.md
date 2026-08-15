# Фоновый запуск

## Запуск

```bash
plyctl prepare
plyctl up [PIPELINE]
```

`--profile` временно переопределяет runtime profile, `--force` следует применять только для осознанной замены stale supervisor state.

## Состояние и мониторинг

```bash
plyctl ps
plyctl top
```

Supervisor state находится в `.nodrix/supervisor.json`.

## Логи

```bash
plyctl logs -n 200
plyctl logs -f
```

Объединённый stdout/stderr находится в `.nodrix/logs/runtime.log`.

## Перезапуск и остановка

```bash
plyctl restart [PIPELINE]
plyctl down --timeout 10
```

Остановка применяется ко всей process group. После таймаута сигналы усиливаются от `SIGINT` до `SIGTERM` и `SIGKILL`.
