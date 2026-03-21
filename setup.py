from setuptools import setup, find_packages

setup(
    name='metor',
    version='0.2',
    packages=find_packages(),
    install_requires=['stem', 'PySocks', 'pynacl', 'psutil'],
    include_package_data=True,
    entry_points={'console_scripts': ['metor = metor.main:main']},
    author='LuRex',
    description='A simple Tor messenger with persistent onion address and chat commands.',
    license='MIT',
)
