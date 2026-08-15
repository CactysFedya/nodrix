# Совместимость серии 2.x

## Используйте в новом коде

```text
Plyctl
plyctl
Python facade: plyctl
Manifest API: plyctl.dev/v2
Provider schema: plyctl-provider/2
Entry points: plyctl.providers
```

## Поддерживается в 2.x

```text
Команда и package nodrix
nodrix.dev/v1, nodrix.dev/v2
nodrix-provider/1, nodrix-provider/2
nodrix.providers
nodrix.yaml
.nodrix/
requires_nodrix и другие protocol compatibility fields
```

Не выполняйте массовое переименование стабильных on-disk/protocol identifiers. Новые публичные примеры переводите на Plyctl, а compatibility names сохраняйте там, где они являются контрактом 2.x.
