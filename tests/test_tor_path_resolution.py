"""Regression tests for Tor executable resolution across host environments."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.tor import TorManager
from metor.utils import Constants


class TorPathResolutionTests(unittest.TestCase):
    def test_env_override_wins_on_windows(self) -> None:
        with (
            patch('metor.core.tor.os.name', 'nt'),
            patch.object(Constants, 'TOR_PATH', r'C:\Tor\tor.exe'),
            patch('metor.core.tor.shutil.which', return_value=r'C:\FromPath\tor.exe'),
        ):
            self.assertEqual(TorManager._resolve_tor_command(), r'C:\Tor\tor.exe')

    def test_windows_uses_path_before_data_dir_fallback(self) -> None:
        with (
            patch('metor.core.tor.os.name', 'nt'),
            patch.object(Constants, 'TOR_PATH', ''),
            patch('metor.core.tor.shutil.which', return_value=r'C:\Tor\tor.exe'),
        ):
            self.assertEqual(TorManager._resolve_tor_command(), r'C:\Tor\tor.exe')

    def test_windows_falls_back_to_data_dir_tor_exe(self) -> None:
        with (
            patch('metor.core.tor.os.name', 'nt'),
            patch.object(Constants, 'TOR_PATH', ''),
            patch('metor.core.tor.shutil.which', return_value=None),
        ):
            self.assertEqual(
                TorManager._resolve_tor_command(),
                str(Constants.DATA / Constants.TOR_WIN),
            )


if __name__ == '__main__':
    unittest.main()
