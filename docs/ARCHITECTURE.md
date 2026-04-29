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

## History Model

History is intentionally split into two views owned by the daemon:

1. Raw transport ledger.
   The persisted `history` table stores `family`, `event_code`, `peer_onion`, `actor`, `trigger`, `detail_code`, `detail_text`, and `flow_id` for each retained transport row.

2. Projected summary history.
   The default history IPC path projects concise user-facing rows from that raw ledger before the UI renders them.

History changes should follow these rules:

- Summary history is derived in the daemon, not reconstructed in the UI from low-level transport noise.
- `history --raw` is the explicit diagnostics path for the raw transport ledger; plain `history` remains the user-facing summary view.
- `daemon.record_live_history` and `daemon.record_drop_history` gate retention at the raw-ledger layer. If retention is disabled, no downstream summary rows may be invented.
- `flow_id` correlates related raw rows without forcing the UI to infer transport semantics from timing alone.
- `family` is explicit in storage and IPC. The UI must not rediscover live vs drop by parsing string prefixes.
- History-specific CLI parsing and presentation belong in the dedicated dispatcher and presenter packages behind their stable facades, so new history behavior does not regrow monolith files.

## Security and OPSEC Guardrails

- Passwords must never be accepted through shell arguments or other surfaces that leak into history or process listings.
- Daemon unlock and per-session authentication are separate concerns. Unlock starts the runtime for a locked encrypted profile; `require_local_auth` authenticates each persistent IPC session independently and also gates offline headless daemon-scoped control requests for encrypted local profiles.
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

## Live Reconnect and Retunnel Recovery Model

This section is the canonical reference for how live-session recovery works.
It exists to keep reconnect, retunnel, fallback, and durable pending-live handling in one coherent model instead of splitting the behavior across tests, transport code, and prompt translations.

### State Ownership and Sources of Truth

1. The daemon owns transport truth.
   `StateTracker` tracks active live sockets, pending live sockets, outbound attempts, reconnect-grace windows, scheduled auto-reconnect intent, retunnel markers, and the in-memory mirror of per-peer pending live messages.

2. Durable pending outbound live state is daemon-owned too.
   The message store retains outbound `LIVE_TEXT` rows with `PENDING` status until ACK, terminal fallback conversion, or explicit manual fallback. That durable spool is the crash-safe source for recoverable live sends.

3. Live lifecycle state is derived, not stored redundantly.
   For each peer the daemon derives one `LiveTransportState`: `DISCONNECTED`, `CONNECTING`, `PENDING`, `CONNECTED`, or `RETUNNELING`.

4. The chat UI owns presentation-only transport state.
   The UI may mark one peer as `LIVE`, `SWITCHING`, `RECONNECTING`, or `DROP`, but that state is only a rendering/send-policy mirror driven by typed IPC events.

5. The UI does not own a recoverable outgoing buffer.
   When the user types while the chat still routes through live semantics, the UI sends `MsgCommand` immediately and renders a pending self-message. Whether that message is sent now, durably deferred, replayed after recovery, or promoted to drop is daemon logic.

6. `StateTracker` keeps only the fast in-memory replay mirror.
   The in-memory pending-live map exists to replay over the current process without rereading SQLite for every ACK or replay step, but it is not the sole source of truth.

7. The UI must never infer recovery from time or socket silence.
   It reacts only to typed IPC transport events, fallback events, and ACK events.

### Recovery Origins and Their Meaning

- `MANUAL` means the local user explicitly started or stopped the flow.
- `INCOMING` means the peer initiated a normal incoming live session.
- `GRACE_RECONNECT` means a generic recovery replacement path was accepted. The passive peer must treat it as generic recovery and must not infer whether the remote side used retunnel, reconnect, or another internal recovery trigger.
- `RETUNNEL` means the local daemon is executing the user-requested retunnel flow. It is a local transport-maintenance semantic, not something the passive peer derives from generic recovery hints.
- `AUTO_RECONNECT` means the daemon-owned reconnect worker is trying to recover a lost live session.
- `MUTUAL_CONNECT` means both peers initiated a connection simultaneously and the tie-breaker chose one winner.
- `AUTO_ACCEPT_CONTACT` means an incoming request was auto-accepted because policy allowed it.

These origins are semantic, not cosmetic. The daemon uses them for state transitions, history projection, and typed IPC.
The UI may translate them differently, but it must not reinterpret them.

### Normal Outbound Live Connect

1. `connect_to()` resolves the peer, registers an outbound attempt, and emits `ConnectionConnectingEvent`.

2. The outbound socket completes the challenge-response handshake.
   Until the peer replies with `PENDING` or `ACCEPTED`, that socket is an outbound attempt, not an active live session.

3. If the peer replies with `PENDING`, the receiver emits `ConnectionPendingEvent` and keeps the socket under late-acceptance timeout.

4. If the peer replies with `ACCEPTED`, the receiver promotes the socket to active live state, clears reconnect/scheduled flags, logs the connection, and emits `ConnectedEvent`.

5. If the successful connection was reserved as the completion of a retunnel flow, the daemon emits `RetunnelSuccessEvent` instead of a generic `ConnectedEvent` on the initiating side.

6. After the new socket becomes active, the daemon replays any retained unacknowledged live messages over that socket.

### Incoming Connect, Tie-Break, and Replacement Rules

1. The listener evaluates every authenticated incoming socket against the current peer transport state.

2. If the peer is already `CONNECTED` or `PENDING` and there is no reconnect grace, no retunnel marker, no scheduled auto reconnect, and no generic recovery hint, the incoming socket is treated as a duplicate and rejected.

3. If both peers initiated a connection simultaneously, the deterministic tie-breaker decides the winner.
   The loser is rejected with `MUTUAL_CONNECT` semantics instead of appearing as a random failure.

4. If reconnect grace, retunnel recovery, scheduled auto reconnect, or a generic recovery hint corroborated by current local recovery state is present, the listener may auto-accept the incoming socket as a recovery replacement.

   If the passive peer explicitly opts out during that window by using `/end` or `/reject`, the retunneling side must surface that as one terminal peer-ended outcome, not as a generic `connection lost` transport failure.

5. If the replacement arrives while the old live socket is still tracked as connected, the listener treats that as a seamless recovery replacement.
   In that special case it suppresses duplicate generic connect history, keeps the passive side on generic recovery semantics, and may complete quietly enough that the passive UI only sees the final `ConnectedEvent` instead of a transient `ConnectionConnectingEvent`.

6. A successful seamless recovery replacement is not a terminal fallback point.
   Retained pending live messages must stay recoverable and replay over the replacement socket. Forcing them into drops on recovery success is a semantic error.

7. A recovery replacement is only auto-accepted when live delivery is allowed now.
   If there is no interactive live consumer and headless live backlog is disabled, the socket remains pending even if its semantic origin is recovery-related.
   A previously expired or explicitly rejected pending request is not implicit consent for a later recovery hint.
   A recent explicit local `/end` or `/reject` is likewise a temporary local opt-out: a later incoming socket with a generic recovery hint must be rejected silently instead of reopening an inbound prompt or contact auto-accept path.

### Remote Disconnect and Deferred Fallback

1. The daemon only enters deferred remote fallback for recoverable loss.
   Explicit peer `/end` remains terminal, while raw transport loss or a peer disconnect frame tagged as recoverable replacement enters the fallback path with `initiated_by_self = False` and `is_fallback = True`.

2. If `daemon.live_reconnect_grace_timeout > 0`, the daemon enters deferred remote fallback instead of immediately treating the loss as final.

3. Deferred remote fallback performs these steps:
   it closes the old socket, marks reconnect grace, retains already-sent unacknowledged live messages, emits `ConnectionConnectingEvent(origin = GRACE_RECONNECT)`, and delays the visible `DisconnectedEvent`.

4. If a replacement socket arrives before grace expires, the delayed worker exits quietly.
   The peer only sees generic reconnect lifecycle, not a disconnect followed by a fresh incoming request.

5. If grace expires without recovery, the daemon emits `DisconnectedEvent` and cleans up orphaned contacts.

6. If `daemon.live_reconnect_delay > 0`, the daemon then schedules `AUTO_RECONNECT`.

7. If `daemon.live_reconnect_delay = 0`, the daemon does not schedule a reconnect worker.
   The current design still keeps retained unacknowledged live messages instead of converting them immediately at grace expiry, because a hinted late recovery replacement may still arrive and replay them.

### Automatic Live Reconnect

1. Automatic reconnect is daemon-owned only.
   It uses `daemon.live_reconnect_delay`, `daemon.max_connect_retries`, and `daemon.connect_retry_backoff_delay`.

2. When auto reconnect is scheduled, the daemon emits `AutoReconnectScheduledEvent` and the chat UI moves into `RECONNECTING` state.

3. The reconnect worker later calls the normal outbound `connect_to()` path with `origin = AUTO_RECONNECT`.

4. Successful auto reconnect behaves like a normal successful connect, except the origin remains `AUTO_RECONNECT` and the UI renders it as reconnect lifecycle rather than as a first connect.

5. Terminal auto-reconnect failure is one of the explicit terminal points for retained unacknowledged live messages.
   When retries are exhausted, the outbound attempt is rejected, or the attempt closes before acceptance, the daemon converts retained unacknowledged live messages to drops and then emits `ConnectionFailedEvent`.

### Explicit Local Retunnel

1. `/retunnel` is a local transport-maintenance operation.
   The initiating UI receives `RetunnelInitiatedEvent`, `RetunnelSuccessEvent`, or `RetunnelFailedEvent`.

2. Retunnel is not allowed to tear down the old live session before Tor circuit rotation succeeds.
   If circuit rotation fails, the daemon emits a retunnel failure and leaves the old live socket intact.

3. After successful circuit rotation, the daemon marks the peer as retunneling, marks that the next successful live connection should finalize retunnel, disconnects the old live socket silently, marks reconnect grace, waits `daemon.retunnel_reconnect_delay`, and then starts a reconnect attempt with `origin = RETUNNEL` unless recovery already happened.

4. A successful retunnel completes only when a replacement live route is active.
   On the initiating side that completion is surfaced as `RetunnelSuccessEvent`, not as generic connect noise.
   The passive peer remains on generic recovery semantics (`GRACE_RECONNECT` or the final generic connected state) and must not infer retunnel from the recovery itself.

5. If the reconnect attempt fails while the old live socket is still active, the daemon emits `RetunnelFailedEvent` but preserves the old live session.

6. If the old live socket is already gone, the daemon may schedule bounded delayed recovery retries using `daemon.retunnel_reconnect_delay` and `daemon.retunnel_recovery_retries` before declaring terminal failure.
   Explicit peer rejection of the retunnel reconnect is terminal: it clears retunnel state immediately, converts retained pending live messages to drops, and must not hand off into further retunnel retries or generic auto reconnect.

7. If retunnel becomes terminal after the old live path is gone, the daemon emits `DisconnectedEvent(origin = RETUNNEL)` plus `RetunnelFailedEvent` locally.
   If auto reconnect is enabled it schedules `AUTO_RECONNECT`; otherwise it converts retained unacknowledged live messages to drops.

### Message Retention, Replay, and Drop Conversion

1. Recoverable outbound live delivery is daemon-owned.

2. Every outbound live message is persisted as durable pending live state before or instead of transport send.
   If a live socket is active, the daemon stores the message as pending live and sends it immediately. If no live socket is active but recovery is still plausible, the daemon stores the same pending live row without auto-converting it to drop.

3. The UI prompt is not the buffer contract.
   Prompt tags like `[Reconnecting]` or `[Switching]` are only presentation. Buffering and replay must still work when those tags never become visibly stable because recovery finished inside one seamless socket swap.

4. `StateTracker` mirrors pending live messages in memory for fast replay and ACK removal inside the running daemon.
   The durable message store remains the crash-safe copy for restart and shutdown scenarios.

5. When a recovered live socket becomes active, the daemon hydrates any durable pending live rows for that peer into `StateTracker` and replays them over the active socket.

6. ACK is the only normal success point for outbound live retention.
   When the peer ACKs one message, the daemon clears the in-memory pending-live entry, marks the durable outbound receipt as `DELIVERED`, and removes it from the live outbox spool.

7. Terminal conversion to drop is intentionally narrower than generic disconnect handling.
   Pending live messages should survive recoverable grace, retunnel, and auto-reconnect paths and only become drops when the daemon concludes that the live recovery path is terminal or when the user explicitly forces fallback.

8. Clean daemon shutdown is also a terminal decision point.
   If `daemon.fallback_to_drop` is enabled, the daemon finalizes any remaining durable pending live rows into `DROP_TEXT` before shutdown. If fallback-to-drop is disabled, those durable pending live rows remain pending for a future live recovery.

9. A seamless replacement over a still-connected old socket is still a recovery success.
   It must preserve retained pending live messages and replay them over the replacement socket rather than forcing fallback because the swap happened quickly.

10. ACK remains transport acceptance, not a read receipt.
    A green sender-side message means the peer daemon accepted the logical message durably, not that the peer user read it.

### Chat UI Recovery Semantics

1. `SWITCHING` means a local retunnel is in progress.
   The user may keep typing, but new outgoing messages remain local until the daemon reports retunnel success or terminal failure.

2. `RECONNECTING` means the daemon is recovering a lost live session through grace reconnect or auto reconnect.
   The prompt changes immediately, but the UI still waits for typed IPC events before deciding whether to flush or drop buffered content.

3. `DROP` means live transport is unavailable now.
   New outgoing messages no longer stay in the UI buffer and instead follow normal drop behavior.

4. Recovery prompt state and transport history state are intentionally coupled but not identical.
   Prompt decoration reacts immediately to typed lifecycle events, while visible chat lines such as `FallbackSuccessEvent`, `AckEvent`, and drop conversions continue to reflect daemon transport truth.

### OPSEC Rules for Recovery

1. Peer-visible retunnel disclosure is intentionally disabled.
   The remote peer must not learn whether a replacement live socket was caused by `/retunnel`, automatic reconnect, or another local recovery decision.

2. The only peer-visible recovery semantics should be generic reconnect behavior.
   On the non-initiating side, reconnect lifecycle must surface as generic `GRACE_RECONNECT` messaging such as `Reconnecting` and `Reconnected`, not as explicit retunnel disclosure.

3. A generic recovery hint in the authenticated live handshake is acceptable only as a corroborating signal.
   It may help the listener classify a new socket as a recovery replacement, but it must not override the absence of local recovery evidence such as reconnect grace, scheduled auto reconnect, retunnel state, or a recent explicit local opt-out.

4. Local observability is allowed to be richer than peer observability.
   The initiating UI may see `RetunnelInitiatedEvent`, `RetunnelSuccessEvent`, and `RetunnelFailedEvent` because that information never crosses the peer protocol boundary.

5. Timing settings are not only UX knobs; they are part of the OPSEC and recovery contract.
   `daemon.live_reconnect_grace_timeout`, `daemon.live_reconnect_delay`, `daemon.live_disconnect_linger_timeout`, `daemon.retunnel_reconnect_delay`, and `daemon.retunnel_recovery_retries` together define whether recovery looks seamless, noisy, or terminal.

### Recommended Recovery Tuning

For slower Tor routes or environments where retunnel replacement can legitimately take longer than the default grace window, prefer one coherent profile instead of tweaking one timeout in isolation.

1. Set `daemon.live_reconnect_grace_timeout` above the observed worst-case retunnel replacement time.
   If retunnel recovery often takes around 15 to 20 seconds end to end, use 25 to 30 seconds so the passive peer stays in generic reconnect grace instead of surfacing a premature disconnect-plus-auto-reconnect schedule.

2. Keep `daemon.retunnel_reconnect_delay` short.
   Values around 1 to 2 seconds are usually enough to let the controlled disconnect flush while still letting retunnel recovery start promptly.

3. Keep `daemon.live_disconnect_linger_timeout` non-zero on slower routes.
   Around 1.0 to 1.5 seconds usually improves in-band disconnect delivery and reduces duplicate-live races during retunnel.

4. Treat `daemon.live_reconnect_delay` as the safety-net delay, not the main retunnel knob.
   It only matters after grace expires and no recovery won. Typical values around 10 to 15 seconds are reasonable; the key anti-noise control is still the grace timeout.

5. Increase `daemon.retunnel_recovery_retries` only when transient reject or early-close races are common.
   A small budget such as 2 or 3 retries is appropriate. Higher values make recovery more persistent but can also prolong a terminal failure.

6. Change the settings together and validate with real logs.
   The target symptom profile is: peer sees `Reconnecting` then `Reconnected`, no premature `Automatic reconnect scheduled`, and retained unacknowledged live messages replay after recovery instead of converting to drops.

### Edge-Case Rules That Must Remain Stable

1. Mutual connect races must never tear down a newer winning socket because of stale callbacks from the losing socket.

2. Duplicate incoming live sockets must be rejected unless reconnect grace, retunnel recovery, scheduled auto reconnect, or the generic recovery hint makes the replacement legitimate.

3. Pending live sockets use late-acceptance timeout, even during reconnect flows.
   A reconnect that never reaches `ACCEPTED` is still a failure path and must not stay pending forever.

4. If the local daemon has no live socket when sending and `daemon.fallback_to_drop` is enabled, new outbound messages may queue directly as drops.
   During reconnect grace, the daemon may suppress the immediate auto-fallback status line to keep the transient remote loss visually quiet.

5. Retunnel recovery and auto reconnect are separate machines.
   Retunnel may hand off into auto reconnect after terminal retunnel failure, but the two flows must not collapse into indistinguishable controller state.

## Extending the Architecture

When you add a new architecture-relevant behavior:

1. Decide whether it belongs in fixed guardrails, cascading settings, or structural profile config.
2. Extend the typed IPC contract if the UI must observe or control it.
3. Update [SETTINGS.md](./SETTINGS.md) or [API.md](./API.md) via the generators instead of hand-editing generated references.
4. Update [AUDIT.md](./AUDIT.md) and [CONTRIBUTE.md](./CONTRIBUTE.md) if the new behavior changes review or implementation rules.
