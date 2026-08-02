from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

import yaml


_PRIMITIVES: dict[str, tuple[str, str, str, int]] = {
    "int8": ("b", "int", "std::int8_t", 1),
    "uint8": ("B", "int", "std::uint8_t", 1),
    "int16": ("h", "int", "std::int16_t", 2),
    "uint16": ("H", "int", "std::uint16_t", 2),
    "int32": ("i", "int", "std::int32_t", 4),
    "uint32": ("I", "int", "std::uint32_t", 4),
    "int64": ("q", "int", "std::int64_t", 8),
    "uint64": ("Q", "int", "std::uint64_t", 8),
    "float32": ("f", "float", "float", 4),
    "float64": ("d", "float", "double", 8),
}
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)(?:\[([1-9][0-9]*)\])?$")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    primitive: str
    count: int

    @property
    def format(self) -> str:
        return f"{self.count if self.count > 1 else ''}{_PRIMITIVES[self.primitive][0]}"

    @property
    def python_type(self) -> str:
        scalar = _PRIMITIVES[self.primitive][1]
        return scalar if self.count == 1 else f"tuple[{scalar}, ...]"

    @property
    def cpp_type(self) -> str:
        scalar = _PRIMITIVES[self.primitive][2]
        return scalar if self.count == 1 else f"std::array<{scalar}, {self.count}>"

    @property
    def nbytes(self) -> int:
        return _PRIMITIVES[self.primitive][3] * self.count


@dataclass(frozen=True, slots=True)
class TypeSchema:
    name: str
    version: int
    class_name: str
    fields: tuple[FieldSpec, ...]
    description: str = ""

    @property
    def struct_format(self) -> str:
        return "<" + "".join(field.format for field in self.fields)

    @property
    def nbytes(self) -> int:
        return sum(field.nbytes for field in self.fields)


def _class_name(type_name: str) -> str:
    base = type_name.split(".")[-1]
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_-]+", base) if part)


def load_type_schema(path: str | Path) -> TypeSchema:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Type schema must be a YAML object")
    name = str(raw.get("name", ""))
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid type name: {name!r}")
    version = int(raw.get("version", 1))
    if version < 1:
        raise ValueError("Type version must be >= 1")
    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, dict) or not fields_raw:
        raise ValueError("Type schema requires a non-empty fields mapping")
    fields: list[FieldSpec] = []
    for field_name, definition in fields_raw.items():
        if not _IDENTIFIER_RE.fullmatch(str(field_name)):
            raise ValueError(f"Invalid field name: {field_name!r}")
        match = _FIELD_RE.fullmatch(str(definition))
        if not match or match.group(1) not in _PRIMITIVES:
            supported = ", ".join(_PRIMITIVES)
            raise ValueError(f"Unsupported field type {definition!r}; supported primitives: {supported}")
        fields.append(FieldSpec(str(field_name), match.group(1), int(match.group(2) or 1)))
    return TypeSchema(
        name=name,
        version=version,
        class_name=str(raw.get("class_name") or _class_name(name)),
        fields=tuple(fields),
        description=str(raw.get("description", "")),
    )


def _python_source(schema: TypeSchema) -> str:
    declarations = "\n".join(f"    {field.name}: {field.python_type}" for field in schema.fields)
    checks = []
    flatten = []
    rebuild = []
    offset = 0
    for field in schema.fields:
        if field.count > 1:
            checks.append(
                f'        if len(self.{field.name}) != {field.count}:\n'
                f'            raise ValueError("{field.name} must contain {field.count} values")'
            )
            flatten.append(f"        values.extend(self.{field.name})")
            rebuild.append(f'            "{field.name}": tuple(values[{offset}:{offset + field.count}]),')
        else:
            flatten.append(f"        values.append(self.{field.name})")
            rebuild.append(f'            "{field.name}": values[{offset}],')
        offset += field.count
    checks_text = "\n".join(checks) or "        pass"
    flatten_text = "\n".join(flatten)
    rebuild_text = "\n".join(rebuild)
    return f'''from __future__ import annotations

from dataclasses import dataclass
import struct

from plyctl import register_message_type, register_wire_codec

TYPE_NAME = {schema.name!r}
TYPE_VERSION = {schema.version}
_STRUCT = struct.Struct({schema.struct_format!r})


@dataclass(slots=True)
class {schema.class_name}:
{declarations}

    def __post_init__(self) -> None:
{checks_text}

    def to_bytes(self) -> bytes:
        values = []
{flatten_text}
        return _STRUCT.pack(*values)

    @classmethod
    def from_bytes(cls, data) -> "{schema.class_name}":
        if len(data) != _STRUCT.size:
            raise ValueError(f"{{TYPE_NAME}} expects {{_STRUCT.size}} bytes, got {{len(data)}}")
        values = _STRUCT.unpack(data)
        return cls(**{{
{rebuild_text}
        }})


def _wire_encode(value: {schema.class_name}):
    encoded = value.to_bytes()
    return {{"version": TYPE_VERSION}}, (memoryview(encoded),)


def _wire_decode(payload, metadata):
    if int(metadata.get("version", TYPE_VERSION)) != TYPE_VERSION:
        raise ValueError(f"Unsupported {{TYPE_NAME}} schema version")
    return {schema.class_name}.from_bytes(payload)


def register() -> None:
    register_message_type(
        TYPE_NAME,
        {schema.class_name},
        description={schema.description!r},
        version=TYPE_VERSION,
        compatible_versions=(TYPE_VERSION,),
        replace=True,
    )
    register_wire_codec(TYPE_NAME, _wire_encode, _wire_decode)


register()
'''


def _cpp_source(schema: TypeSchema) -> str:
    fields = "\n".join(f"  {field.cpp_type} {field.name};" for field in schema.fields)
    includes = "#include <array>\n" if any(field.count > 1 for field in schema.fields) else ""
    return f'''#pragma once

{includes}#include <cstddef>
#include <cstdint>
#include <string_view>
#include <type_traits>

namespace nodrix::types {{

#pragma pack(push, 1)
struct {schema.class_name} final {{
{fields}
}};
#pragma pack(pop)

inline constexpr std::string_view k{schema.class_name}TypeName = {json.dumps(schema.name)};
inline constexpr std::uint32_t k{schema.class_name}Version = {schema.version};
static_assert(std::is_standard_layout_v<{schema.class_name}>);
static_assert(sizeof({schema.class_name}) == {schema.nbytes});

}}  // namespace nodrix::types
'''


def generate_type(schema_path: str | Path, output_dir: str | Path) -> dict[str, Path]:
    schema = load_type_schema(schema_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", schema.name).lower()
    python_path = output / f"{stem}.py"
    cpp_path = output / f"{stem}.hpp"
    manifest_path = output / f"{stem}.schema.json"
    python_path.write_text(_python_source(schema), encoding="utf-8")
    cpp_path.write_text(_cpp_source(schema), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "name": schema.name,
                "version": schema.version,
                "class_name": schema.class_name,
                "wire_format": schema.struct_format,
                "wire_size": schema.nbytes,
                "fields": [
                    {"name": field.name, "type": field.primitive, "count": field.count}
                    for field in schema.fields
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    init_path = output / "__init__.py"
    module = python_path.stem
    export_line = f"from .{module} import {schema.class_name}\n"
    existing = init_path.read_text(encoding="utf-8") if init_path.exists() else ""
    if export_line not in existing:
        init_path.write_text(existing + export_line, encoding="utf-8")
    return {"python": python_path, "cpp": cpp_path, "schema": manifest_path, "init": init_path}
