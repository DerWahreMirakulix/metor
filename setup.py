"""Build-time dependency metadata for the base Metor distribution."""

import sys
from pathlib import Path

from setuptools import setup


SOURCE_DIR: Path = Path(__file__).resolve().parent / 'src'
sys.path.insert(0, str(SOURCE_DIR))

from metor.versioning import APP_VERSION  # noqa: E402


setup(
    install_requires=[
        f'metor-sdk=={APP_VERSION}',
        'stem==1.8.2',
        'PySocks==1.7.1',
        'pynacl==1.6.2',
        'psutil==7.2.2',
        'python-dotenv==1.2.2',
        "sqlcipher3-binary==0.6.0; platform_system == 'Linux'",
        "sqlcipher3==0.6.2; platform_system != 'Linux'",
    ]
)
