# Embedded UI Core Contract

This document defines the frontend-neutral Core boundary that a future Embedded
UI must consume. It does not define or implement screens, navigation, playback,
hardware drivers, or other presentation behavior. The Terminal remains an equal
client of the same typed contract.

## Ownership boundary

- Core owns profiles, identity, contacts, message identity, DROP/LIVE semantics,
  persistence, ACK/dedupe, transport recovery, fallback, authentication,
  resource limits, and typed runtime facts.
- `metor.client` owns IPC connection/bootstrap orchestration and the safe profile
  transition coordinator.
- A frontend owns navigation, focus projection, drafts, scroll and playback
  cursors, wording, notification presentation, and bounded volatile copies of
  already-consumed LIVE content.
- The platform layer owns capture/playback, echo cancellation, display, hardware
  input, LEDs, haptics, camera, and physical power control.

Opening a view is never a network action. A frontend must issue explicit typed
commands for connect, reconnect, fallback, accept, reject, disconnect, consume,
or dismiss behavior.

## Attach and race-safe recovery

After the normal IPC version/auth handshake, a rich frontend must:

1. send `RegisterLiveConsumerCommand` so it receives typed asynchronous events;
2. request `GetRuntimeSnapshotCommand`;
3. install `RuntimeSnapshotEvent` as its projection baseline;
4. apply only buffered or later events whose `revision` is greater than the
   snapshot revision.

Every IPC event carries the daemon-authored monotonic `revision`. The aggregate
snapshot contains profile and Onion identity, saved/discovered contacts,
content-free DROP conversation summaries, LIVE contexts, pending incoming
requests, unread and pending counts, disconnect reason, and settings revision.
It deliberately excludes message content and UI-only state.

## Messaging contract

The stable logical shape is `MessageContent + Delivery + msg_id`.

- `Delivery.LIVE` is ephemeral interactive content. It may use crash-safe Core
  spool state while unseen or awaiting ACK, but it is not chat history.
- `Delivery.DROP` is durable mailbox content retained until explicit deletion or
  configured shredding.
- `TextContent` and `VoiceContent` are members of the same typed content union.
- One Voice press is one logical message with one immutable `msg_id`; bounded
  chunks and resume offsets are transport/application details beneath it.
- ACK confirms durable peer acceptance, not that a person read the content.
  Remote read receipts are optional and default to disabled.

`FallbackCommand(target, msg_ids=None)` preserves Terminal's peer-wide fallback.
Supplying IDs selects an atomic subset of pending outbound LIVE messages. A
successful fallback preserves each `msg_id`, removes it from LIVE replay, and
promotes the complete content to DROP. A malformed, cross-peer, non-pending, or
already-promoted selection is rejected without partial changes.

`MarkReadCommand(target, delivery=None)` preserves the combined Terminal consume
flow. Rich clients should supply `DROP` or `LIVE` when projections are separate.
Only the selected unread rows are consumed. `ClearMessagesCommand` and
`DeleteMessageCommand` affect only eligible local DROP presentation/payload
state; pending DROP delivery and all LIVE state remain intact.
`DismissLiveContextCommand` is the explicit cleanup action for a disconnected,
non-recovering LIVE context and is rejected while outbound pending LIVE content
still needs reconnect or fallback.

### Voice capture and transfer

A capturing frontend uses `BeginVoiceCommand`, zero or more
`AppendVoiceChunkCommand` calls with exact byte offsets and bounded Base64
chunks, then `FinalizeVoiceCommand` for the same `msg_id`. Core permanently binds
the turn to its begin-time target. Connection loss does not finalize it; recovery
resumes after the peer-confirmed offset. Text and Voice remain full-duplex.

Core applies a finite profile-aware retained Voice budget. It emits typed
pressure and hard-limit events, finalizes the current turn at the hard boundary,
never overwrites older chunks, and rejects new turns while capacity is full.
Finalized pending LIVE Voice follows the same reconnect and selective/automatic
fallback rules as text. Once a frontend consumes unseen LIVE Voice, Core may
shred its owned spool; the frontend may retain only a bounded volatile copy.

## Restricted client/session lock

`LockCommand` remains the hard profile-runtime lock: it releases database, Tor,
blob, identity, and key runtime state. It is not a device screen lock.

`RestrictClientCommand` restricts only its requesting authenticated IPC session.
Its immutable lock-cycle policy selects:

- `unlock_method`: `PIN`, `PROFILE_PASSWORD`, or `NONE`;
- an optional continued LIVE target and whether locked Voice is allowed;
- incoming acceptance policy: `ALL`, `SAVED_CONTACTS`, or `NONE`;
- notification privacy: `SHOW_ALL`, `ANONYMIZE`, or `OFF`.

Restricted clients cannot read normal contacts/history/messages/settings or send
to arbitrary targets. Reject is permitted; accept and locked Voice are checked
against the fixed policy in Core. Other authenticated clients, including a
Terminal session, remain unaffected. An anonymized restricted client receives
no peer identity/saved-status disclosure, and `OFF` suppresses unsolicited
presentation metadata. Locked notifications never carry message content.

Quick unlock stores a salted Argon2id-derived verifier, never a PIN or profile
encryption key. Proofs are bound to one-use challenges. After three failed PIN
attempts in one lock cycle, only the profile-password proof can reauthorize that
session; successful password recovery restores PIN eligibility for the next
normal cycle. PIN never starts a cold or hard-locked profile.

## Profile lifecycle and power

`ProfileRuntimeCoordinator` is the client-layer profile-switch boundary. A
frontend may inspect the current snapshot and must finalize platform-owned
capture before switching. The coordinator then requests
`PrepareProfileExitCommand`, disconnects the old client, attaches/authenticates
the selected profile, and returns a fresh aggregate snapshot. Normal preparation
durably applies configured eligible fallback, does not wait for remote DROP
delivery, terminates LIVE sessions, and hard-locks the old runtime. When fallback
is disabled, pending LIVE data remains recoverable and is not auto-reconnected
on a later return.

Self-destruct is a separate emergency path. Once accepted, it preempts Voice
finalization, fallback, reconnect, outbox delivery, and ordinary notification
work. Core aborts reliability workers, destroys protected key access before
best-effort storage cleanup, then emits `SelfDestructCompletedEvent`. A platform
must not cut power merely on `SelfDestructInitiatedEvent`.

## Privacy and compatibility rules

- Never derive behavior by parsing human-readable strings; branch on typed event
  classes/enums and structured fields.
- Never place message text, Voice bytes, or previews in runtime snapshots,
  notification metadata, or detached notification sinks.
- Respect `daemon.ephemeral_messages`, history retention settings, and
  `daemon.send_read_receipts` in every frontend.
- Treat Onion identity and `msg_id` as stable keys; aliases are mutable labels.
- Render unknown `MessageContent` variants safely. Terminal intentionally uses a
  placeholder for Voice and remains a text-oriented client.

The complete wire shapes and defaults are generated in
[API.md](../generated/API.md) and [SETTINGS.md](../generated/SETTINGS.md).
