"""Small, dependency-free validator for Provider API parameter schemas."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_PYTHON_TYPES: dict[str, tuple[type[Any], ...]] = {
    "object": (dict,),
    "array": (list, tuple),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def validate_provider_parameters(
    schema: Mapping[str, Any] | None,
    value: Mapping[str, Any],
    *,
    location: str,
) -> None:
    """Validate the safe JSON-Schema subset used in provider descriptors.

    Supported keywords are ``type``, ``enum``, ``required``, ``properties``,
    ``additionalProperties``, ``items``, length/item limits and numeric bounds.
    Unknown annotations remain forward-compatible and are ignored.
    """

    if not schema:
        return
    _validate(dict(schema), dict(value), location)


def _validate(schema: Mapping[str, Any], value: Any, location: str) -> None:
    expected = schema.get("type")
    if isinstance(expected, str):
        accepted = _PYTHON_TYPES.get(expected)
        if accepted is not None:
            valid = isinstance(value, accepted)
            if expected in {"integer", "number"} and isinstance(value, bool):
                valid = False
            if not valid:
                raise ValueError(f"{location} must be {expected}")

    enum = schema.get("enum")
    if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes)):
        if value not in enum:
            rendered = ", ".join(repr(item) for item in enum)
            raise ValueError(f"{location} must be one of {rendered}")

    if isinstance(value, Mapping):
        required = schema.get("required") or ()
        if isinstance(required, Sequence) and not isinstance(
            required, (str, bytes)
        ):
            missing = [str(name) for name in required if name not in value]
            if missing:
                raise ValueError(
                    f"{location} is missing required parameters: "
                    + ", ".join(missing)
                )
        properties = schema.get("properties") or {}
        if isinstance(properties, Mapping):
            for name, child_schema in properties.items():
                if name in value and isinstance(child_schema, Mapping):
                    _validate(
                        child_schema,
                        value[name],
                        f"{location}.{name}",
                    )
            if schema.get("additionalProperties") is False:
                unknown = sorted(str(name) for name in value if name not in properties)
                if unknown:
                    raise ValueError(
                        f"{location} contains unknown parameters: "
                        + ", ".join(unknown)
                    )

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                _validate(items, item, f"{location}[{index}]")
        _limit(schema, "minItems", len(value), location, minimum=True)
        _limit(schema, "maxItems", len(value), location, minimum=False)

    if isinstance(value, str):
        _limit(schema, "minLength", len(value), location, minimum=True)
        _limit(schema, "maxLength", len(value), location, minimum=False)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < float(schema["minimum"]):
            raise ValueError(f"{location} must be >= {schema['minimum']}")
        if "maximum" in schema and value > float(schema["maximum"]):
            raise ValueError(f"{location} must be <= {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= float(
            schema["exclusiveMinimum"]
        ):
            raise ValueError(
                f"{location} must be > {schema['exclusiveMinimum']}"
            )
        if "exclusiveMaximum" in schema and value >= float(
            schema["exclusiveMaximum"]
        ):
            raise ValueError(
                f"{location} must be < {schema['exclusiveMaximum']}"
            )


def _limit(
    schema: Mapping[str, Any],
    keyword: str,
    actual: int,
    location: str,
    *,
    minimum: bool,
) -> None:
    if keyword not in schema:
        return
    expected = int(schema[keyword])
    if (minimum and actual < expected) or (not minimum and actual > expected):
        operator = ">=" if minimum else "<="
        raise ValueError(f"{location} length must be {operator} {expected}")


__all__ = ["validate_provider_parameters"]
