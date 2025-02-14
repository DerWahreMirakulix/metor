from setuptools import setup, find_packages

setup(
    name="metor",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "stem",
        "PySocks"
    ],
    include_package_data=True,
    package_data={
        'metor': ['tor.exe'] 
    },
    entry_points={
        "console_scripts": [
            "metor = metor.cli:main"
        ]
    },
    author="LuRex",
    description="A simple Tor messenger with persistent onion address and chat commands.",
    license="MIT",
)
