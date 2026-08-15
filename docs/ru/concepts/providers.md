# Provider и границы расширения

Provider — независимый пакет интеграции, который объявляет capabilities до импорта Python-реализации.

Metadata позволяет проверить:

- id/version provider;
- Provider API;
- диапазон совместимых версий runtime;
- required features;
- node IDs, factories, ports, schemas;
- resources, sessions, applications, probes, external links;
- подпись и trust policy.

## Provider APIs 1 и 2

API 1 покрывает исходную модель nodes/probes. API 2 добавляет transport-neutral resources, managed applications, richer external links и feature negotiation.

Для новых provider:

```text
schema: plyctl-provider/2
entry point: plyctl.providers
provider_api: "2"
```

`nodrix-provider/*` и `nodrix.providers` поддерживаются в 2.x.

## Что выбирать

- Local Python class — один проект и быстрые изменения.
- Provider — переиспользуемый Python package.
- Native plugin — измеренный hot path или native library.
- Managed application — готовый executable, ROS launch, driver или service.
