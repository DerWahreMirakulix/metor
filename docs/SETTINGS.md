# Metor Settings Documentation

This document is auto-generated from setting metadata in `metor.data.settings` and `metor.data.profile.models`.
It is the canonical reference for supported user-facing settings and structural profile config keys.

## Configuration Model

- `metor settings ...` changes global defaults in `settings.json`.
- `metor config ...` writes profile-specific overrides in the active profile `config.json`.
- UI settings stay local to the client machine. Daemon settings are applied to the owning daemon runtime.
- Structural profile config keys are special-case profile metadata, not regular cascading settings.

## Table of Contents

- [Configuration Model](#configuration-model)
- [Cascading Settings](#cascading-settings)
  - [User Interface](#user-interface)
  - [Core Daemon](#core-daemon)
  - [Advanced Network Resilience](#advanced-network-resilience)
- [Structural Profile Config](#structural-profile-config)

## Cascading Settings

### User Interface

#### `ui.default_profile`

Selects the profile used when the CLI is started without `-p`.

| Property         | Value                                                       |
| ---------------- | ----------------------------------------------------------- |
| Type             | `str`                                                       |
| Default          | `default`                                                   |
| Category         | `User Interface`                                            |
| Scope            | `UI client-local`                                           |
| Profile Override | `No`                                                        |
| Constraints      | Non-empty profile name using letters, numbers, `-`, or `_`. |

**CLI Examples**

- `metor settings get ui.default_profile`
- `metor settings set ui.default_profile default`

---

#### `ui.prompt_sign`

Sets the prompt prefix shown in the interactive chat UI.

| Property         | Value             |
| ---------------- | ----------------- |
| Type             | `str`             |
| Default          | `$`               |
| Category         | `User Interface`  |
| Scope            | `UI client-local` |
| Profile Override | `Yes`             |
| Constraints      | Non-empty string. |

**CLI Examples**

- `metor settings get ui.prompt_sign`
- `metor settings set ui.prompt_sign $`
- `metor -p <profile> config get ui.prompt_sign`
- `metor -p <profile> config set ui.prompt_sign $`

---

#### `ui.chat_limit`

Limits the number of rendered chat lines kept in volatile UI memory.

| Property         | Value             |
| ---------------- | ----------------- |
| Type             | `int`             |
| Default          | `50`              |
| Category         | `User Interface`  |
| Scope            | `UI client-local` |
| Profile Override | `Yes`             |
| Constraints      | Integer >= 1.     |

**CLI Examples**

- `metor settings get ui.chat_limit`
- `metor settings set ui.chat_limit 50`
- `metor -p <profile> config get ui.chat_limit`
- `metor -p <profile> config set ui.chat_limit 50`

---

#### `ui.history_limit`

Default number of history events shown per request.

| Property         | Value             |
| ---------------- | ----------------- |
| Type             | `int`             |
| Default          | `50`              |
| Category         | `User Interface`  |
| Scope            | `UI client-local` |
| Profile Override | `Yes`             |
| Constraints      | Integer >= 1.     |

**CLI Examples**

- `metor settings get ui.history_limit`
- `metor settings set ui.history_limit 50`
- `metor -p <profile> config get ui.history_limit`
- `metor -p <profile> config set ui.history_limit 50`

---

#### `ui.messages_limit`

Default number of stored messages shown per request.

| Property         | Value             |
| ---------------- | ----------------- |
| Type             | `int`             |
| Default          | `50`              |
| Category         | `User Interface`  |
| Scope            | `UI client-local` |
| Profile Override | `Yes`             |
| Constraints      | Integer >= 1.     |

**CLI Examples**

- `metor settings get ui.messages_limit`
- `metor settings set ui.messages_limit 50`
- `metor -p <profile> config get ui.messages_limit`
- `metor -p <profile> config set ui.messages_limit 50`

---

#### `ui.chat_buffer_padding`

Keeps extra renderer lines around the viewport to reduce redraw churn.

| Property         | Value             |
| ---------------- | ----------------- |
| Type             | `int`             |
| Default          | `20`              |
| Category         | `User Interface`  |
| Scope            | `UI client-local` |
| Profile Override | `Yes`             |
| Constraints      | Integer >= 0.     |

**CLI Examples**

- `metor settings get ui.chat_buffer_padding`
- `metor settings set ui.chat_buffer_padding 20`
- `metor -p <profile> config get ui.chat_buffer_padding`
- `metor -p <profile> config set ui.chat_buffer_padding 20`

---

#### `ui.inbox_notification_delay`

Delays and aggregates unread-message notifications while the peer is unfocused. `0` disables buffering.

| Property         | Value               |
| ---------------- | ------------------- |
| Type             | `float`             |
| Default          | `10.0`              |
| Category         | `User Interface`    |
| Scope            | `UI client-local`   |
| Profile Override | `Yes`               |
| Constraints      | Float >= 0 seconds. |

**CLI Examples**

- `metor settings get ui.inbox_notification_delay`
- `metor settings set ui.inbox_notification_delay 10.0`
- `metor -p <profile> config get ui.inbox_notification_delay`
- `metor -p <profile> config set ui.inbox_notification_delay 10.0`

---

#### `ui.ipc_timeout`

Client-side timeout for CLI and chat IPC requests.

| Property         | Value                 |
| ---------------- | --------------------- |
| Type             | `float`               |
| Default          | `15.0`                |
| Category         | `User Interface`      |
| Scope            | `UI client-local`     |
| Profile Override | `Yes`                 |
| Constraints      | Float >= 0.1 seconds. |

**CLI Examples**

- `metor settings get ui.ipc_timeout`
- `metor settings set ui.ipc_timeout 15.0`
- `metor -p <profile> config get ui.ipc_timeout`
- `metor -p <profile> config set ui.ipc_timeout 15.0`

### Core Daemon

#### `daemon.max_tor_retries`

Controls how many times Tor launch is attempted before startup fails.

| Property         | Value            |
| ---------------- | ---------------- |
| Type             | `int`            |
| Default          | `3`              |
| Category         | `Core Daemon`    |
| Scope            | `Daemon runtime` |
| Profile Override | `Yes`            |
| Constraints      | Integer >= 1.    |

**CLI Examples**

- `metor settings get daemon.max_tor_retries`
- `metor settings set daemon.max_tor_retries 3`
- `metor -p <profile> config get daemon.max_tor_retries`
- `metor -p <profile> config set daemon.max_tor_retries 3`

---

#### `daemon.max_connect_retries`

Controls how many additional live connect retries run after the initial attempt.

| Property         | Value            |
| ---------------- | ---------------- |
| Type             | `int`            |
| Default          | `3`              |
| Category         | `Core Daemon`    |
| Scope            | `Daemon runtime` |
| Profile Override | `Yes`            |
| Constraints      | Integer >= 0.    |

**CLI Examples**

- `metor settings get daemon.max_connect_retries`
- `metor settings set daemon.max_connect_retries 3`
- `metor -p <profile> config get daemon.max_connect_retries`
- `metor -p <profile> config set daemon.max_connect_retries 3`

---

#### `daemon.tor_timeout`

Timeout for outbound Tor socket operations and readiness checks.

| Property         | Value                 |
| ---------------- | --------------------- |
| Type             | `float`               |
| Default          | `10.0`                |
| Category         | `Core Daemon`         |
| Scope            | `Daemon runtime`      |
| Profile Override | `Yes`                 |
| Constraints      | Float >= 0.1 seconds. |

**CLI Examples**

- `metor settings get daemon.tor_timeout`
- `metor settings set daemon.tor_timeout 10.0`
- `metor -p <profile> config get daemon.tor_timeout`
- `metor -p <profile> config set daemon.tor_timeout 10.0`

---

#### `daemon.stream_idle_timeout`

Socket read timeout for active live sessions and idle timeout for drop sockets. Active live chats stay connected across pure read timeouts.

| Property         | Value                 |
| ---------------- | --------------------- |
| Type             | `float`               |
| Default          | `60.0`                |
| Category         | `Core Daemon`         |
| Scope            | `Daemon runtime`      |
| Profile Override | `Yes`                 |
| Constraints      | Float >= 0.1 seconds. |

**CLI Examples**

- `metor settings get daemon.stream_idle_timeout`
- `metor settings set daemon.stream_idle_timeout 60.0`
- `metor -p <profile> config get daemon.stream_idle_timeout`
- `metor -p <profile> config set daemon.stream_idle_timeout 60.0`

---

#### `daemon.late_acceptance_timeout`

Window during which pending live sessions may still be accepted.

| Property         | Value               |
| ---------------- | ------------------- |
| Type             | `float`             |
| Default          | `60.0`              |
| Category         | `Core Daemon`       |
| Scope            | `Daemon runtime`    |
| Profile Override | `Yes`               |
| Constraints      | Float >= 0 seconds. |

**CLI Examples**

- `metor settings get daemon.late_acceptance_timeout`
- `metor settings set daemon.late_acceptance_timeout 60.0`
- `metor -p <profile> config get daemon.late_acceptance_timeout`
- `metor -p <profile> config set daemon.late_acceptance_timeout 60.0`

---

#### `daemon.ipc_timeout`

Server-side timeout for daemon IPC sockets.

| Property         | Value                 |
| ---------------- | --------------------- |
| Type             | `float`               |
| Default          | `15.0`                |
| Category         | `Core Daemon`         |
| Scope            | `Daemon runtime`      |
| Profile Override | `Yes`                 |
| Constraints      | Float >= 0.1 seconds. |

**CLI Examples**

- `metor settings get daemon.ipc_timeout`
- `metor settings set daemon.ipc_timeout 15.0`
- `metor -p <profile> config get daemon.ipc_timeout`
- `metor -p <profile> config set daemon.ipc_timeout 15.0`

---

#### `daemon.enable_tor_logging`

Emits Tor process logs to the terminal.

| Property         | Value                                                                         |
| ---------------- | ----------------------------------------------------------------------------- |
| Type             | `bool`                                                                        |
| Default          | `False`                                                                       |
| Category         | `Core Daemon`                                                                 |
| Scope            | `Daemon runtime`                                                              |
| Profile Override | `Yes`                                                                         |
| Constraints      | Boolean.                                                                      |
| Security Note    | Can reveal operational timing and local environment details in terminal logs. |

**CLI Examples**

- `metor settings get daemon.enable_tor_logging`
- `metor settings set daemon.enable_tor_logging false`
- `metor -p <profile> config get daemon.enable_tor_logging`
- `metor -p <profile> config set daemon.enable_tor_logging false`

---

#### `daemon.enable_sql_logging`

Emits SQLCipher and SQLite diagnostics to the terminal.

| Property         | Value                                                          |
| ---------------- | -------------------------------------------------------------- |
| Type             | `bool`                                                         |
| Default          | `False`                                                        |
| Category         | `Core Daemon`                                                  |
| Scope            | `Daemon runtime`                                               |
| Profile Override | `Yes`                                                          |
| Constraints      | Boolean.                                                       |
| Security Note    | Can expose local schema, file, and corruption details in logs. |

**CLI Examples**

- `metor settings get daemon.enable_sql_logging`
- `metor settings set daemon.enable_sql_logging false`
- `metor -p <profile> config get daemon.enable_sql_logging`
- `metor -p <profile> config set daemon.enable_sql_logging false`

---

#### `daemon.enable_runtime_db_mirror`

Exports a plaintext runtime copy of the encrypted database for local inspection tools.

| Property         | Value                                                                                                                  |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Type             | `bool`                                                                                                                 |
| Default          | `False`                                                                                                                |
| Category         | `Core Daemon`                                                                                                          |
| Scope            | `Daemon runtime`                                                                                                       |
| Profile Override | `Yes`                                                                                                                  |
| Constraints      | Boolean.                                                                                                               |
| Security Note    | Creates a plaintext database on disk while enabled. Keep disabled unless you explicitly need local inspection tooling. |

**CLI Examples**

- `metor settings get daemon.enable_runtime_db_mirror`
- `metor settings set daemon.enable_runtime_db_mirror false`
- `metor -p <profile> config get daemon.enable_runtime_db_mirror`
- `metor -p <profile> config set daemon.enable_runtime_db_mirror false`

---

#### `daemon.auto_accept_contacts`

Automatically accepts incoming live sessions from saved contacts.

| Property         | Value                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| Type             | `bool`                                                                                            |
| Default          | `True`                                                                                            |
| Category         | `Core Daemon`                                                                                     |
| Scope            | `Daemon runtime`                                                                                  |
| Profile Override | `Yes`                                                                                             |
| Constraints      | Boolean.                                                                                          |
| Security Note    | Improves convenience for known contacts, but reduces explicit confirmation on inbound reconnects. |

**CLI Examples**

- `metor settings get daemon.auto_accept_contacts`
- `metor settings set daemon.auto_accept_contacts true`
- `metor -p <profile> config get daemon.auto_accept_contacts`
- `metor -p <profile> config set daemon.auto_accept_contacts true`

---

#### `daemon.require_local_auth`

Requires every UI session to authenticate even when the daemon is already running.

| Property         | Value                                                        |
| ---------------- | ------------------------------------------------------------ |
| Type             | `bool`                                                       |
| Default          | `False`                                                      |
| Category         | `Core Daemon`                                                |
| Scope            | `Daemon runtime`                                             |
| Profile Override | `Yes`                                                        |
| Constraints      | Boolean.                                                     |
| Security Note    | Recommended for remote, shared, or physically exposed hosts. |

**CLI Examples**

- `metor settings get daemon.require_local_auth`
- `metor settings set daemon.require_local_auth false`
- `metor -p <profile> config get daemon.require_local_auth`
- `metor -p <profile> config set daemon.require_local_auth false`

---

#### `daemon.allow_drops`

Enables reception and processing of offline drop messages.

| Property         | Value            |
| ---------------- | ---------------- |
| Type             | `bool`           |
| Default          | `True`           |
| Category         | `Core Daemon`    |
| Scope            | `Daemon runtime` |
| Profile Override | `Yes`            |
| Constraints      | Boolean.         |

**CLI Examples**

- `metor settings get daemon.allow_drops`
- `metor settings set daemon.allow_drops true`
- `metor -p <profile> config get daemon.allow_drops`
- `metor -p <profile> config set daemon.allow_drops true`

---

#### `daemon.ephemeral_messages`

Shreds consumed drop-message payloads after they are read instead of retaining them in message history.

| Property         | Value                                                                                                                      |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Type             | `bool`                                                                                                                     |
| Default          | `False`                                                                                                                    |
| Category         | `Core Daemon`                                                                                                              |
| Scope            | `Daemon runtime`                                                                                                           |
| Profile Override | `Yes`                                                                                                                      |
| Constraints      | Boolean.                                                                                                                   |
| Security Note    | Improves local deniability by removing consumed drop content while preserving minimal delivery metadata for deduplication. |

**CLI Examples**

- `metor settings get daemon.ephemeral_messages`
- `metor settings set daemon.ephemeral_messages false`
- `metor -p <profile> config get daemon.ephemeral_messages`
- `metor -p <profile> config set daemon.ephemeral_messages false`

---

#### `daemon.record_live_history`

Persists raw live transport rows in the history ledger and projected summary history.

| Property         | Value                                                         |
| ---------------- | ------------------------------------------------------------- |
| Type             | `bool`                                                        |
| Default          | `True`                                                        |
| Category         | `Core Daemon`                                                 |
| Scope            | `Daemon runtime`                                              |
| Profile Override | `Yes`                                                         |
| Constraints      | Boolean.                                                      |
| Security Note    | Disabling reduces local metadata retention for live sessions. |

**CLI Examples**

- `metor settings get daemon.record_live_history`
- `metor settings set daemon.record_live_history true`
- `metor -p <profile> config get daemon.record_live_history`
- `metor -p <profile> config set daemon.record_live_history true`

---

#### `daemon.record_drop_history`

Persists raw drop transport rows in the history ledger and projected summary history.

| Property         | Value                                                                  |
| ---------------- | ---------------------------------------------------------------------- |
| Type             | `bool`                                                                 |
| Default          | `True`                                                                 |
| Category         | `Core Daemon`                                                          |
| Scope            | `Daemon runtime`                                                       |
| Profile Override | `Yes`                                                                  |
| Constraints      | Boolean.                                                               |
| Security Note    | Disabling reduces local metadata retention for drop delivery attempts. |

**CLI Examples**

- `metor settings get daemon.record_drop_history`
- `metor settings set daemon.record_drop_history true`
- `metor -p <profile> config get daemon.record_drop_history`
- `metor -p <profile> config set daemon.record_drop_history true`

---

#### `daemon.fallback_to_drop`

Falls back unacknowledged live messages into the offline drop queue when possible.

| Property         | Value            |
| ---------------- | ---------------- |
| Type             | `bool`           |
| Default          | `True`           |
| Category         | `Core Daemon`    |
| Scope            | `Daemon runtime` |
| Profile Override | `Yes`            |
| Constraints      | Boolean.         |

**CLI Examples**

- `metor settings get daemon.fallback_to_drop`
- `metor settings set daemon.fallback_to_drop true`
- `metor -p <profile> config get daemon.fallback_to_drop`
- `metor -p <profile> config set daemon.fallback_to_drop true`

---

#### `daemon.max_unseen_live_msgs`

Caps unread crash-safe live backlog per peer. `0` disables headless live backlog, while `-1` removes the limit entirely.

| Property         | Value            |
| ---------------- | ---------------- |
| Type             | `int`            |
| Default          | `20`             |
| Category         | `Core Daemon`    |
| Scope            | `Daemon runtime` |
| Profile Override | `Yes`            |
| Constraints      | Integer >= -1.   |

**CLI Examples**

- `metor settings get daemon.max_unseen_live_msgs`
- `metor settings set daemon.max_unseen_live_msgs 20`
- `metor -p <profile> config get daemon.max_unseen_live_msgs`
- `metor -p <profile> config set daemon.max_unseen_live_msgs 20`

### Advanced Network Resilience

#### `daemon.max_concurrent_connections`

Limits simultaneous authenticated and unauthenticated live sockets handled by the daemon.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `int`                         |
| Default          | `50`                          |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Integer >= 1.                 |

**CLI Examples**

- `metor settings get daemon.max_concurrent_connections`
- `metor settings set daemon.max_concurrent_connections 50`
- `metor -p <profile> config get daemon.max_concurrent_connections`
- `metor -p <profile> config set daemon.max_concurrent_connections 50`

---

#### `daemon.drop_tunnel_idle_timeout`

Controls cached drop tunnel lifetime. `0` disables caching completely.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `float`                       |
| Default          | `30.0`                        |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Float >= 0 seconds.           |

**CLI Examples**

- `metor settings get daemon.drop_tunnel_idle_timeout`
- `metor settings set daemon.drop_tunnel_idle_timeout 30.0`
- `metor -p <profile> config get daemon.drop_tunnel_idle_timeout`
- `metor -p <profile> config set daemon.drop_tunnel_idle_timeout 30.0`

---

#### `daemon.allow_drop_standby_on_live`

Keeps a cached drop tunnel warm while live remains the primary transport.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `bool`                        |
| Default          | `False`                       |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Boolean.                      |

**CLI Examples**

- `metor settings get daemon.allow_drop_standby_on_live`
- `metor settings set daemon.allow_drop_standby_on_live false`
- `metor -p <profile> config get daemon.allow_drop_standby_on_live`
- `metor -p <profile> config set daemon.allow_drop_standby_on_live false`

---

#### `daemon.connect_retry_backoff_delay`

Delay between explicit live connect retries after the initial attempt. `0` retries immediately.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `float`                       |
| Default          | `3.0`                         |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Float >= 0 seconds.           |

**CLI Examples**

- `metor settings get daemon.connect_retry_backoff_delay`
- `metor settings set daemon.connect_retry_backoff_delay 3.0`
- `metor -p <profile> config get daemon.connect_retry_backoff_delay`
- `metor -p <profile> config set daemon.connect_retry_backoff_delay 3.0`

---

#### `daemon.live_reconnect_delay`

Base delay before automatic live reconnect attempts. `0` disables automatic reconnect.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `int`                         |
| Default          | `15`                          |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Integer >= 0 seconds.         |

**CLI Examples**

- `metor settings get daemon.live_reconnect_delay`
- `metor settings set daemon.live_reconnect_delay 15`
- `metor -p <profile> config get daemon.live_reconnect_delay`
- `metor -p <profile> config set daemon.live_reconnect_delay 15`

---

#### `daemon.live_reconnect_grace_timeout`

Reconnect grace window for silently accepting a recent peer reconnect. `0` disables reconnect grace.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `int`                         |
| Default          | `15`                          |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Integer >= 0 seconds.         |

**CLI Examples**

- `metor settings get daemon.live_reconnect_grace_timeout`
- `metor settings set daemon.live_reconnect_grace_timeout 15`
- `metor -p <profile> config get daemon.live_reconnect_grace_timeout`
- `metor -p <profile> config set daemon.live_reconnect_grace_timeout 15`

---

#### `daemon.live_disconnect_linger_timeout`

Keeps a locally initiated live socket open briefly after sending `DISCONNECT` so the control frame can flush through Tor before shutdown. Higher values improve retunnel reliability on slower routes.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `float`                       |
| Default          | `1.0`                         |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Float >= 0 seconds.           |

**CLI Examples**

- `metor settings get daemon.live_disconnect_linger_timeout`
- `metor settings set daemon.live_disconnect_linger_timeout 1.0`
- `metor -p <profile> config get daemon.live_disconnect_linger_timeout`
- `metor -p <profile> config set daemon.live_disconnect_linger_timeout 1.0`

---

#### `daemon.retunnel_reconnect_delay`

Delay before reconnecting after a live retunnel disconnect. `0` reconnects immediately.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `float`                       |
| Default          | `1.0`                         |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Float >= 0 seconds.           |

**CLI Examples**

- `metor settings get daemon.retunnel_reconnect_delay`
- `metor settings set daemon.retunnel_reconnect_delay 1.0`
- `metor -p <profile> config get daemon.retunnel_reconnect_delay`
- `metor -p <profile> config set daemon.retunnel_reconnect_delay 1.0`

---

#### `daemon.retunnel_recovery_retries`

Additional delayed retunnel recovery retries after a transient reject or early close.

| Property         | Value                         |
| ---------------- | ----------------------------- |
| Type             | `int`                         |
| Default          | `2`                           |
| Category         | `Advanced Network Resilience` |
| Scope            | `Daemon runtime`              |
| Profile Override | `Yes`                         |
| Constraints      | Integer >= 0.                 |

**CLI Examples**

- `metor settings get daemon.retunnel_recovery_retries`
- `metor settings set daemon.retunnel_recovery_retries 2`
- `metor -p <profile> config get daemon.retunnel_recovery_retries`
- `metor -p <profile> config set daemon.retunnel_recovery_retries 2`

## Structural Profile Config

### `is_remote`

Marks the profile as a remote client profile instead of a local daemon owner.

| Property               | Value                                      |
| ---------------------- | ------------------------------------------ |
| Type                   | `bool`                                     |
| Default                | `False`                                    |
| Scope                  | `Profile structural config`                |
| Mutable After Creation | `No`                                       |
| Constraints            | Boolean. Immutable after profile creation. |

**CLI Examples**

- `metor profiles add <name> --remote --port <port>`

---

### `daemon_port`

Stores the static IPC port for remote profiles or the current daemon port file value.

| Property               | Value                                          |
| ---------------------- | ---------------------------------------------- |
| Type                   | `Optional[int]`                                |
| Default                | `None`                                         |
| Scope                  | `Profile structural config`                    |
| Mutable After Creation | `Yes`                                          |
| Constraints            | Positive integer between 1 and 65535, or null. |

**CLI Examples**

- `metor -p <profile> config get daemon_port`
- `metor -p <profile> config set daemon_port 50051`

---

### `security_mode`

Declares whether the local profile stores keys and the database encrypted or plaintext at rest.

| Property               | Value                                                                                                                |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Type                   | `Literal['encrypted', 'plaintext']`                                                                                  |
| Default                | `encrypted`                                                                                                          |
| Scope                  | `Profile structural config`                                                                                          |
| Mutable After Creation | `No`                                                                                                                 |
| Constraints            | One of 'encrypted' or 'plaintext'. Immutable after profile creation except through the dedicated migration workflow. |

**CLI Examples**

- `metor profiles add <name> --plaintext`
- `metor profiles migrate <name> --to <encrypted|plaintext>`
