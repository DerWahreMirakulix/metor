# Metor Naming Glossary

This document is the canonical terminology reference for the Metor codebase.
It is binding: every new or renamed symbol, setting, event, or documentation
string MUST follow these definitions. When in doubt, extend this file instead
of inventing a parallel term.

## Dimension 1 — Message Semantics (User Concept, unchanged)

The user-facing world is split into two message semantics. These terms are
used by the UI, the IPC contract, and the message store. They do NOT change.

| Term   | Meaning                                                                                   |
| ------ | ----------------------------------------------------------------------------------------- |
| `live` | Ephemeral, interactive. Never appears in chat history; payload is shredded after consume. |
| `drop` | Durable, mailbox-style. Persists until deletion or shred policy.                          |

Examples that keep this vocabulary: `SendMessageCommand`, `Delivery.LIVE` /
`Delivery.DROP`, `TextContent`, `ChatTransportState`, UI prompt tags
(`[Drop]`, `[Switching]`, `[Reconnecting]`).

## Dimension 2 — Connection Type (Backend, `transport` field)

The backend transport layer distinguishes exactly three connection types.
The IPC/ledger field `transport` uses only these values.

| Value     | Meaning                                                                          |
| --------- | -------------------------------------------------------------------------------- |
| `session` | Persistent, authenticated channel (previously "live tunnel").                    |
| `tunnel`  | Cached circuit route for batched drop delivery (previously "drop tunnel cache"). |
| `direct`  | Short-lived single connection per drop (used when tunnel caching is disabled).   |

`transport` is logged in the history ledger only when the live-history policy
allows it (see `daemon.record_live_history`). When that setting is `false`, the
field is omitted from ALL rows — uniform absence, never selective absence.

## Term Rules

- `reuse` is a DESCRIPTION ("drop delivered over a session channel"), not an
  enum value and not a fourth connection type.
- "Warm" describes drop-tunnel readiness (cached circuit), never a transport.
- "Focus" is a UI relevance signal, never a transport decision.
- The daemon owns connection-type decisions; the UI only expresses message
  semantics (`live`/`drop`).

## Settings Namespaces

| Prefix            | Scope                                     | Owner                                    |
| ----------------- | ----------------------------------------- | ---------------------------------------- |
| `client.*`        | Client-machine behavior, paradigm-neutral | Core client layer                        |
| `daemon.*`        | Daemon-host behavior                      | Daemon (only scope the daemon validates) |
| `ui.<frontend>.*` | Frontend-owned presentation/behavior      | Registering UI frontend                  |

The daemon validates only `daemon.*` keys against its own registry. Any other
prefix is client scope and rejected with `CLIENT_SCOPE_KEY_REJECTED`.

## Mapping (old → new)

| Old                                                                                                             | New                                | Where                                 |
| --------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------- |
| `PrimaryTransport.LIVE` / `DROP`                                                                                | `session` / `tunnel` (plus `none`) | StateTracker                          |
| `LiveTransportState`                                                                                            | `SessionState`                     | transport state                       |
| `DropTunnelState`                                                                                               | `TunnelState`                      | transport state                       |
| `_live_consumer_clients`                                                                                        | `_session_consumers`               | daemon engine                         |
| `record_live_history` / `record_drop_history`                                                                   | unchanged                          | history settings (semantic dimension) |
| `DAEMON_CANNOT_MANAGE_UI`                                                                                       | `CLIENT_SCOPE_KEY_REJECTED`        | IPC event                             |
| `ui.prompt_sign` / `ui.chat_limit` / `ui.chat_buffer_padding` / `ui.inbox_notification_delay`                   | `ui.terminal.*`                    | frontend registry                     |
| `ui.default_profile` / `ui.ipc_timeout` / `ui.chat_daemon_autostart` / `ui.history_limit` / `ui.messages_limit` | `client.*`                         | settings schema                       |
