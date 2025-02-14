from setuptools import setup, find_packages

setup(
    name="metor",
    version="0.1",
    packages=find_packages(), 
    install_requires=[
        "stem",
        "PySocks"
    ],
    entry_points={
        "console_scripts": [
            "metor = metor.cli:main"
        ]
    },
    author="DerWahreMirakulix",
    description="A simple Tor messenger with persistent onion address and chat commands.",
    license="MIT",
)
