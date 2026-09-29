"""Parse the maintained device examples with the production configuration boundary."""

from pathlib import Path
import tempfile
import unittest

from metor.ui.gui.platform import DeviceConfigurationError, read_configuration
from metor.utils import open_private_binary_file


ROOT = Path(__file__).resolve().parents[1]


class DeviceExampleTests(unittest.TestCase):
    """Keep the shipped simulator configuration executable and nonphysical."""

    def test_simulator_example_requires_explicit_simulator_mode(self) -> None:
        """A physical run must reject the simulator's selected providers."""
        example = ROOT / 'docs/examples/gui-simulator.toml'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            with open_private_binary_file(path) as handle:
                handle.write(example.read_bytes())
            with self.assertRaises(DeviceConfigurationError):
                read_configuration(str(path), simulator=False)

    def test_simulator_example_parses_with_production_validator(self) -> None:
        """The documented example must pass the real device parser."""
        example = ROOT / 'docs/examples/gui-simulator.toml'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            with open_private_binary_file(path) as handle:
                handle.write(example.read_bytes())
            configuration = read_configuration(str(path), simulator=True)
        self.assertEqual(configuration.mode, 'simulator')
        self.assertEqual(configuration.logical_size, (480, 800))


if __name__ == '__main__':
    unittest.main()
