"""Independent general command-line entry point for Metor."""

import sys


def main() -> None:
    """
    Runs the base CLI without importing an interactive frontend.

    Args:
        None

    Returns:
        None
    """
    argv: list[str] = sys.argv[1:]
    from metor.cli.entry import run_cli

    sys.exit(run_cli(argv))


if __name__ == '__main__':
    main()
