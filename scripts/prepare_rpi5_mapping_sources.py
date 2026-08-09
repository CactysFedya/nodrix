from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence


DEFAULT_SOURCES = (
    (
        "livox-sdk2",
        "https://github.com/Livox-SDK/Livox-SDK2.git",
        "v1.3.1",
        Path("sources/Livox-SDK2"),
        "NODRIX_LIVOX_SDK2_REF",
    ),
    (
        "livox-driver",
        "https://github.com/Livox-SDK/livox_ros_driver2.git",
        "1.2.6",
        Path("workspaces/livox_ws/src/livox_ros_driver2"),
        "NODRIX_LIVOX_DRIVER_REF",
    ),
    (
        "fast-lio2",
        "https://github.com/Ericsii/FAST_LIO_ROS2.git",
        "ros2",
        Path("workspaces/fast_lio2_ws/src/FAST_LIO_ROS2"),
        "NODRIX_FAST_LIO2_REF",
    ),
)


def _run(argv: Sequence[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _git_sha(path: Path) -> str:
    return _run(("git", "rev-parse", "HEAD"), cwd=path)


def _clone(*, name: str, url: str, ref: str, target: Path, refresh: bool) -> tuple[str, str]:
    if target.exists():
        if not (target / ".git").is_dir():
            raise RuntimeError(
                f"{target} exists but is not a Git repository; "
                "move it away or remove it before prepare"
            )
        if refresh:
            _run(("git", "fetch", "--tags", "--prune", "origin"), cwd=target)
            _run(("git", "checkout", "--detach", ref), cwd=target)
            _run(("git", "submodule", "update", "--init", "--recursive"), cwd=target)
            action = "REFRESHED"
        else:
            action = "REUSED"
        sha = _git_sha(target)
        print(f"{action:<10} {name:<13} {sha[:12]}  {target}")
        return sha, action.lower()

    target.parent.mkdir(parents=True, exist_ok=True)
    _run(
        (
            "git",
            "clone",
            "--recursive",
            "--depth",
            "1",
            "--branch",
            ref,
            url,
            str(target),
        )
    )
    sha = _git_sha(target)
    print(f"{'ACQUIRED':<10} {name:<13} {sha[:12]}  {target}")
    return sha, "acquired"


def _normalize_livox_ros2(source: Path) -> None:
    package_ros2 = source / "package_ROS2.xml"
    launch_ros2 = source / "launch_ROS2"
    if not package_ros2.is_file() or not launch_ros2.is_dir():
        raise RuntimeError(
            "Livox ROS Driver 2 source does not contain package_ROS2.xml "
            "and launch_ROS2; unsupported source layout"
        )

    shutil.copy2(package_ros2, source / "package.xml")
    launch = source / "launch"
    if launch.exists():
        if launch.is_symlink() or not launch.is_dir():
            raise RuntimeError(f"Unsafe Livox launch path: {launch}")
        shutil.rmtree(launch)
    shutil.copytree(launch_ros2, launch)
    print(f"{'NORMALIZED':<10} {'livox-driver':<13} ROS2/Jazzy package layout")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire sources for the Nodrix Raspberry Pi 5 mapping reference system."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly fetch and checkout configured refs in existing repositories.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    records: dict[str, dict[str, str]] = {}
    for name, url, default_ref, relative, env_name in DEFAULT_SOURCES:
        ref = os.environ.get(env_name, default_ref).strip() or default_ref
        target = root / relative
        sha, action = _clone(
            name=name,
            url=url,
            ref=ref,
            target=target,
            refresh=args.refresh,
        )
        records[name] = {
            "url": url,
            "ref": ref,
            "sha": sha,
            "path": relative.as_posix(),
            "action": action,
        }

    _normalize_livox_ros2(root / "workspaces/livox_ws/src/livox_ros_driver2")

    state = root / ".nodrix" / "reference-sources.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {"schema": "nodrix.reference-sources/v1", "sources": records},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{'RECORDED':<10} {'source-lock':<13} {state.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
