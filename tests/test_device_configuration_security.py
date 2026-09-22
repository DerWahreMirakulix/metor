"""Security regressions for handle-bound GUI device configuration reads."""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metor.ui.gui.platform.configuration import (
    DeviceConfigurationError,
    read_configuration,
)


DEVICE = """schema_version = 1
[display]
adapter = "simulator"
width_px = 480
height_px = 800
[input]
adapter = "simulator"
ptt_binding = "ptt"
power_binding = "power"
"""


class DeviceConfigurationSecurityTests(unittest.TestCase):
    """Ensures trust checks describe the exact object whose bytes are parsed."""

    def test_posix_accepts_owner_readonly_file(self) -> None:
        if os.name == 'nt':
            self.skipTest('POSIX permission contract')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            path.write_text(DEVICE, encoding='utf-8')
            path.chmod(stat.S_IRUSR)

            config = read_configuration(str(path), True)

        self.assertEqual(config.logical_size, (480, 800))

    def test_posix_rejects_group_or_world_writable_file(self) -> None:
        if os.name == 'nt':
            self.skipTest('POSIX permission contract')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            path.write_text(DEVICE, encoding='utf-8')
            for mode in (stat.S_IRUSR | stat.S_IWUSR | stat.S_IWGRP, 0o666):
                with self.subTest(mode=oct(mode)):
                    path.chmod(mode)
                    with self.assertRaisesRegex(DeviceConfigurationError, 'writable'):
                        read_configuration(str(path), True)

    def test_posix_rejects_symbolic_and_hard_links(self) -> None:
        if os.name == 'nt':
            self.skipTest('POSIX link contract')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target.toml'
            target.write_text(DEVICE, encoding='utf-8')
            symbolic = root / 'symbolic.toml'
            symbolic.symlink_to(target)
            hard = root / 'hard.toml'
            os.link(target, hard)

            for path in (symbolic, hard):
                with (
                    self.subTest(path=path.name),
                    self.assertRaises(DeviceConfigurationError),
                ):
                    read_configuration(str(path), True)

    def test_posix_fifo_is_rejected_without_waiting_for_a_writer(self) -> None:
        """A special input is classified before any blocking content read.

        Args:
            None

        Returns:
            None
        """
        if os.name == 'nt' or not hasattr(os, 'mkfifo'):
            self.skipTest('POSIX FIFO contract')
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / 'device.toml'
            os.mkfifo(fifo)
            source_root = Path(__file__).resolve().parents[1] / 'src'
            environment = os.environ.copy()
            current_path = environment.get('PYTHONPATH')
            environment['PYTHONPATH'] = (
                f'{source_root}{os.pathsep}{current_path}'
                if current_path
                else str(source_root)
            )
            probe = (
                'import sys\n'
                'from metor.ui.gui.platform.configuration import ('
                'DeviceConfigurationError, read_configuration)\n'
                'try:\n'
                '    read_configuration(sys.argv[1], True)\n'
                'except DeviceConfigurationError:\n'
                '    raise SystemExit(0)\n'
                'raise SystemExit(1)\n'
            )
            result = subprocess.run(
                [sys.executable, '-c', probe, str(fifo)],
                capture_output=True,
                check=False,
                env=environment,
                timeout=5.0,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))

    def test_validation_does_not_stat_path_before_opening(self) -> None:
        if os.name == 'nt':
            self.skipTest('POSIX descriptor contract')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            path.write_text(DEVICE, encoding='utf-8')

            with patch.object(
                Path,
                'stat',
                side_effect=AssertionError('path metadata race'),
            ):
                config = read_configuration(str(path), True)

        self.assertEqual(config.width_px, 480)

    def test_path_swap_after_open_cannot_replace_read_object(self) -> None:
        if os.name == 'nt':
            self.skipTest('POSIX descriptor contract')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'device.toml'
            original = root / 'opened.toml'
            path.write_text(DEVICE, encoding='utf-8')

            def swap_after_open(location: Path) -> int:
                descriptor = os.open(location, os.O_RDONLY | os.O_NOFOLLOW)
                location.rename(original)
                location.write_text('invalid = true', encoding='utf-8')
                return descriptor

            with patch(
                'metor.ui.gui.platform.configuration._open_configuration',
                side_effect=swap_after_open,
            ):
                config = read_configuration(str(path), True)

        self.assertEqual(config.width_px, 480)

    def test_wrong_type_and_oversize_fail_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(DeviceConfigurationError, 'regular file'):
                read_configuration(str(root), True)

            path = root / 'large.toml'
            path.write_bytes(b'#' * (64 * 1024 + 1))
            with self.assertRaisesRegex(DeviceConfigurationError, '64 KiB'):
                read_configuration(str(path), True)

            path.write_text('[display', encoding='utf-8')
            with self.assertRaisesRegex(DeviceConfigurationError, 'could not be read'):
                read_configuration(str(path), True)

    def test_windows_uses_secure_opener_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            path.write_text(DEVICE, encoding='utf-8')
            descriptor = os.open(path, os.O_RDONLY)
            try:
                with (
                    patch(
                        'metor.ui.gui.platform.configuration._is_windows',
                        return_value=True,
                    ),
                    patch(
                        'metor.ui.gui.platform.configuration._open_windows_configuration',
                        return_value=descriptor,
                    ) as opener,
                ):
                    config = read_configuration(str(path), True)
                self.assertEqual(config.width_px, 480)
                opener.assert_called_once_with(path)
                descriptor = -1
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

            with (
                patch(
                    'metor.ui.gui.platform.configuration._is_windows',
                    return_value=True,
                ),
                patch(
                    'metor.ui.gui.platform.configuration._open_windows_configuration',
                    side_effect=DeviceConfigurationError(
                        'Windows device configuration trust could not be established'
                    ),
                ),
                self.assertRaisesRegex(DeviceConfigurationError, 'trust'),
            ):
                read_configuration(str(path), True)


if __name__ == '__main__':
    unittest.main()
