"""Observe real Linux logind lifecycle transitions for an installed GUI."""

import argparse
import threading
import time

from metor.ui.gui.platform.lifecycle import DesktopLifecycleEvent, LinuxLifecycleSource


NATIVE_EVENT_TIMEOUT_SEC = 120.0


def main() -> None:
    """Require operator-triggered lock, suspend, and resume provider events.

    Args:
        None

    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--expect',
        default='lock,suspend,resume',
        help='Comma-separated ordered lifecycle events to observe.',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=NATIVE_EVENT_TIMEOUT_SEC,
        help='Maximum seconds for authorized external lifecycle actions.',
    )
    args = parser.parse_args()
    try:
        expected = [DesktopLifecycleEvent(value) for value in args.expect.split(',')]
    except ValueError as exc:
        raise SystemExit('Unsupported lifecycle event in --expect.') from exc
    if not expected or args.timeout <= 0:
        raise SystemExit('At least one event and a positive timeout are required.')

    received: list[DesktopLifecycleEvent] = []
    condition = threading.Condition()

    def publish(event: DesktopLifecycleEvent) -> None:
        """Capture validated native provider events in arrival order.

        Args:
            event (DesktopLifecycleEvent): Validated lifecycle event.

        Returns:
            None
        """
        with condition:
            received.append(event)
            condition.notify_all()

    source = LinuxLifecycleSource(publish)
    source.start()
    print(
        'NATIVE_LIFECYCLE_READY: trigger only the authorized lock/suspend/resume '
        'actions listed by --expect.',
        flush=True,
    )
    deadline = time.monotonic() + args.timeout
    matched = 0
    try:
        with condition:
            while matched < len(expected):
                if DesktopLifecycleEvent.SOURCE_LOST in received:
                    raise AssertionError('Linux lifecycle provider was lost')
                while received:
                    event = received.pop(0)
                    if event is expected[matched]:
                        matched += 1
                        if matched == len(expected):
                            break
                remaining = deadline - time.monotonic()
                if matched < len(expected) and remaining <= 0:
                    raise AssertionError(
                        f'Native lifecycle sequence incomplete at {matched}: '
                        f'{expected!r}'
                    )
                if matched < len(expected):
                    condition.wait(remaining)
    finally:
        source.close()
    print('NATIVE_LINUX_LIFECYCLE_OK')


if __name__ == '__main__':
    main()
