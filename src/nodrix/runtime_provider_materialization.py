from __future__ import annotations

from typing import Any

from .errors import RuntimeGraphError
from .provider_validation import (
    validate_provider_parameters,
)
from .providers import (
    load_provider_application,
    load_provider_resource,
    provider_for_application,
    provider_for_resource,
)
from .runtime_components import (
    LoadedApplication,
    LoadedResource,
)
from .runtime_primitives import (
    RuntimeApplicationBinding,
    RuntimeResourceBinding,
)


def _construct_provider(
    provider_class: type[Any],
    parameters: dict[str, Any],
) -> Any:
    """Construct a provider using the existing provider ABI.

    The positional-to-keyword TypeError retry is intentionally preserved
    during the runtime architecture migration for behavioral parity.
    """

    try:
        return provider_class(
            parameters
        )
    except TypeError:
        return provider_class(
            parameters=parameters
        )


def materialize_runtime_resource(
    name: str,
    binding: RuntimeResourceBinding,
) -> LoadedResource:
    """Resolve, validate, instantiate, and wrap one runtime resource."""

    resolved = provider_for_resource(
        binding.uses,
        include_legacy=False,
    )

    if resolved is None:
        raise RuntimeGraphError(
            f"Unknown provider resource {binding.uses!r}"
        )

    _candidate, descriptor = resolved

    parameters = dict(
        binding.parameters
    )

    validate_provider_parameters(
        descriptor.parameters_schema,
        parameters,
        location=(
            f"resources.{name}.parameters"
        ),
    )

    provider_class = load_provider_resource(
        binding.uses
    )

    if provider_class is None:
        raise RuntimeGraphError(
            f"Unknown provider resource {binding.uses!r}"
        )

    instance = _construct_provider(
        provider_class,
        parameters,
    )

    return LoadedResource(
        name=name,
        uses=binding.uses,
        instance=instance,
        binding=binding,
    )


def materialize_runtime_application(
    name: str,
    binding: RuntimeApplicationBinding,
) -> LoadedApplication:
    """Resolve, validate, instantiate, and wrap one managed application."""

    resolved = provider_for_application(
        binding.uses,
        include_legacy=False,
    )

    if resolved is None:
        raise RuntimeGraphError(
            f"Unknown provider application {binding.uses!r}"
        )

    _candidate, descriptor = resolved

    parameters = dict(
        binding.parameters
    )

    validate_provider_parameters(
        descriptor.parameters_schema,
        parameters,
        location=(
            f"applications.{name}.parameters"
        ),
    )

    provider_class = load_provider_application(
        binding.uses
    )

    if provider_class is None:
        raise RuntimeGraphError(
            f"Unknown provider application {binding.uses!r}"
        )

    instance = _construct_provider(
        provider_class,
        parameters,
    )

    for method_name in (
        "configure",
        "start",
        "stop",
        "health",
    ):
        if not callable(
            getattr(
                instance,
                method_name,
                None,
            )
        ):
            raise RuntimeGraphError(
                f"Provider application {binding.uses!r} "
                f"has no callable {method_name}()"
            )

    return LoadedApplication(
        name=name,
        uses=binding.uses,
        instance=instance,
        binding=binding,
    )


__all__ = [
    "materialize_runtime_application",
    "materialize_runtime_resource",
]
