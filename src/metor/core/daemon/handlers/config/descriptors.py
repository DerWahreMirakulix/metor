"""Safe settings disclosure over the public configuration boundary."""

from metor.core.api import SettingSnapshotEntry
from metor.data import Settings, SettingKey
from metor.data.profile import ProfileManager


SAFE_SETTING_LABELS: dict[SettingKey, tuple[str, str]] = {
    SettingKey.FALLBACK_TO_DROP: ('Live', 'Fallback to Drop'),
    SettingKey.ALLOW_DROPS: ('Live', 'Receive Drops'),
    SettingKey.AUTO_ACCEPT_CONTACTS: ('Live', 'Auto-accept saved contacts'),
    SettingKey.SEND_READ_RECEIPTS: ('Live', 'Send read receipts'),
    SettingKey.EPHEMERAL_MESSAGES: ('Privacy', 'Ephemeral Drops'),
    SettingKey.RECORD_LIVE_HISTORY: ('Privacy', 'Record Live history'),
    SettingKey.RECORD_DROP_HISTORY: ('Privacy', 'Record Drop history'),
    SettingKey.MAX_LIVE_VOICE_BUFFER_BYTES: ('Device', 'Voice buffer limit'),
    SettingKey.MAX_PENDING_LIVE_MSGS: ('Advanced', 'Pending Live message limit'),
    SettingKey.MAX_PENDING_LIVE_BYTES: ('Advanced', 'Pending Live byte limit'),
    SettingKey.MAX_UNSEEN_DROP_MSGS: ('Advanced', 'Unseen Drop limit'),
    SettingKey.MAX_UNSEEN_LIVE_MSGS: ('Advanced', 'Unseen Live limit'),
    SettingKey.MAX_CONCURRENT_CONNECTIONS: ('Advanced', 'Concurrent connections'),
    SettingKey.MAX_CONNECT_RETRIES: ('Advanced', 'Connection retries'),
    SettingKey.MAX_TOR_RETRIES: ('Advanced', 'Tor startup retries'),
    SettingKey.TOR_TIMEOUT: ('Advanced', 'Tor socket timeout'),
    SettingKey.STREAM_IDLE_TIMEOUT: ('Advanced', 'Socket read timeout'),
    SettingKey.LATE_ACCEPTANCE_TIMEOUT: ('Advanced', 'Call acceptance timeout'),
    SettingKey.CONNECT_RETRY_BACKOFF_DELAY: ('Advanced', 'Connection retry delay'),
    SettingKey.LIVE_RECONNECT_DELAY: ('Advanced', 'Live reconnect delay'),
    SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT: ('Advanced', 'Reconnect grace period'),
    SettingKey.LIVE_DISCONNECT_LINGER_TIMEOUT: ('Advanced', 'Disconnect flush period'),
    SettingKey.RETUNNEL_RECONNECT_DELAY: ('Advanced', 'Route reconnect delay'),
    SettingKey.RETUNNEL_RECOVERY_RETRIES: ('Advanced', 'Route recovery retries'),
    SettingKey.LIVE_IDLE_TIMEOUT: ('Advanced', 'Unfocused Live idle timeout'),
    SettingKey.DROP_TUNNEL_IDLE_TIMEOUT: ('Advanced', 'Drop route cache lifetime'),
    SettingKey.ALLOW_DROP_STANDBY_ON_LIVE: ('Advanced', 'Keep Drop route on standby'),
    SettingKey.REUSE_LIVE_FOR_DROPS: ('Advanced', 'Reuse Live for Drops'),
    SettingKey.MAX_IPC_CLIENTS: ('Advanced', 'Attached client limit'),
    SettingKey.DAEMON_IPC_TIMEOUT: ('Advanced', 'Service IPC timeout'),
    SettingKey.EXPOSE_DROP_REJECTION: ('Advanced', 'Explain Drop rejection to peers'),
}


def setting_descriptors(pm: ProfileManager) -> list[SettingSnapshotEntry]:
    """Combines permitted presentation metadata with authoritative registry values.

    Args:
        pm: Owning profile; the frontend never reads its files or settings registry.
    Returns:
        list[SettingSnapshotEntry]: Finite safe catalog with effective values and scope.
    """
    snapshots = {
        row['key']: row for row in pm.config.get_setting_snapshots(domain='daemon')
    }
    result: list[SettingSnapshotEntry] = []
    for key, (group, label) in SAFE_SETTING_LABELS.items():
        spec = Settings.get_spec(key)
        row = snapshots[key.value]
        description = spec.description
        if key is SettingKey.ALLOW_DROPS:
            description = (
                'Controls receiving and processing Drops. When off, new Drop text '
                'sends and recording starts are also refused. Existing finalized '
                'recordings can still be queued.'
            )
        result.append(
            SettingSnapshotEntry(
                **row,
                value_type=type(spec.default).__name__,
                display_name=label,
                display_group=group,
                description=description,
                constraints=spec.constraints,
                security_note=spec.security_note or '',
                min_value=spec.min_value,
                max_value=spec.max_value,
                editable=spec.allow_profile_override
                and row['source'] != 'plaintext_forced',
                scope='profile',
            )
        )
    return result
