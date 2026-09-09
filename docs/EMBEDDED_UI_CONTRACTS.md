# Embedded UI Preparation Contracts

This document defines the integration boundary for a later hardware-operated
frontend. It does not specify visual layout or implement screens.

## Ownership and data flow

```text
hardware/platform ports → metor.ui.embedded → metor.client → typed IPC
                                                     ↓
                              daemon → domain → Tor/crypto/storage
```

The daemon owns identity, profiles, lock/auth state, Tor, contacts, message
delivery, outbox state, history, and settings. `metor.client` owns framing,
authentication exchange, request correlation, reconnect attachment, and typed
command/event transport. Frontends own presentation and transient navigation.
Injected platform ports own device input, display/audio/camera integration,
power state, haptics, clocks, local diagnostics, and `ui.embedded.*` settings.

No Metor-owned state is inferred from rendered strings. No platform package is
imported by Core. DROP pages and LIVE streams remain separate projections.

## Existing contract audit

| Area                 | Authoritative current contract                                                                                                            |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Initialize/auth/lock | `InitCommand`, protocol negotiation, `DaemonLockedEvent`, `UnlockCommand`, session challenge/proof, `LockCommand`, typed lifecycle events |
| Contacts             | typed list/add/promote/rename/remove commands and result events; saved and discovered peers remain distinguishable                        |
| DROP                 | `SendMessageCommand(Delivery.DROP, content)`, inbox counts, unread consume, paged stored messages, ACK/failure states                     |
| LIVE                 | connect/accept/reject/disconnect, connecting/pending/connected/reconnect/retunnel events, consumer registration, ACK/replay/fallback      |
| Content              | `MessageContent` currently resolves to `TextContent`; delivery is independent; voice/file need authenticated bounded blob references      |
| History              | projected typed history and an optional raw transport ledger                                                                              |
| Settings             | global metadata, profile overrides, and frontend-local `ui.*` namespaces                                                                  |
| Recovery             | request IDs correlate responses; clients reattach, negotiate, request startup state, then subscribe                                       |

## Previous UI module classification and final import map

| Previous location                                       | Classification                    | Canonical location                  |
| ------------------------------------------------------- | --------------------------------- | ----------------------------------- |
| `ui/chat/**`                                            | terminal-only chat loop/rendering | `ui/terminal/chat/**`               |
| `ui/cli/**`                                             | terminal-only command interface   | `ui/terminal/cli/**`                |
| `ui/presenter/**`                                       | terminal-only text rendering      | `ui/terminal/presenter/**`          |
| root help/models/prompt/session-auth/theme/translations | terminal-only                     | `ui/terminal/*`                     |
| `ui/registry.py`                                        | frontend registry/bootstrap       | unchanged                           |
| `ui/ipc/**`                                             | obsolete duplicate re-exports     | removed; callers use `metor.client` |
| `client/auth.py`, `ipc.py`, `session.py`, `stream.py`   | frontend-neutral SDK              | unchanged and evolved in place      |

`metor.ui.__init__` now exposes only registry/selection symbols. The terminal
entry remains registered as the default frontend and uses the same SDK/API
boundary available to future frontends.

## Prototype contract matrix

| Screen/action/state  | Consumes                                                      | Emits                                       | Owner    | Status/change                                                  |
| -------------------- | ------------------------------------------------------------- | ------------------------------------------- | -------- | -------------------------------------------------------------- |
| Locked startup       | `EmbeddedStartupSnapshot`                                     | `UnlockCommand`                             | Core     | supported; projection defined                                  |
| Home/status          | startup snapshot and typed health events                      | refresh/snapshot request                    | Core     | projection defined; aggregate IPC snapshot remains future work |
| DROP list            | `DropConversationSummary`                                     | inbox/page commands                         | Core     | projection defined; aggregate summary query remains            |
| DROP detail/send     | `DropMessagePage`, typed delivery states                      | `SendMessageCommand(DROP, content)`         | Core     | text supported                                                 |
| LIVE list/detail     | `LiveSessionSummary` and lifecycle events                     | connect/accept/reject/disconnect/retunnel   | Core     | existing events; projection defined                            |
| LIVE text stream     | `LiveContentItem` / `MessageReceivedEvent(LIVE, TextContent)` | `SendMessageCommand(LIVE, TextContent)`     | Core     | supported                                                      |
| Manual fallback      | fallback result with exact `msg_ids`                          | `FallbackCommand`                           | Core     | supported; content identity preserved                          |
| Retunnel             | initiated/state/success/failure events                        | `RetunnelCommand`                           | Core     | supported; old route preservation is represented by state      |
| Contacts/QR          | raw scan bytes, typed QR validation result                    | `AddContactCommand` after validation        | split    | version-one validator implemented; UI flow later               |
| History              | typed projected/raw events                                    | history queries/filters                     | Core     | current peer/limit filters; richer family/time filters remain  |
| Settings             | `SettingDescriptor`                                           | typed setting commands or local store write | split    | descriptor defined; aggregate projection remains               |
| Keyboard/D-pad/PTT   | `HardwareInputEvent`                                          | navigation or Metor commands                | Platform | port and fake defined; behavior later                          |
| Audio/camera/haptics | capability flags and optional ports                           | platform calls                              | Platform | ports only; no media protocol/screens                          |
| Screen sleep/power   | display and power ports                                       | platform request                            | Platform | distinct from `LockCommand`                                    |

## Startup, ordering, and recovery

The deterministic sequence is attach, negotiate version/capabilities, resolve
locked/auth/ready state, authenticate or unlock, request one authoritative
snapshot, subscribe, then apply incremental events. On IPC loss, incremental
application stops; after reconnect a new snapshot is installed before events are
accepted.

Every command uses a stable request ID. Responses with another request ID are
ignored by that request. Projection events require a stable event/entity ID and
monotonically increasing revision. `RevisionGate` rejects pre-snapshot, stale,
out-of-order, and duplicate events and resets its duplicate set whenever a new
snapshot is installed. The current daemon does not yet emit a global revision,
so the gate defines the required contract before the aggregate snapshot API is
implemented.

Hardware bounce must reuse the same request ID until a terminal result. Starting
LIVE remains an explicit `ConnectCommand`; incoming sessions require explicit
`AcceptCommand` because `daemon.auto_accept_contacts` defaults to `false`.
Ending LIVE uses the existing daemon policy: pending content is retained for
recovery when recovery is active, otherwise `daemon.fallback_to_drop` controls
content-preserving fallback. Discard is intentionally unavailable until a
secure, explicitly confirmed deletion command exists.

## Settings ownership

| Concern                   | Ownership                           | Representative key/state            |
| ------------------------- | ----------------------------------- | ----------------------------------- |
| Auto-accept               | daemon-global with profile override | `daemon.auto_accept_contacts=false` |
| Live-to-DROP fallback     | daemon-global with profile override | `daemon.fallback_to_drop`           |
| History retention         | daemon-global/profile override      | daemon history settings             |
| Ephemeral DROP policy     | daemon-global/profile override      | daemon ephemeral-message setting    |
| Reuse LIVE for DROP       | daemon-global/profile override      | `daemon.reuse_live_for_drops`       |
| Reconnect/retunnel timing | daemon-global/profile override      | daemon timeout settings             |
| Brightness                | device-local                        | `ui.embedded.brightness`            |
| Volume                    | device-local                        | `ui.embedded.volume`                |
| Haptics                   | device-local                        | `ui.embedded.haptics`               |
| Key sound                 | device-local                        | `ui.embedded.key_sound`             |
| PTT mode                  | device-local                        | `ui.embedded.ptt_mode`              |
| Auto-lock preference      | device-local                        | `ui.embedded.auto_lock`             |
| Battery/charging          | platform runtime state              | `PowerPort.battery_state()`         |
| Camera/audio availability | platform runtime capability         | `PlatformCapabilities`              |

## Remaining implementation gaps

- Add one daemon-owned aggregate startup snapshot with global revision/event IDs.
- Add DROP conversation summaries and cursor pagination commands/events.
- Extend history queries with family, event-code, and time-range filters.
- Project full setting metadata over IPC.
- Design authenticated bounded blob upload/download and references before adding
  `VoiceContent` or `FileContent`.
- Decide and specify an explicitly confirmed destructive `DISCARD` policy if it
  is wanted for ending LIVE sessions.
