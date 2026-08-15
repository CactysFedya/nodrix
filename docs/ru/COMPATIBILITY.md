# Политика совместимости линии 2.x

Plyctl — публичный CLI и Python-дистрибутив. Nodrix остаётся названием
экосистемы, репозитория, compatibility import и исторических on-disk форматов.

## Сохраняется в 2.3.0b1

- Команда и distribution `plyctl`.
- Compatibility import и CLI alias `nodrix`.
- Manifest aliases, поддерживаемые migration layer 2.x.
- Существующие `.nodrix/` state и run directories.
- Записи `.ndrx` и native ABI names в рамках политики 2.x.
- Совместимость Provider API 1 при предпочтительном Provider API 2.

## Что нельзя переносить между платформами

Virtual environment, native wheel, build directory и compiled plugin являются
платформенными артефактами. Сборка macOS не переносится на Linux ARM64.
Переносится source с lock-файлами либо квалифицированные target wheels.

## Ломающие изменения

Изменение CLI, manifest, provider, ABI, wire или artifact contract требует:

1. ADR;
2. migration path;
3. периода deprecation, когда он практически возможен;
4. compatibility tests;
5. явных release notes.
