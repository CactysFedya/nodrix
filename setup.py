from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
from setuptools import Extension, setup
from setuptools.command.build_py import build_py

compile_args: list[str] = []
link_args: list[str] = []
if os.name == "nt":
    compile_args.extend(["/O2", "/std:c++20", "/DNDEBUG"])
else:
    compile_args.extend(["-O3", "-std=c++20", "-DNDEBUG", "-fvisibility=hidden"])
    if sys.platform == "darwin":
        compile_args.append("-stdlib=libc++")


class BuildPyWithNativeRunner(build_py):
    """Build the portable standalone runtime into every platform wheel."""

    def run(self) -> None:
        super().run()
        source = Path(__file__).parent / "src" / "nodrix" / "native"
        build_ext_command = self.get_finalized_command("build_ext")
        build = (
            Path(build_ext_command.build_temp) / "nodrix-native-runner"
        )
        configure = [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DNODRIX_BUILD_EXAMPLE_PLUGIN=OFF",
            "-DNODRIX_BUILD_TESTS=OFF",
            "-DNODRIX_NATIVE_LTO=ON",
            "-DNODRIX_NATIVE_MARCH_NATIVE=OFF",
        ]
        architecture_flags = os.environ.get("ARCHFLAGS", "")
        if sys.platform == "darwin" and not architecture_flags:
            architecture_flags = " ".join(
                str(sysconfig.get_config_var(name) or "")
                for name in ("CFLAGS", "LDSHARED")
            )
        architectures = list(
            dict.fromkeys(
                re.findall(
                    r"(?:^|\s)-arch\s+(\S+)",
                    architecture_flags,
                )
            )
        )
        if sys.platform == "darwin" and architectures:
            configure.append(
                "-DCMAKE_OSX_ARCHITECTURES=" + ";".join(architectures)
            )
        subprocess.run(configure, check=True)
        subprocess.run(
            [
                "cmake",
                "--build",
                str(build),
                "--config",
                "Release",
                "--parallel",
                str(max(1, os.cpu_count() or 1)),
            ],
            check=True,
        )
        name = (
            "nodrix-native-runner.exe"
            if os.name == "nt"
            else "nodrix-native-runner"
        )
        candidates = [
            build / name,
            build / "Release" / name,
        ]
        runner = next((path for path in candidates if path.is_file()), None)
        if runner is None:
            raise RuntimeError(
                f"CMake did not produce the packaged native runner: {candidates}"
            )
        destination = Path(self.build_lib) / "nodrix" / "bin" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runner, destination)
        if os.name != "nt":
            destination.chmod(destination.stat().st_mode | 0o755)


setup(
    cmdclass={"build_py": BuildPyWithNativeRunner},
    ext_modules=[
        Extension(
            "nodrix._native_queue",
            ["src/nodrix/native/python/queue_module.cpp"],
            language="c++",
            extra_compile_args=compile_args,
            extra_link_args=link_args,
        ),
        Extension(
            "nodrix._native_buffer",
            ["src/nodrix/native/python/buffer_module.cpp"],
            language="c++",
            extra_compile_args=compile_args,
            extra_link_args=link_args,
        ),
        Extension(
            "nodrix._native_device",
            ["src/nodrix/native/python/device_module.cpp"],
            language="c++",
            extra_compile_args=compile_args,
            extra_link_args=link_args + (["-ldl"] if sys.platform.startswith("linux") else []),
        ),
        Extension(
            "nodrix._native_plugin",
            ["src/nodrix/native/python/plugin_module.cpp"],
            language="c++",
            include_dirs=["src/nodrix/native/include"],
            extra_compile_args=compile_args,
            extra_link_args=link_args + (["-ldl"] if sys.platform.startswith("linux") else []),
        ),
        Extension(
            "nodrix._native_tracking",
            ["src/nodrix/native/python/tracking_module.cpp"],
            language="c++",
            extra_compile_args=compile_args,
            extra_link_args=link_args,
        ),
    ]
)
