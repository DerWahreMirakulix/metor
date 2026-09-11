"""Independent general command-line entry point for Metor."""

import sys

from metor.cli import run_cli


def main() -> None:
    """
    Runs the base CLI without importing an interactive frontend.

    Args:
        None

    Returns:
        None
    """
    sys.exit(run_cli(sys.argv[1:]))


if __name__ == '__main__':
    main()
