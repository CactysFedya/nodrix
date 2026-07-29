from setuptools import Extension, setup

setup(
    name="nodrix-frame-mean-native",
    version="0.1.0",
    ext_modules=[
        Extension(
            "_frame_mean_native",
            ["native_backend.cpp"],
            language="c++",
            extra_compile_args=["-O3", "-std=c++20", "-DNDEBUG"],
        )
    ],
)
