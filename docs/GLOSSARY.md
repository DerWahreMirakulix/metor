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
| `live` | Ephemeral, interactive. Never appears in chat history; Core payload may be shredded after consume. |
| `drop` | Durable, mailbox-style. Persists until deletion or shred policy.                                |

Examples that keep this vocabulary: `SendMessageCommand`, `Delivery.LIVE` /
`Delivery.DROP`, `TextContent`, `ChatTransportState`, UI prompt tags
(`[Drop]`, `[Switching]`, `[Reconnecting]`).

## Message content and identity

| Term | Meaning |
| ---- | ------- |
| `msg_id` | Stable logical message identity across retry, replay, ACK, and LIVE-to-DROP fallback. |
| `TextContent` | UTF-8 typed message content. |
| `VoiceContent` | Typed metadata referencing a bounded Core-owned Voice blob; never raw audio in normal message NDJSON. |
| Voice turn | One physical PTT press, one logical message, and one stable `msg_id`, regardless of chunk count. |
| consume | Explicit local read/unseen transition; distinct from a delivery ACK and optionally produces a remote read receipt. |

## Client access and lifecycle

| Term | Meaning |
| ---- | ------- |
| hard lock | `LockCommand`: releases the entire active profile runtime and its key/database/Tor state. |
| restricted client | Per-IPC-session authorization state used for device-style lock behavior while the profile runtime remains active. |
| quick unlock | Optional challenge proof derived from a salted memory-hard PIN verifier; never a profile decryption credential. |
| graceful profile exit | Reliability-preserving local commit/connection shutdown/hard-lock flow that does not wait for remote DROP delivery. |
| purge / self-destruct | Reliability-preempting destruction flow: abort communication work, destroy key access, then perform best-effort cleanup. |
| revision | Daemon-authored monotonic sequence on IPC events used to reconcile an aggregate runtime snapshot with buffered events. |
| frontend ID | Stable entry-point name in `metor.ui_frontends`, selected only by `metor chat`. |
| retained inventory | Content-free, paginated discovery of pending outbound or unseen Voice identities; listing never consumes payload. |

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
| `ui.<frontend>.*` | Frontend-owned presentation/behavior      | Inert official base metadata catalog; narrow frontend values view |

The daemon validates only `daemon.*` keys against its own registry. Any other
prefix is client scope and rejected with `CLIENT_SCOPE_KEY_REJECTED`.

## Profile storage security

| Term                  | Meaning                                                                 |
| --------------------- | ----------------------------------------------------------------------- |
| `PMK`                 | Random 32-byte Profile Master Key; root of encrypted profile storage.   |
| `KEK`                 | Password-derived Key Encryption Key used only to wrap or unwrap a PMK.  |
| `DB_KEY`              | PMK-derived SQLCipher key under the `metor/db/v1` domain.               |
| `SECRET_KEY`          | PMK-derived identity-secret key under `metor/secrets/v1`.               |
| `BLOB_KEY`            | PMK-derived external-object root under `metor/blobs/v1`.                |
| `keyslot`             | Versioned protector metadata containing only an authenticated PMK wrap. |
| `blob_id`             | Opaque identifier for an encrypted object; never a filesystem path.     |
| `temporary blob`      | Encrypted crash-safe spool object that is not normal persisted history. |
| unsent draft | Core-owned capture staging, not an eligible outbox message; finalization is distinct from explicit DROP commit. |
| fallback repair intent | `fallback_committed` receipt payload metadata authorizes exact outbound media promotion after committed LIVE→DROP conversion. |
| request lease | One SDK exchange's connection generation, socket and registration identity; reused wire request IDs do not transfer it. |
| configured endpoint | Host-resolved local/forwarded port; successful SDK connect and bootstrap are separate checks. |
| `persistent blob`     | Encrypted durable object referenced by structured database metadata.    |
| `KeyProtector`        | Boundary that protects, unwraps, rewraps, and destroys PMK access.      |
| `cryptographic erase` | Destruction of PMK access before best-effort ciphertext cleanup.        |

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
