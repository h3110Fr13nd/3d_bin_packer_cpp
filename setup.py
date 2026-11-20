# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pybind11",
#     "setuptools",
# ]
# ///
import os
import sys

from setuptools import setup, Extension
import pybind11

if sys.platform == "win32":
    extra_compile_args = ["/O2", "/std:c++17"]
else:
    # -O3 turns on the loop auto-vectoriser used by the packing kernels.
    extra_compile_args = ["-O3", "-std=c++17"]
    # Opt-in: tune for the build machine's SIMD width (AVX2/AVX-512).
    # Not portable across CPUs, so never enable it for distributed wheels.
    if os.environ.get("BINPACK_NATIVE") == "1":
        extra_compile_args.append("-march=native")

ext_modules = [
    Extension(
        'pybinding',
        sources=['src/item.cpp', 'src/pybinding.cpp', 'src/box.cpp', 'src/bin.cpp', 'src/packer.cpp', 'src/utils.cpp', 'src/log.cpp',
                 'src/packing_engine.cpp', 'src/loading_sequence.cpp',
                 'src/bin_planner.cpp', 'src/fleet_planner.cpp'],
        include_dirs=["include", pybind11.get_include()],
        extra_compile_args=extra_compile_args,
        language='c++'
    ),
]

setup(
    name='3d_bin_packer',
    version='0.1',
    author='Dummy Author',
    author_email='dummy-email@xyz.com',
    description='A 3D bin packing library',
    license='MIT',
    ext_modules=ext_modules,
    # Python tooling (reports, validation, pricing, rendering) next to the extension.
    packages=['binpack'],
    package_dir={'': 'src'},
    install_requires=['pybind11>=2.5.0', 'numpy>=1.21'],
    extras_require={'render': ['matplotlib>=3.5']},
)
