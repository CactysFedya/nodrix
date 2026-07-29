from __future__ import annotations

import os
import sys
from setuptools import Extension, setup

compile_args: list[str] = []
link_args: list[str] = []
if os.name == "nt":
    compile_args.extend(["/O2", "/std:c++20", "/DNDEBUG"])
else:
    compile_args.extend(["-O3", "-std=c++20", "-DNDEBUG", "-fvisibility=hidden"])
    if sys.platform == "darwin":
        compile_args.append("-stdlib=libc++")

setup(
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
