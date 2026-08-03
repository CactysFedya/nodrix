# Практические инструкции

## Проверить pipeline

```bash
plyctl validate pipeline.yaml
plyctl inspect pipeline.yaml
```

## Запустить с production-проверками

```bash
plyctl validate pipeline.yaml --production
plyctl run pipeline.yaml --production
```

## Проверить провайдеры

```bash
plyctl provider list
plyctl provider verify example.echo
plyctl doctor --provider ros2
plyctl doctor --deep --json
```

## Наблюдать за выполнением

```bash
plyctl top
```

Метрики runtime должны учитывать ресурсы дочерних managed applications, чтобы
отображать фактическую нагрузку всего pipeline.
