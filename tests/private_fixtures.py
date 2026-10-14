"""Disposable owner-private storage roots for tests that exercise protected state."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType

from metor.utils import create_private_directory_tree


class PrivateTemporaryDirectory:
    """Own a private child beneath the standard library's temporary container.

    Elevated Windows processes can create ordinary temporary directories owned
    by the Administrators group. Protected Core storage deliberately refuses
    to adopt a foreign owner, so positive storage fixtures create an explicit
    current-user-owned child using the same primitive as production profiles.
    Tests of foreign ownership or unsafe paths must use their own raw fixtures.
    """

    def __init__(
        self,
        *,
        prefix: str = 'metor-private-test-',
        suffix: str = '',
        dir: str | Path | None = None,
    ) -> None:
        """Create the container and private child, cleaning up partial failures."""
        self._temporary = TemporaryDirectory(prefix=prefix, suffix=suffix, dir=dir)
        root = Path(self._temporary.name) / 'private'
        try:
            create_private_directory_tree(root, ())
        except BaseException:
            self._temporary.cleanup()
            raise
        self.name = str(root)

    def __enter__(self) -> str:
        """Return the owned path with standard TemporaryDirectory context semantics."""
        return self.name

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Remove the complete disposable container after its resources are closed."""
        self.cleanup()

    def cleanup(self) -> None:
        """Remove the owned child and its parent, preserving ordinary cleanup errors."""
        self._temporary.cleanup()
