# Metor Architecture Decisions Guide

This document is the canonical architecture guide for the repository.
It records the long-lived design boundaries that should survive feature work, refactors, and UI changes.
Future architecture decisions should extend this file instead of creating separate top-level notes.

## Purpose

Use this document when you need to answer one of these questions:

- Which layer is allowed to own state or side effects?
- Which behaviors should remain configurable, and which should stay hard safety guardrails?
- How should new IPC, transport, or persistence features fit into the existing design?
- Which other repository documents should be updated when architecture changes?

## Document Map

- [README.md](../README.md): Master entry point for installation, usage, and repository navigation.
- [SETTINGS.md](./SETTINGS.md): Generated reference for user-facing settings and structural profile config keys.
- [API.md](./API.md): Generated reference for the typed IPC contract.
- [AUDIT.md](./AUDIT.md): Review checklist for security, OPSEC, concurrency, and architecture risks.
- [CONTRIBUTE.md](./CONTRIBUTE.md): Coding rules, import boundaries, typing requirements, and formatting standards.

## Core System Boundaries

1. The UI is stateless.
   It may hold transient presentation state such as focus or scroll position, but it must not own Tor, database, or cryptographic lifecycle.

2. The daemon owns operational state.
   Tor runtime, live/drop transport state, persistence side effects, and background workers remain daemon responsibilities.

3. The Data layer stays behind daemon or headless orchestration.
   UI code must never read encrypted databases, hidden-service keys, or Tor runtime files directly.

4. Remote profiles are still client profiles.
   UI-local settings remain on the client machine, while daemon settings are routed over IPC to the daemon host.

## Configuration Model

Metor has three configuration classes with different responsibilities:

1. Global cascading settings.
   `metor settings ...` writes global defaults that apply across profiles unless overridden.

2. Profile-specific overrides.
   `metor config ...` writes per-profile overrides for supported `SettingKey` entries.

3. Structural profile config.
   Keys such as `is_remote`, `daemon_port`, and `security_mode` are profile metadata, not ordinary cascading settings.

Configuration should follow these rules:

- User-relevant runtime behavior belongs in documented settings metadata and appears in [SETTINGS.md](./SETTINGS.md).
- Hard anti-DoS and protocol guardrails may stay in constants when exposing them would weaken safety or contract clarity.
- Every persisted setting should have one canonical validator and one canonical documentation source.
- Structural profile metadata must stay immutable through generic `config set` flows; changes such as storage security mode require a dedicated migration workflow.

## IPC Contract Model

The IPC boundary is typed on purpose. Future changes should extend that contract instead of reintroducing string parsing in the UI.

1. UI behavior must branch on `event_type` or explicit structured payload fields.
   Free-form error text may enrich a log line, but it must never be the discriminator for user-visible behavior.

2. Unknown payload fields should be rejected, not silently ignored.
   API drift must fail fast so mismatched clients do not appear to succeed while dropping data.

3. Startup and connection failure paths should stay semantically split.
   Invalid passwords, corrupted databases, Tor runtime-key failures, Tor startup failures, and failed live connects must remain distinct outcomes through unique event types or dedicated payload fields.

4. Alias-bearing peer-state logs should stay rename-safe when the event still refers to the current peer identity.
   In chat mode this means preserving the `{alias}` placeholder together with alias metadata for dynamic redraws, while inherently final events such as completed removals may remain static.

## Security and OPSEC Guardrails

- Passwords must never be accepted through shell arguments or other surfaces that leak into history or process listings.
- Daemon unlock and per-session authentication are separate concerns. Unlock starts the runtime for a locked encrypted profile; `require_local_auth` authenticates each persistent IPC session independently.
- Plaintext runtime mirrors are opt-in diagnostic tools and must be shredded or removed whenever they are disabled or the daemon stops.
- Plaintext profiles intentionally opt out of password-based local auth and encrypted runtime-mirror semantics; those features must degrade to disabled behavior instead of pretending to work.
- Logging of Tor or SQL internals must stay explicit and documented because those logs can leak local operational details.
- Stream framing, byte caps, and socket timeouts are security boundaries, not cosmetic implementation details.

## Transport Model

The following rules describe the transport invariants enforced by the current daemon and chat runtime.
They exist so future work extends one coherent model instead of reintroducing ad-hoc live/drop behavior.

### Core Invariants

1. The daemon owns transport state.
   The UI may choose a peer focus, but it must not infer or manage Tor socket lifecycle directly.

2. Focus is not transport.
   A focused peer is only the selected chat target. Focus may keep a drop tunnel warm, but focus alone never makes a peer live.

3. Each peer has exactly one primary transport.
   Live is the primary transport whenever a peer is connecting, pending, connected, or retunneling.
   Drop may stay available as a standby path only when `daemon.allow_drop_standby_on_live` is enabled.

4. `daemon.drop_tunnel_idle_timeout = 0` means single-drop mode.
   In that mode no cached drop tunnel may survive after a single delivery attempt.

5. Cached drop tunnels close on inactivity, not on arbitrary batch timing.
   `daemon.drop_tunnel_idle_timeout` controls the idle close window for unfocused peers.
   Focused peers may keep their drop tunnel alive until focus is removed or transport policy closes it.

6. Retunnel is a peer-level transport operation.
   `/retunnel` emits a retunnel lifecycle (`initiated`, then `success` or `failed`) instead of generic disconnect/connect noise when the flow succeeds.

7. A successful retunnel only completes when the new route is ready.
   For live, success is emitted after the new live session is established.
   For drop, success is emitted after the cached drop route was discarded and Tor circuit rotation completed.

8. Terminal timeline ordering is receive-order only.
   The terminal chat may show timestamps for live and drop messages, but it must not reorder buffered output by timestamp.

9. The daemon owns message timestamps.
   Live and drop payloads may be rendered optimistically in the terminal, but daemon-authored timestamps remain the canonical values exposed over IPC.

10. Delivery ACK is not a read receipt.
    A sender-side ACK only means the peer daemon durably accepted the logical message. Read state is a separate local consume action.

11. Every logical message keeps one stable identifier across transports.
    Live, drop, fallback, and retry paths must reuse the same `msg_id` so duplicate deliveries stay idempotent.

12. Inbound live delivery is crash-safe but not normal chat history.
    Live payloads must be durably spooled before ACK, then shredded on explicit consume while retaining only minimal dedupe metadata. They do not become ordinary visible chat-history rows by default.

### Transport Settings

- `daemon.drop_tunnel_idle_timeout`
  Controls drop tunnel caching with one numeric value. A value of `0` disables caching and forces single-drop delivery. A value `> 0` keeps an unfocused cached drop tunnel alive for that many idle seconds.

- `daemon.allow_drop_standby_on_live`
  Controls whether a cached drop tunnel may remain warm while live is the primary transport. It does not reroute drop items into the live tunnel.

- `daemon.max_unseen_live_msgs`
  Caps the unread crash-safe live backlog per peer. When the limit is reached, new inbound live messages stop ACKing so the sender's existing fallback policy can take over. A value of `0` disables headless live backlog and only allows automatic live acceptance while an interactive live consumer is attached. A value of `-1` removes the limit entirely.

- `ui.inbox_notification_delay`
  Buffers and aggregates unread-message notification lines locally for unfocused peers. This is a UI-only presentation setting and does not affect daemon read state or transport behavior.

## Transport Shared State Model

The single source of truth for peer transport state is the daemon `StateTracker`.
It combines:

- live transport lifecycle
- cached drop tunnel presence
- retunnel flow markers
- UI focus reference counts

The outbox worker and the network stack must both read and write this shared state.

## Transport Default Policy

- Live wins over drop.
- Cached drop standby while live is active is disabled by default.
- Retunnel success/failure is transport-specific and explicit.
- The chat UI renders focus independently from transport state and only decorates the prompt based on the current primary route.

## Extending the Architecture

When you add a new architecture-relevant behavior:

1. Decide whether it belongs in fixed guardrails, cascading settings, or structural profile config.
2. Extend the typed IPC contract if the UI must observe or control it.
3. Update [SETTINGS.md](./SETTINGS.md) or [API.md](./API.md) via the generators instead of hand-editing generated references.
4. Update [AUDIT.md](./AUDIT.md) and [CONTRIBUTE.md](./CONTRIBUTE.md) if the new behavior changes review or implementation rules.
