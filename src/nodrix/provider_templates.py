"""Safe installation of metadata-owned provider project templates."""

from __future__ import annotations

from pathlib import Path
import shutil
import stat
from typing import Any, Callable

from .errors import ProviderError
from .manifest_schema import write_manifest_schema
from .provider_loading import provider_for_template
from .provider_verification import verify_candidate


_EDITOR_SETTINGS = """\
{
  "yaml.schemas": {
    ".plyctl-schema.json": [
      "pipeline.yaml",
      "pipelines/*.yaml"
    ]
  }
}
"""


def create_provider_project(
    directory: str | Path,
    template_id: str,
    *,
    force: bool = False,
    _resolver: Callable[..., Any] = provider_for_template,
    _verifier: Callable[..., Any] = verify_candidate,
) -> list[Path]:
    """Copy a provider-owned project template without importing its package."""

    resolved = _resolver(template_id, include_legacy=False)
    if resolved is None:
        raise ProviderError(
            f"Provider template {template_id!r} is not installed"
        )
    candidate, descriptor = resolved
    verification = _verifier(candidate)
    if verification.errors:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: "
            + "; ".join(verification.errors)
        )
    if candidate.metadata_path is None:
        raise ProviderError(
            f"Provider {candidate.id!r} has no template resource location"
        )
    relative = Path(descriptor.source)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProviderError(
            f"Provider template {template_id!r} has an unsafe source path"
        )
    package_root = candidate.metadata_path.parent.resolve()
    source = (package_root / relative).resolve()
    if package_root != source and package_root not in source.parents:
        raise ProviderError(
            f"Provider template {template_id!r} escapes its package"
        )
    if not source.is_dir() or source.is_symlink():
        raise ProviderError(
            f"Provider template {template_id!r} is not a regular directory"
        )

    target_root = Path(directory).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ProviderError(
                f"Provider template {template_id!r} contains a symbolic "
                f"link: {item.relative_to(source)}"
            )
        relative_item = item.relative_to(source)
        target = target_root / relative_item
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            resolved_target = target.resolve()
            if (
                resolved_target != target_root
                and target_root not in resolved_target.parents
            ):
                raise ProviderError(
                    "Provider template target escapes through a symbolic "
                    f"link: {target}"
                )
            continue
        if not item.is_file():
            raise ProviderError(
                f"Provider template {template_id!r} contains a non-file entry"
            )
        if target.is_symlink():
            raise ProviderError(
                "Refusing to write a provider template through a symbolic "
                f"link: {target}"
            )
        if target.exists() and not force:
            raise FileExistsError(
                f"Refusing to overwrite existing template file: {target}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = target.parent.resolve()
        if (
            resolved_parent != target_root
            and target_root not in resolved_parent.parents
        ):
            raise ProviderError(
                "Provider template target escapes through a symbolic link: "
                f"{target.parent}"
            )
        shutil.copyfile(item, target)
        source_mode = item.stat().st_mode
        target.chmod(0o755 if source_mode & stat.S_IXUSR else 0o644)
        created.append(target)

    schema_path = target_root / ".plyctl-schema.json"
    if force or not schema_path.exists():
        write_manifest_schema(schema_path)
    settings_path = target_root / ".vscode" / "settings.json"
    if not settings_path.exists():
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(_EDITOR_SETTINGS, encoding="utf-8")
    return created


__all__ = ["create_provider_project"]
