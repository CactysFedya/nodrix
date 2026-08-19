"""Persistent operational identity and filesystem layout for Nodrix Runs.

This module owns the live filesystem session that exists before execution
starts.  It deliberately does not replace the canonical immutable RunRecord.

Lifecycle:

    PlanRecord
        -> RunSession / Run directory
        -> actual Execution
        -> terminal ExecutionRecord
        -> immutable RunRecord
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Callable
from uuid import uuid4

from nodrix.model import PlanRecord


RUN_SESSION_SCHEMA = "nodrix.run-session/v1"

RUN_LAYOUT_SCHEMA_V1 = "nodrix.run-layout/v1"
RUN_LAYOUT_SCHEMA = "nodrix.run-layout/v2"

SUPPORTED_RUN_LAYOUT_SCHEMAS = (
    RUN_LAYOUT_SCHEMA_V1,
    RUN_LAYOUT_SCHEMA,
)

_RUN_ID_RE = re.compile(
    r"^run_[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)
_TOKEN_RE = re.compile(r"^[0-9a-f]{12}$")

Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_token() -> str:
    return uuid4().hex[:12]


def _utc_datetime(
    value: datetime,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} must be a datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return value.astimezone(timezone.utc)


def _iso_timestamp(value: datetime) -> str:
    return (
        value.isoformat(
            timespec="microseconds"
        )
        .replace("+00:00", "Z")
    )


def _validate_run_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(
            "run_id must be a string"
        )

    normalized = value.strip()

    if not _RUN_ID_RE.fullmatch(
        normalized
    ):
        raise ValueError(
            "run_id must start with 'run_' and "
            "contain only letters, digits, '.', "
            "'_' or '-'"
        )

    return normalized


def _validate_token(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(
            "Run ID token must be a string"
        )

    normalized = value.strip().lower()

    if not _TOKEN_RE.fullmatch(
        normalized
    ):
        raise ValueError(
            "Run ID token must contain exactly "
            "12 hexadecimal characters"
        )

    return normalized


def generate_run_id(
    created_at: datetime,
    *,
    token: str,
) -> str:
    """Generate one sortable, collision-resistant Run identifier."""

    created_at = _utc_datetime(
        created_at,
        field_name="created_at",
    )
    token = _validate_token(token)

    timestamp = created_at.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    return (
        f"run_{timestamp}_{token}"
    )


@dataclass(frozen=True, slots=True)
class RunSession:
    """Immutable header of one persistent Run filesystem session."""

    run_id: str
    created_at: datetime
    plan_id: str
    plan_kind: str
    operation_kind: str
    subject: str
    subject_revision: str
    directory: Path

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "run_id",
            _validate_run_id(
                self.run_id
            ),
        )

        object.__setattr__(
            self,
            "created_at",
            _utc_datetime(
                self.created_at,
                field_name="created_at",
            ),
        )

        if not isinstance(
            self.directory,
            Path,
        ):
            object.__setattr__(
                self,
                "directory",
                Path(self.directory),
            )

    @property
    def session_path(self) -> Path:
        return (
            self.directory
            / "session.json"
        )

    @property
    def readme_path(self) -> Path:
        return (
            self.directory
            / "README.md"
        )

    @property
    def logs_path(self) -> Path:
        return (
            self.directory
            / "logs"
        )

    @property
    def metrics_path(self) -> Path:
        """Return the optional canonical Metrics directory."""

        return (
            self.directory
            / "metrics"
        )

    def document(self) -> dict[str, object]:
        """Return the stable JSON session header."""

        return {
            "schema": RUN_SESSION_SCHEMA,
            "layout": RUN_LAYOUT_SCHEMA,
            "run_id": self.run_id,
            "created_at": _iso_timestamp(
                self.created_at
            ),
            "plan": {
                "id": self.plan_id,
                "kind": self.plan_kind,
            },
            "operation": {
                "kind": self.operation_kind,
                "subject": self.subject,
                "subject_revision": (
                    self.subject_revision
                ),
            },
            "documentation": "README.md",
        }


def render_run_readme(
    session: RunSession,
) -> str:
    """Render the bilingual self-describing Nodrix Run layout."""

    created_at = _iso_timestamp(
        session.created_at
    )

    return f"""# Nodrix Run

Run ID: `{session.run_id}`<br>
Created: `{created_at}`<br>
Layout standard: `{RUN_LAYOUT_SCHEMA}`<br>
Session schema: `{RUN_SESSION_SCHEMA}`

## English

This directory contains the persistent record of one Nodrix execution attempt.
It is created before the execution backend starts.

Some files appear only later in the Run lifecycle. Their absence is normal
while the Run is still starting/running, or when execution stopped before that
stage was reached.

| Path | Purpose |
| --- | --- |
| `README.md` | This bilingual description of the Nodrix Run layout. |
| `session.json` | Immutable Run session header: Run ID, creation time and exact Plan identity. Created before execution starts. |
| `definition.json` | Immutable canonical Definition snapshot whose revision is the exact System revision referenced by the Run Plan. |
| `plan.json` | Immutable exact resolved Plan snapshot, including effective parameters, placement, bindings, nested Systems and execution topology. |
| `policy.json` | Immutable effective ExecutionPolicy provenance for this Run. Literal redaction secret values are never persisted. |
| `status.json` | Current live status snapshot. Replaced atomically for fast reads and recoverable from durable Run history; it is not immutable historical evidence. |
| `events.jsonl` | Append-only ordered Run event stream. Each record contains Run ID, sequence number and one versioned domain event. Existing events are never rewritten. |
| `environment.json` | Immutable minimal runtime-environment provenance. Process environment variables are captured only from an explicit allowlist and pass through redaction. |
| `logs/` | Optional bounded diagnostic JSONL logs. Disabled by default; category/level filters, byte quotas and redaction apply. Log failures never control execution. |
| `metrics/records.jsonl` | Optional append-only canonical typed Metric observations for this Run. This is distinct from legacy runtime snapshot telemetry. |
| `metrics/status.json` | Optional Metric-loss evidence. Created when bounded Metric storage drops observations and records the loss explicitly. |
| `run.json` | Immutable final canonical Run record. Published only after a terminal `ExecutionRecord` exists and never overwritten. |

### File semantics

- `session.json`, `definition.json`, `plan.json`, `policy.json` and final `run.json` are historical evidence and must not be silently rewritten.
- `events.jsonl` is append-only.
- `status.json` is live operational state and may change while execution is active.
- `logs/` may grow while the Run is active.
- `metrics/records.jsonl` is optional and append-only when canonical Metrics are published.
- Missing lifecycle files do not by themselves mean that the Run directory is invalid.

## Русский

Этот каталог содержит постоянную запись одной попытки выполнения Nodrix.
Он создаётся до запуска execution backend.

Некоторые файлы появляются только на следующих стадиях жизненного цикла Run.
Их отсутствие нормально, пока Run запускается или выполняется, а также если
execution завершился до достижения соответствующей стадии.

| Путь | Назначение |
| --- | --- |
| `README.md` | Это двуязычное описание стандартной структуры Run Nodrix. |
| `session.json` | Неизменяемый заголовок Run: Run ID, время создания и идентичность точного Plan. Создаётся до начала execution. |
| `definition.json` | Неизменяемый снимок канонического Definition; его revision точно совпадает с ревизией System, на которую ссылается Plan данного Run. |
| `plan.json` | Неизменяемый точный снимок resolved Plan, включая эффективные параметры, placement, bindings, вложенные Systems и execution topology. |
| `policy.json` | Неизменяемый снимок effective ExecutionPolicy данного Run. Literal secret values из redaction policy никогда не сохраняются. |
| `status.json` | Текущий снимок состояния Run. Атомарно заменяется для быстрого чтения и может быть восстановлен из постоянной истории Run; сам по себе не является неизменяемой исторической записью. |
| `events.jsonl` | Упорядоченный журнал событий Run только для добавления. Каждая запись содержит Run ID, номер последовательности и одно версионированное событие execution domain. Уже записанные события не переписываются. |
| `environment.json` | Неизменяемый минимальный снимок runtime-окружения. Переменные окружения процесса сохраняются только по явному allowlist и проходят redaction. |
| `logs/` | Опциональные ограниченные диагностические JSONL-логи. По умолчанию отключены; применяются фильтры category/level, byte quotas и redaction. Ошибки логирования не управляют execution. |
| `metrics/records.jsonl` | Опциональные канонические typed Metric observations данного Run в append-only журнале. Этот журнал отделён от legacy runtime snapshot telemetry. |
| `metrics/status.json` | Опциональная запись о потере Metrics. Создаётся, когда bounded Metric storage отбрасывает observations, чтобы потеря данных была явной. |
| `run.json` | Неизменяемая итоговая каноническая запись Run. Публикуется только после появления terminal `ExecutionRecord` и никогда не перезаписывается. |

### Семантика файлов

- `session.json`, `definition.json`, `plan.json`, `policy.json` и финальный `run.json` являются историческими данными и не должны молча переписываться.
- `events.jsonl` работает только на добавление.
- `status.json` является текущим operational state и может изменяться во время работы.
- `logs/` может пополняться во время выполнения.
- `metrics/records.jsonl` является опциональным append-only журналом canonical Metrics.
- Отсутствие файлов более поздних стадий само по себе не означает повреждение Run.

Generated by Nodrix. Do not use mutable Run files as canonical history after
`run.json` has been finalized.
"""


def _write_new_json(
    path: Path,
    document: dict[str, object],
) -> None:
    with path.open(
        "x",
        encoding="utf-8",
    ) as stream:
        json.dump(
            document,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")


def _write_new_text(
    path: Path,
    content: str,
) -> None:
    with path.open(
        "x",
        encoding="utf-8",
    ) as stream:
        stream.write(content)


class RunStore:
    """Filesystem owner for persistent Nodrix Run sessions."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Clock = _utc_now,
        token_factory: TokenFactory = _default_token,
    ) -> None:
        self.root = Path(
            root
        ).expanduser()
        self.clock = clock
        self.token_factory = (
            token_factory
        )

        if not callable(self.clock):
            raise TypeError(
                "clock must be callable"
            )

        if not callable(
            self.token_factory
        ):
            raise TypeError(
                "token_factory must be callable"
            )

    def _created_at(self) -> datetime:
        return _utc_datetime(
            self.clock(),
            field_name="clock result",
        )

    def _allocate_directory(
        self,
        created_at: datetime,
        *,
        run_id: str | None,
    ) -> tuple[str, Path]:
        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        if run_id is not None:
            candidate = _validate_run_id(
                run_id
            )
            directory = (
                self.root
                / candidate
            )

            directory.mkdir(
                exist_ok=False
            )

            return (
                candidate,
                directory,
            )

        for _ in range(8):
            candidate = generate_run_id(
                created_at,
                token=self.token_factory(),
            )
            directory = (
                self.root
                / candidate
            )

            try:
                directory.mkdir(
                    exist_ok=False
                )
            except FileExistsError:
                continue

            return (
                candidate,
                directory,
            )

        raise FileExistsError(
            "cannot allocate a unique Run directory "
            "after 8 attempts"
        )

    def create(
        self,
        plan: PlanRecord,
        *,
        run_id: str | None = None,
    ) -> RunSession:
        """Create a durable Run session before actual execution starts."""

        if not isinstance(
            plan,
            PlanRecord,
        ):
            raise TypeError(
                "plan must be a PlanRecord"
            )

        created_at = (
            self._created_at()
        )

        (
            allocated_run_id,
            directory,
        ) = self._allocate_directory(
            created_at,
            run_id=run_id,
        )

        session = RunSession(
            run_id=allocated_run_id,
            created_at=created_at,
            plan_id=plan.plan_id,
            plan_kind=plan.kind_name,
            operation_kind=(
                plan.operation.kind_name
            ),
            subject=(
                plan.subject.canonical
            ),
            subject_revision=(
                plan.subject_revision.canonical
            ),
            directory=directory,
        )

        try:
            session.logs_path.mkdir()

            _write_new_json(
                session.session_path,
                session.document(),
            )

            _write_new_text(
                session.readme_path,
                render_run_readme(
                    session
                ),
            )
        except Exception:
            # A Run must not start from a partially initialized persistent
            # session.  If the durable header cannot be created, fail before
            # execution and remove the incomplete allocation.
            shutil.rmtree(
                directory,
                ignore_errors=True,
            )
            raise

        return session


__all__ = [
    "RUN_LAYOUT_SCHEMA",
    "RUN_LAYOUT_SCHEMA_V1",
    "SUPPORTED_RUN_LAYOUT_SCHEMAS",
    "RUN_SESSION_SCHEMA",
    "RunSession",
    "RunStore",
    "generate_run_id",
    "render_run_readme",
]
