"""Explicit telephone selection and guarded confirmation for replacing an ongoing Call."""

from collections.abc import Callable

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import CallState
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet

# Local Package Imports
from ..audio import show_audio_unavailable


def call_peer(
    controller: GuiController, peer: str, refresh: Callable[[], None]
) -> None:
    """Opens the same Call, confirms replacing another, or starts one explicit telephone call.

    Args:
        controller: Current presentation and authenticated Call action owner.
        peer: Canonical peer captured from the initiating contact or conversation.
        refresh: Native repaint request.
    Returns:
        None. Navigation and chat connection permission are unchanged.
    """
    if controller.state.covered:
        return
    calls, current = controller.calls, controller.calls.current
    if current is None or current.state is CallState.ENDED:
        if not calls.ready:
            show_audio_unavailable(controller, refresh, purpose='calls')
        else:
            calls.start(peer)
            refresh()
        return
    if current.peer == peer:
        calls.show(current.call_id)
        refresh()
        return
    call_id = current.call_id
    generation, client = controller.state.generation, controller.client
    sheet: ActionSheet | None = None

    def label(target: str, fallback: str) -> str:
        """Resolves current display labels while preserving the captured canonical target."""
        snapshot = controller.state.snapshot
        if snapshot is None:
            return fallback
        return next(
            (
                item.alias
                for rows in (
                    snapshot.contacts,
                    snapshot.conversations,
                    snapshot.live_contexts,
                )
                for item in rows
                if item.onion == target
            ),
            fallback,
        )

    def valid() -> bool:
        """Revalidates the original Call and client before allowing its replacement."""
        source = calls.current
        return bool(
            not controller.state.covered
            and controller.state.generation == generation
            and controller.client is client
            and source is not None
            and source.call_id == call_id
            and source.owned
            and source.state is not CallState.ENDED
            and not controller.state.busy
        )

    def replace_call() -> None:
        """Ends only the captured Call; runtime requires positive cleanup before one new start."""
        if sheet is not None and valid() and calls.handover(call_id, peer):
            sheet.dismiss(animation=False)
        refresh()

    def open_incoming() -> None:
        """Opens only the incoming Call captured by this dialog on its original client."""
        source = calls.current
        if (
            controller.state.covered
            or controller.state.generation != generation
            or controller.client is not client
            or source is None
            or source.call_id != call_id
            or source.state is not CallState.INCOMING
        ):
            return
        if sheet is not None:
            sheet.dismiss(animation=False)
        calls.show(call_id)
        refresh()

    def build(body: BoxLayout) -> None:
        """Explains exact scope and disables a confirmation whose original Call has changed."""
        source = calls.current
        matching = source is not None and source.call_id == call_id
        body.add_widget(
            Label(
                'The original call is no longer current. Close this dialog and choose Call again.'
                if not matching or source is None or source.state is CallState.ENDED
                else 'Answer or decline the incoming call before calling another contact.'
                if not source.owned
                else f'End your call with {label(current.peer, current.alias or "the current contact")} and call {label(peer, "this contact")}?',
                role='support',
            )
        )
        if matching and source is not None and not source.owned:
            body.add_widget(
                Action(
                    'Open incoming call controls',
                    open_incoming,
                )
            )
        if sheet is not None and sheet.primary_action is not None:
            sheet.primary_action.disabled = not valid()

    sheet = ActionSheet(
        controller,
        build,
        title='Call ongoing',
        primary=('End current call and call this peer', replace_call),
        revision=lambda: (
            controller.state.generation,
            controller.state.busy,
            calls.revision,
        ),
    )
    assert sheet.primary_action is not None
    sheet.primary_action.disabled = not valid()
    sheet.show()
    refresh()
