# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pybind11",
#     "setuptools",
# ]
# ///
from setuptools import setup, Extension
import pybind11

ext_modules = [
    Extension(
        'pybinding',
        sources=['src/item.cpp', 'src/pybinding.cpp', 'src/box.cpp', 'src/bin.cpp', 'src/packer.cpp', 'src/utils.cpp', 'src/log.cpp'],
        include_dirs=["include", pybind11.get_include()],
        language='c++'
    ),
]

setup(
    name='3d_bin_packer',
    version='0.1',
    author='Vijay Singh Kushwaha',
    author_email='vijaysinghkushwaha3737@gmail.com',
    description='A 3D bin packing library',
    ext_modules=ext_modules,
    install_requires=['pybind11>=2.5.0'],
)
