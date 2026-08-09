from __future__ import annotations

import os

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class BuildExt(build_ext):
    """Portable C++20 build with opt-in host-specific optimization."""

    def build_extensions(self) -> None:
        for extension in self.extensions:
            if self.compiler.compiler_type == "msvc":
                extension.extra_compile_args.extend(
                    ["/O2", "/std:c++20", "/DNDEBUG"]
                )
            else:
                extension.extra_compile_args.extend(
                    ["-O3", "-std=c++20", "-DNDEBUG", "-fvisibility=hidden"]
                )

                # Never bake host-specific ISA into distributable wheels unless
                # the builder explicitly asks for it.
                if os.environ.get(
                    "NODRIX_MAPPING_NATIVE_ARCH_NATIVE", "0"
                ) == "1":
                    extension.extra_compile_args.append("-march=native")

                # LTO is useful on the Pi production build but is deliberately
                # opt-in for developer portability (Apple Clang/MSVC/toolchains).
                if os.environ.get(
                    "NODRIX_MAPPING_NATIVE_LTO", "0"
                ) == "1":
                    extension.extra_compile_args.append("-flto")
                    extension.extra_link_args.append("-flto")

        super().build_extensions()


setup(
    ext_modules=[
        Extension(
            "nodrix_mapping._mapping_native",
            ["src/nodrix_mapping/native/mapping_native.cpp"],
            language="c++",
        )
    ],
    cmdclass={"build_ext": BuildExt},
)
