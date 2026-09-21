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
    if '--daemon-child' in argv:
        from metor.daemon_main import run

        sys.exit(run(argv))

    from metor.cli import run_cli

    sys.exit(run_cli(argv))


if __name__ == '__main__':
    main()
