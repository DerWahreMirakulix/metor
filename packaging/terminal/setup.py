"""Build-time dependency metadata for the Terminal frontend distribution."""

import sys
from pathlib import Path

from setuptools import setup


SOURCE_DIR: Path = Path(__file__).resolve().parents[2] / 'src'
sys.path.insert(0, str(SOURCE_DIR))

from metor.versioning import APP_VERSION  # noqa: E402


setup(
    install_requires=[
        f'metor=={APP_VERSION}',
        f'metor-sdk=={APP_VERSION}',
    ]
)
