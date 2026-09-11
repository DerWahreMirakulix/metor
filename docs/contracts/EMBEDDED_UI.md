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

The daemon also assigns a fresh opaque `epoch` at each start. Clients reset
revision ordering when the epoch changes. `RuntimeSnapshotUnavailableEvent`
means the bounded stable-read retries were exhausted and the request is safe to
retry; it is never an unchecked snapshot. The client IPC layer owns the only
socket reader, registers a request before writing it, demultiplexes correlated
responses, and queues unsolicited events without loss. A shared
`RuntimeStateChangedEvent` has no request correlation and invalidates only its
content-free scope for every authorized client. Connection and pending-request
events are absolute keyed upserts, not counters to apply more than once.

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
Only selected unread text rows are consumed; Voice has its own handoff contract.
`ClearMessagesCommand` and direction-qualified `DeleteMessageCommand` affect
only eligible local DROP presentation/payload state; an omitted direction is
rejected when inbound and outbound receipts share the same peer and `msg_id`.
Pending DROP delivery and all LIVE state remain intact.
`DismissLiveContextCommand` is the explicit cleanup action for a disconnected,
non-recovering LIVE context and is rejected while outbound pending LIVE content
still needs reconnect or fallback.

### Voice capture and transfer

A capturing frontend uses `BeginVoiceCommand`, zero or more
`AppendVoiceChunkCommand` calls with exact byte offsets and bounded Base64
chunks, then `FinalizeVoiceCommand` for the same `msg_id`. Core permanently binds
the turn to its begin-time target. Connection loss does not finalize it; recovery
resumes after the peer-confirmed offset. Text and Voice remain full-duplex.

For DROP Voice, finalize creates a non-visible `DRAFT`. The frontend must issue
`CommitVoiceCommand` to publish it or `CancelVoiceCommand` to shred it. Incoming
or retained Voice is read only through bounded `GetVoiceChunkCommand` /
`VoiceDataEvent` ranges. After a safe playback handoff, the client explicitly
issues `ReleaseVoiceCommand`; reads never consume content implicitly.

Peer wire generation 3 separates `/ack` (LIVE text), `/drop_ack` (DROP text),
`/voice_ack <id> <offset>` (resumable progress), and
`/voice_commit_ack <id>` (terminal Voice durability). A sender retains every
Voice segment until the terminal commit ACK. Duplicate matching chunks and END
frames are idempotent; conflicting bytes or offsets are malformed peer frames.

Core applies finite profile-aware retained Voice and shared pending-LIVE count /
byte budgets transactionally across text and Voice. It emits typed pressure and
hard-limit events, finalizes the current turn at the hard boundary, stores each
chunk as one bounded append-only encrypted object, never rewrites older chunks,
and rejects new turns while capacity is full.
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
- `device_lifecycle`, granted only to a session authenticated before restriction.

Restricted clients cannot read normal contacts/history/messages/settings or send
to arbitrary targets. Reject is permitted; accept and locked Voice are checked
against the fixed policy in Core. Other authenticated clients, including a
Terminal session, remain unaffected. An anonymized restricted client receives
no peer identity/saved-status disclosure, and `OFF` suppresses unsolicited
presentation metadata. Multiple anonymous incoming calls use distinct opaque
action handles so accept/reject and expiry remain actionable without disclosing
identity. Locked notifications never carry message content. Locked Voice is
limited to the fixed continued LIVE target independently of notification
privacy; unrelated or DROP media is never exposed.

Quick unlock stores a salted Argon2id-derived verifier, never a PIN or profile
encryption key. The verifier is itself a usable authentication credential and
must stay inside the profile protection boundary with owner-only permissions.
Proofs are bound to one-use challenges. Password retries share the daemon-wide
failure counter and cooldown, including after reconnect or PIN escalation. A
Forgot PIN action requests a fresh password-salt challenge without fabricating
a failed attempt. After three failed PIN
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

Self-destruct is a separate emergency path. Hard-locked anonymous clients cannot
invoke it; a previously authenticated restricted session needs the explicit
`device_lifecycle` capability. Once accepted, it preempts Voice
finalization, fallback, reconnect, outbox delivery, and ordinary notification
work. Core aborts reliability workers and attempts protected-key destruction
even if nonessential runtime preparation fails. It emits
`SelfDestructKeyDestroyedEvent` at the irreversible milestone, then performs
best-effort profile-scoped cleanup. `SelfDestructCleanupFailedEvent` identifies
the failed `preparation`, `key_destruction`, or `cleanup` phase and truthfully
states whether the key was destroyed. `SelfDestructCompletedEvent` follows only
complete cleanup. A platform must not cut power merely on
`SelfDestructInitiatedEvent`.

Purge affects only the selected profile. Ordinary exit never purges: it converts
eligible pending LIVE text and Voice to DROP when fallback is enabled, otherwise
retains them as pending LIVE, does not wait for delivery, and does not recreate
an automatic reconnect intent when the profile is next opened.

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

## Acceptance regression map

The following executable checks pin the cross-layer invariants. Test names are
stable evidence labels; the full suite remains the final regression boundary.

| Gate | Implementation invariant                                                          | Primary regression evidence                                                                                                                                                                   |
| ---- | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G01  | Fresh DROP Voice begins at offset zero and completes with a commit ACK.           | `test_fresh_drop_voice_completes_first_attempt_empty_and_nonempty`                                                                                                                            |
| G02  | Text replay/ACK paths cannot reinterpret or complete Voice.                       | `test_common_replay_keeps_text_and_voice_frames_typed`; `test_generic_text_ack_cannot_complete_voice_identity`                                                                                |
| G03  | Resume offsets are monotonic and matching duplicate chunks are idempotent.        | `test_duplicate_chunk_is_idempotent_but_conflict_is_malformed`; `test_progress_ack_never_releases_before_terminal_commit`                                                                     |
| G04  | Progress and terminal durability ACKs are distinct; DROP drafts need commit.      | `test_duplicate_end_repeats_terminal_commit_ack`; `test_drop_voice_draft_requires_commit_and_can_be_cancelled`                                                                                |
| G05  | LIVE-to-DROP receiver promotion retains the same logical identity and bytes.      | `test_partial_live_promotes_to_drop_with_same_identity_and_full_bytes`                                                                                                                        |
| G06  | Stale LIVE control frames cannot falsely complete promoted DROP work.             | `test_generic_text_ack_cannot_complete_voice_identity`; `test_partial_live_promotes_to_drop_with_same_identity_and_full_bytes`                                                                |
| G07  | Encrypted object ownership reconciles after interrupted SQL/blob promotion.       | `test_interrupted_encrypted_blob_promotion_reconciles_on_restart`                                                                                                                             |
| G08  | Public bounded IPC reads expose retained Voice after reattach.                    | `test_public_bounded_read_precedes_explicit_release`                                                                                                                                          |
| G09  | Voice release is explicit and incomplete media survives text consume.             | `test_public_bounded_read_precedes_explicit_release`; `test_text_consume_and_live_dismiss_preserve_other_voice_state`                                                                         |
| G10  | Focused text consumption does not abort simultaneous Voice.                       | `test_text_consume_and_live_dismiss_preserve_other_voice_state`                                                                                                                               |
| G11  | LIVE dismissal does not remove simultaneous DROP Voice.                           | `test_text_consume_and_live_dismiss_preserve_other_voice_state`                                                                                                                               |
| G12  | Text and Voice share atomic count/byte admission limits.                          | `test_atomic_mixed_pending_count_quota_admits_only_one`; `test_voice_byte_quota_rejects_growth_without_partial_storage`                                                                       |
| G13  | Segmented storage is linear and peer I/O is independently scheduled.              | `test_segment_storage_is_linear_and_socket_frames_do_not_interleave`; `test_slow_voice_peer_does_not_stall_another_peer`                                                                      |
| G14  | Every application frame has one per-socket serialized writer.                     | `test_segment_storage_is_linear_and_socket_frames_do_not_interleave`                                                                                                                          |
| G15  | DROP-disabled policy covers session and tunnel-carried Voice.                     | `test_drop_disabled_rejects_voice_before_receipt_on_session`; DROP tunnel contract suite                                                                                                      |
| G16  | Restricted password retries use global failure/cooldown state.                    | `test_restricted_password_retries_share_global_cooldown`                                                                                                                                      |
| G17  | Forgot PIN obtains a password challenge without a fake failure.                   | `test_forgot_pin_issues_password_challenge_without_failed_attempt`                                                                                                                            |
| G18  | Locked Voice is scoped to the continued LIVE target under every privacy mode.     | `test_locked_media_scope_is_independent_of_notification_privacy`                                                                                                                              |
| G19  | Anonymous calls have unique actionable, expiring handles.                         | `test_anonymized_call_handles_are_unique_actionable_and_expirable`                                                                                                                            |
| G20  | Snapshot installation is epoch/revision safe and exhaustion is explicit.          | `test_runtime_snapshot_retries_across_revision_change`; `test_runtime_snapshot_exhaustion_is_explicitly_retryable`; `test_epoch_round_trips_as_sequence_reset_boundary`                       |
| G21  | One client reader demultiplexes concurrent responses and unsolicited events.      | `test_event_before_snapshot_response_is_not_discarded`; `test_concurrent_request_ids_receive_only_their_own_response`                                                                         |
| G22  | Canonical mutations fan out content-free, privacy-projected invalidation.         | `test_mutation_fans_out_content_free_state_to_restricted_peer`                                                                                                                                |
| G23  | Normal exit locally preserves pending text and Voice without remote waits.        | `test_normal_exit_preserves_pending_text_and_voice_locally`                                                                                                                                   |
| G24  | Profile return creates no implicit reconnect/fallback intent.                     | `test_profile_return_does_not_resurrect_live_reconnect_intent`                                                                                                                                |
| G25  | A purge fence wins deterministic races against Voice/fallback/outbox commits.     | `test_purge_fence_wins_after_voice_finalize_passes_initial_guard`; `test_purge_stop_wins_after_outbox_ack_passes_initial_guard`                                                               |
| G26  | Preparation, key destruction, and cleanup failures report truthful milestones.    | `test_preparation_failure_still_destroys_key_and_reports_phase`; `test_key_destruction_failure_prevents_cleanup_and_reports_phase`; `test_cleanup_failure_does_not_restore_destroyed_keyslot` |
| G27  | Locked lifecycle control is a prior-authenticated per-session capability.         | `test_device_lifecycle_scope_requires_prior_authenticated_session`; `test_hard_locked_daemon_cannot_bypass_session_authorization`                                                             |
| G28  | Destructive message identity includes direction.                                  | `test_direction_collision_deletes_only_selected_receipt`                                                                                                                                      |
| G29  | Terminal text/contact/settings/profile behavior remains an equal client contract. | Full `test_terminal_*`, chat, contact, settings, and profile suites                                                                                                                           |
| G30  | Source, schemas, distributions, and version axes pass all repository gates.       | Ruff, Ruff format, MyPy, generated-doc validation, wheel builds, version validation, and full unittest discovery                                                                              |
