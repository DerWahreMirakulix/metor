"""Build-time dependency closure for the independent native GUI distribution."""

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
        'Kivy==2.3.1',
        'sounddevice==0.5.3',
        'qrcode==8.2',
        'accesskit==0.7.0',
        'dbus-next==0.2.3; platform_system == "Linux"',
    ]
)
