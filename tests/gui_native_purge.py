"""Native destruction-cover fixtures with synthetic events and no destructive command or device."""

from metor.core.api import (
    SelfDestructInitiatedEvent,
    SelfDestructKeyDestroyedEvent,
    SelfDestructSafeEvent,
    SelfDestructCompletedEvent,
    SelfDestructCleanupFailedEvent,
)
from metor.ui.gui.runtime import GuiController


def configure_purge(controller: GuiController, variant: str) -> None:
    """Installs only explicitly synthetic progress through the production observation reducer.

    Args:
        controller: Isolated simulator with no authenticated Core client.
        variant: Initiated, key-only, safe, complete, cleanup failure or unknown fixture.
    Returns:
        None
    """
    assert controller.simulator and controller.client is None
    generation = controller.state.generation
    operation = 'd' * 32
    monitor = controller.purge
    monitor.observe(generation, SelfDestructInitiatedEvent('Simulator', operation))
    if variant == 'purge_key':
        monitor.observe(
            generation, SelfDestructKeyDestroyedEvent('Simulator', operation)
        )
    if variant in {'purge_safe', 'purge_complete', 'purge_failed'}:
        monitor.observe(generation, SelfDestructSafeEvent('Simulator', operation))
    if variant == 'purge_complete':
        monitor.observe(generation, SelfDestructCompletedEvent('Simulator', operation))
    if variant == 'purge_failed':
        monitor.observe(
            generation,
            SelfDestructCleanupFailedEvent('Simulator', operation_id=operation),
        )
    if variant == 'purge_unknown':
        monitor.lost(generation)
    controller.poll()
    assert controller.state.covered and controller.state.route.view == 'V22'
