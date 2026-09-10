"""Deterministic read-model fixtures for future embedded UI tests."""

from datetime import datetime, timezone

from metor.core.api import ConnectionActor
from metor.versioning import APP_VERSION, IPC_PROTOCOL_VERSION
from metor.ui.embedded.contracts import (
    CapabilityInfo,
    DaemonHealth,
    DaemonLockState,
    DropConversationSummary,
    EmbeddedStartupSnapshot,
    LiveAction,
    LiveSessionPhase,
    LiveSessionSummary,
)

FIXTURE_TIME: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)

LOCKED_STARTUP: EmbeddedStartupSnapshot = EmbeddedStartupSnapshot(
    revision=1,
    lock_state=DaemonLockState.LOCKED,
    health=DaemonHealth.ONLINE,
    profile_id=None,
    unread_drop_total=0,
    active_live_count=0,
    pending_live_count=0,
    incoming_request_count=0,
    capability_info=CapabilityInfo(
        IPC_PROTOCOL_VERSION,
        APP_VERSION,
        ('text', 'lock'),
    ),
)

READY_STARTUP: EmbeddedStartupSnapshot = EmbeddedStartupSnapshot(
    revision=10,
    lock_state=DaemonLockState.READY,
    health=DaemonHealth.ONLINE,
    profile_id='primary',
    unread_drop_total=2,
    active_live_count=1,
    pending_live_count=1,
    incoming_request_count=1,
    capability_info=CapabilityInfo(
        IPC_PROTOCOL_VERSION,
        APP_VERSION,
        ('text', 'lock'),
    ),
)

DROP_CONVERSATIONS: tuple[DropConversationSummary, ...] = (
    DropConversationSummary(
        peer_id='alice.onion',
        alias='alice',
        last_drop_preview='Meet tomorrow?',
        unread_count=2,
        last_activity=FIXTURE_TIME,
        has_pending_outbox=False,
        has_active_live_session=True,
    ),
)

LIVE_SESSIONS: tuple[LiveSessionSummary, ...] = (
    LiveSessionSummary(
        peer_id='alice.onion',
        alias='alice',
        phase=LiveSessionPhase.CONNECTED,
        actor=ConnectionActor.LOCAL,
        reason_code=None,
        started_at=FIXTURE_TIME,
        pending_outbound_count=0,
        allowed_actions=(LiveAction.END, LiveAction.RETUNNEL),
    ),
)
