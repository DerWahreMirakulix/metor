"""Non-visual contracts and platform ports for the future embedded UI."""

from metor.ui.embedded.contracts import (
    CapabilityInfo,
    DaemonHealth,
    DaemonLockState,
    DropConversationSummary,
    EmbeddedStartupSnapshot,
    LiveAction,
    LiveSessionPhase,
    LiveSessionSummary,
    MessagePage,
    MessagePageItem,
    RevisionGate,
    SettingDescriptor,
)
from metor.ui.embedded.platform import EmbeddedPlatform, PlatformCapabilities

__all__ = [
    'CapabilityInfo',
    'DaemonHealth',
    'DaemonLockState',
    'DropConversationSummary',
    'EmbeddedPlatform',
    'EmbeddedStartupSnapshot',
    'LiveAction',
    'LiveSessionPhase',
    'LiveSessionSummary',
    'MessagePage',
    'MessagePageItem',
    'PlatformCapabilities',
    'RevisionGate',
    'SettingDescriptor',
]
