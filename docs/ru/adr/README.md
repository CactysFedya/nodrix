# Architecture Decision Records

ADR защищают принципы продукта от случайного архитектурного дрейфа. ADR нужен
для изменения identity продукта, границ Core, схем, совместимости, безопасности,
владения lifecycle, transport или формата artifacts.

Каждый ADR фиксирует:

- статус и дату;
- контекст и ограничения;
- рассмотренные варианты;
- принятое решение;
- влияние на совместимость и migration;
- влияние на производительность и безопасность;
- validation evidence.

Локальная деталь реализации не требует ADR, пока она не меняет публичный или
архитектурный контракт.

## Принятые решения

- [ADR-0001: Lifecycle, хранение и recovery для Run](0001-run-lifecycle-persistence-recovery.md)
- [ADR-0002: Канонический контракт Operation, planning и execution](0002-canonical-operation-planning-execution.md)
- [ADR-0003: Execution и Run policy](0003-execution-run-policy.md)
- [ADR-0004: Каноническое foreground-выполнение Operation](0004-canonical-foreground-operation-execution.md)
