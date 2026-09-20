# Metor Naming Glossary

This document is the canonical terminology reference for the Metor codebase.
It is binding: every new or renamed symbol, setting, event, or documentation
string MUST follow these definitions. When in doubt, extend this file instead
of inventing a parallel term.

## Graphical frontend

`gui` is the single official graphical frontend ID; `metor-ui-gui` owns
`metor.ui.gui`. Embedded describes deployment, not another frontend ID.
`device_config` is the optional absolute device-description path on the public
launch context; `simulator` is explicit isolated execution, never desktop fallback.
`pcm_s16le_16000_mono` names the candidate GUI codec: 16 kHz mono signed
little-endian 16-bit samples, 320-sample capture frames and sample-aligned seeks.
It does not imply that existing arbitrary Voice codec strings are decodable.

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

## Protected GUI metadata

- `DropConversationSummaryEntry.pending_count`: content-free count of pending
  outbound DROP receipts. It defaults to zero for older IPC-2 writers and remains
  separate from inbound `unread_count`. Clearing local history does not cancel
  this delivery state. Core retains its canonical conversation order, with
  stable peer-identity ties; the GUI applies protected pin order only.
- `profile_instance_id`: opaque storage-owned identity in a runtime snapshot and
  protected GUI preference result; independent of profile name and own Onion.
- `GuiPreferences`: bounded `ui.gui` document with DROP pin identities and
  application presentation/lock defaults. It contains no aliases or content.
- `preferences_revision` / `expected_revision`: authoritative revision and
  compare-and-swap precondition; distinct from runtime/content event revisions.
- `GetGuiPreferencesCommand` / `SetGuiPreferencesCommand`: public authenticated
  read/update operations. Security-policy changes additionally require current
  root-password strength; PIN verifier management remains its existing Core API.
- `GuiPreferencesEvent` / `GuiPreferencesRejectedEvent`: authoritative values
  or non-mutating typed `GuiPreferenceFailure`; no plaintext fallback.
- `profile_instance_id` / `protected_gui_preferences` capabilities: additive
  IPC-2 support negotiated before the GUI uses these services.

The generated API/schema describe the nested fields and enums. Schema 4 stores
this namespace under the profile database's protection and deletion boundary.

- `local_acceptance`: opt-in text-send field requesting a local durable result
  before remote ACK; false preserves the existing command behavior.
- `TextAcceptedEvent` / `TextRejectedEvent`: local admission or definite rejection,
  distinct from delivered/read outcomes. Actual delivery may be DROP after Core
  automatic fallback.
- `GetMessageOutcomeCommand` / `MessageOutcomeEvent`: exact canonical peer, local
  direction and logical-ID receipt reconciliation, without reading content. An
  absent receipt leaves delivery unknown.
## GUI Voice producer lifecycle

- `RegisterVoiceOwnerCommand` / `VoiceOwnerRegisteredEvent`: establish a Core-issued,
  connection-bound token for disposable DROP staging and LIVE producer loss.
- `ReleaseVoiceOwnerCommand` / `VoiceOwnerReleasedEvent`: revoke that connection's
  owner; `cleanup_pending` means durable cleanup/recovery remains tracked.
- `VoiceOwnerRejectedEvent`: unsupported policy or stale/wrong connection token.
- `owner_token`: optional qualification on Voice mutations, preview and retained
  inventory. It is volatile frontend authority, never a blob path or resume secret.
- `producer_interrupted`: retained LIVE data whose vanished producer could not yet
  be finalized. `can_retry_finalization` permits an authenticated explicit
  `FinalizeVoiceCommand` without claiming the invalidated producer token.
- `disposable_voice_owner`, `interrupted_voice_recovery`: managed-runtime capability
  names advertised only with protected SQL staging and an active blob store.
- `LiveContextEntry.context_generation`: logical conversation identity qualified by
  the runtime epoch. Recovery preserves it; a later independent call receives a
  new value. A known retained identity alone grants no active permission.
- `BeginVoiceCommand.context_generation`: optional expected logical context;
  stale, ended or pending-inbound context-qualified capture is rejected.
- `live_context_identity`: capability for snapshot identity and qualified capture.
- `ListRetainedMessagesCommand.msg_id`: optional exact identity filter, included in
  the continuation fingerprint. Combine it with peer and direction; it does not
  read or consume content. `retained_message_identity` advertises this filter.

## Bounded foreground text handoff

- `MarkReadCommand.max_messages`: optional maximum number of returned/consumed
  text rows. A null value preserves the existing unlimited caller behavior.
- `MarkReadCommand.max_payload_bytes`: optional budget for the UTF-8 JSON encoding
  of the selected SQL row string values; selection stops before a row exceeding
  the remaining budget. It excludes response-envelope/presentation overhead,
  which consumers reserve separately. Selection and consumption remain atomic.
- `bounded_text_handoff`: additive IPC-2 capability for these defaulted bounds.
  The operation remains peer- and delivery-filtered and never consumes Voice.

### Bounded DROP archive paging

- `bounded_archive_pages`: additive IPC-2 capability for optional
  `GetMessagesCommand.before_msg_id`, `before_direction` and `max_payload_bytes`.
  Continuation requires both exact identity fields and explicit bounded paging.
  The boundary is exclusive and qualified by the resolved peer and DROP delivery;
  equal timestamps are ordered by Core receipt identity. GUI code never receives
  or interprets SQL receipt numbers.
- `max_payload_bytes` on archive requests limits the UTF-8 JSON representation of
  the selected storage-row values, excluding response-envelope overhead, to at
  most 2 MiB. Bounded requests also require a row limit of 1–200. Core reads rows
  incrementally and does not fetch an entire archive to trim it afterward.
- `MessagesDataEvent.has_older` reports another eligible older row; it is not an
  unread count. `page_available=false` with an empty page means the requested
  boundary no longer exists or the first row exceeds the requested byte budget.
  Clients preserve the old page and offer an explicit return to current history.
  Legacy requests retain their existing history projection and default values.

### Contact identity guards and observations

- `contact_identity_guard`: additive IPC-2 capability for defaulted optional
  `RemoveContactCommand.onion` and `RenameContactCommand.onion`. The canonical
  contact service rejects an alias that no longer belongs to that exact identity;
  legacy alias-only writers retain their behavior. The asserted identity never
  selects a replacement peer through a reused human label.
- Contact rename/demotion and orphan-removal broadcasts are uncorrelated state
  observations. Only the requested operation's actual outcome completes its
  exchange. In particular, cleanup of a different discovered peer is not a
  successful result for a rejected contact-removal command.

### Exact incoming-call handles

- `pending_call_handles`: additive IPC-2 capability. Defaulted
  `AcceptCommand.action_handle`, `RejectCommand.action_handle` and
  `PendingConnectionEntry.action_handle` bind an action to one pending request
  owned by that IPC recipient. `IncomingConnectionEvent.action_handle` uses the
  same recipient-specific authority in both full and restricted sessions.
  Handle absence preserves legacy target-only requests. An explicit invalid,
  expired, cross-client or replacement-request handle returns
  `NO_PENDING_CONNECTION`; it never falls back to a target-only action.
- Handles survive the same client's successful normal reauthorization while the
  exact request, runtime and deadline remain valid. Denied restricted Accept
  does not consume the handle needed by Decline. A new restriction cycle,
  disconnected client or hard runtime teardown revokes its prior handles.
- `LiveContextEntry.call_handle`: defaulted optional navigation identity for a
  call observed by this IPC client and positively accepted into that exact socket,
  including acceptance by another local client. It is projected only while the
  accepted logical context still matches its generation. A later call from the
  same Onion cannot inherit it. This metadata grants no media permission.
- The network state coordinator owns runtime-only pending source tokens.
  Session access replaces them with bounded recipient handles before publishing
  snapshots or incoming events. A late source projection cannot acquire a
  replacement request's authority; internal source tokens are not exposed as
  usable client handles. No peer-wire or storage generation changes are involved.

### Restricted state and notification sources

- `restricted_live_projection`: additive IPC-2 capability for the read-only
  `GetRestrictedClientStateCommand` / `RestrictedClientStateEvent` exchange.
  The event projects only the requesting connection's current restriction,
  exact continued target/context generation, session phase and privacy-permitted
  pending calls / accepted navigation handles. Notifications Off returns neither
  pending nor accepted call metadata. Full sessions receive `restricted=False`.
- `continued_live_context_generation`: defaulted optional positive integer on
  `RestrictClientCommand` qualifies the deliberate foreground target. Core returns
  the granted target/generation on `ClientRestrictedEvent` and revalidates both
  on restricted-state queries. Recognized recovery preserves the logical context;
  terminal end or a fresh manual call does not inherit old media permission.
- `InboxNotificationEvent.delivery`: defaulted DROP/LIVE kind for content-free
  unseen activity. `source_id` is a defaulted optional canonical inbound message
  identity, used to distinguish a new arrival with the same unread count.
  Anonymous restricted projection removes source identity, Onion and alias;
  Notifications Off suppresses the event. No message body is part of this DTO.
  GUI dismissal watermarks and arrival hashes are bounded volatile metadata;
  current unread totals never establish an exact historical since-lock count.

### Qualified LIVE lifecycle controls

- `qualified_live_control`: capability for optional exact qualifiers on
  `DisconnectCommand`. `context_generation` identifies the displayed active or
  recovering context for End; `attempt_id` identifies one current outbound call
  for Cancel. They are mutually exclusive. Unqualified legacy callers retain
  their existing semantics.
- `LiveContextEntry.outbound_attempt_id`: defaulted optional opaque 32-character
  hexadecimal identity of the current outbound attempt. Cancellation invalidates
  it; a late connection worker cannot bind to or clear a replacement attempt.
  Its entropy is defined by `LIVE_ATTEMPT_TOKEN_BYTES`.
- `LiveControlCompletedEvent` / `LiveControlRejectedEvent`: exact local lifecycle
  completion or stale-selection rejection. Completion does not imply remote
  receipt or delivery; rejection is not a transport failure.
- `qualified_live_retunnel`: capability for optional
  `RetunnelCommand.context_generation`. Qualified Change route admits only an
  active LIVE context and rechecks it after circuit IO; it never selects a
  cached DROP route. `LiveContextEntry.route_changing` is the defaulted Core
  projection of admitted route replacement and its recognized recovery.

### Safe Core setting descriptors

- `safe_setting_descriptors`: capability for `GetConfigListCommand.safe_descriptors`
  and `SetConfigCommand.safe_only`. The closed Core catalog exposes permitted
  profile overrides; global and existing Terminal/CLI operations retain their
  defaults. It does not grant restricted-session configuration access.
- `SettingSnapshotEntry.value_type`, `display_name`, `display_group`, `description`,
  `constraints`, `security_note`, `min_value`, `max_value`, `editable` and `scope`
  extend the existing effective `key`, `value`, `source` and `category` snapshot.
  Registry types/defaults/constraints and current configuration remain authoritative.
- `SetConfigCommand.expected_value`: optional displayed effective string compared
  under the profile configuration lock before writing a profile override.
  A stale edit reports the existing typed setting validation error. It does not
  replace protected GUI-preference document revisions or write global settings.

### Activity metadata pages

- `history_metadata_pages`: capability for opt-in `page_size` and `before_id` on
  `GetHistoryCommand` / `GetRawHistoryCommand`. The exclusive profile-local ledger
  anchor is validated atomically with retrieval; it is not a message identity.
- `metadata_only`: paged history excludes free-form diagnostic text at the SQL
  boundary. `next_before_id`, `has_older` and `page_available` distinguish a next
  page from the end of history and an expired anchor. A summary page can contain
  no displayable rows while retaining a truthful older-page cursor.
- `record_live` and `record_drop`: optional effective Core retention flags on
  history results; populated for metadata pages. Existing rows can remain visible
  while recording is off. No replacement GUI ledger is created.
- `HISTORY_PAGE_MAX_ITEMS` (200), `HISTORY_METADATA_MAX_CHARS` (512),
  `HISTORY_PAGE_MAX_BYTES` (2 MiB) and `HISTORY_ANCHOR_MAX` bound the public paging
  contract. GUI retains one 64-row page and at most 128 cursor bookmarks.

### Optional frontend profile management

- `FrontendProfileManagement`: optional SDK protocol implemented by the local
  base host. It adds `profile_catalog`, `manage_profile` and
  `create_profile_entry` without making them requirements of the existing
  launch-host interface or introducing GUI filesystem access.
- `FrontendProfileCatalog`: finite local profile metadata, actual selected and
  default names, and an optional exclusive `next_after` bookmark.
- `FrontendProfileChange`: one `FrontendProfileAction` (`set_default`, `rename`
  or `remove`), exact profile name, originally selected host profile and optional
  new name. `selection_changed` refuses stale host-selection intent.
- `valid_frontend_profile_name`: exact bounded canonical name validation; path-like
  input is rejected before host lifecycle calls rather than silently normalized.
  `FRONTEND_PROFILE_PAGE_ITEMS` and `FRONTEND_PROFILE_NAME_CHARACTERS` bound pages
  to 64 rows and names to 255 characters.
- `Settings.set(expected_value=...)`: optional file-lock-protected effective-value
  comparison for host-owned global reference updates. A GUI-host rename follows
  the default reference only if it still points to the renamed profile.
  `renamed_default_unconfirmed` reports a completed directory rename whose default
  reference update could not be confirmed; it never means the rename was rolled back.

- `ProfileRuntimeCoordinator.switch(on_phase=...)`: optional observer of actual
  source snapshot, capture finalization, source preparation/release and target
  factory/bootstrap/snapshot phases; observer failure cannot change the transaction.
- `ProfileSwitchError.source_prepared`: confirmed Core preparation and hard lock,
  independently of the existing `source_released` client-detach result.
- `RuntimeSnapshotEvent.authenticated_client_count`: optional point-in-time
  authenticated IPC client count, including the caller; None is unavailable,
  not zero. Used for profile-switch shared-client consequences.
- GUI `LIFECYCLE_CAPTURE_SECONDS` (65): local wait ceiling for accepted capture
  finalization before exit/switch. Timeout is unconfirmed preservation and never
  authorizes an appliance power cut.

- `SelfDestructCommand.operation_id`: optional 32-character lowercase hexadecimal
  correlation identity (`DESTRUCTION_OPERATION_BYTES = 16`). It is carried by
  initiated, key-destroyed and terminal reports for the initiating client; it is
  not an authentication credential or an authorization grant.
- `SelfDestructRuntimeReleasedEvent`: opt-in exact-operation confirmation that
  runtime preparation, database close and runtime-key release all succeeded.
- `SelfDestructSafeEvent`: combined selected-encrypted-profile runtime release
  and persistent key-protection destruction. File cleanup can still be pending;
  unrelated runtime safety and host shutdown permission remain separate.
- `purge_safe_milestone`: support for the optional scoped destruction reports,
  not permission to invoke destruction. Existing conservative authorization applies.
- `MessageOutcomeEvent.archive_available`: optional exact receipt's local archive
  presence, read atomically with delivery/status and without loading any payload.
  False does not mean pending delivery was cancelled or that a message was never sent.
- `message_archive_state`: support for the optional archive-presence receipt field.
- GUI `RECEIPT_TARGETS`: at most three bounded LIVE-item populations plus one
  archive page (3,064 metadata identities) in uncertain-mutation reconciliation.
  Reads use original targets; later arrivals never join that batch.


GUI volatile interaction bounds: `CONTACT_SELECTION_ITEMS` (128) and
`CONTACT_SELECTION_BYTES` (64 KiB) bound exact selected-contact removal intent;
`PLAYBACK_COVERAGE_PER_ITEM` (128 intervals) and
`PLAYBACK_COVERAGE_INTERVALS` (8192 aggregate intervals, at most 1000 targets)
bound current-runtime drained PCM coverage. Exceeding coverage limits forgets
ranges conservatively; it never fabricates heard content or a Core Read receipt.


`WAVEFORM_BINS` is the 64-bin maximum for one retained GUI PCM amplitude summary.
`SEEK_FRACTION_STEP` is the 0.05 fraction used by deliberate Left/Right selection
in the native audio-position control; Enter/Space applies the selected position.
These are volatile presentation/input constants, not Core receipt or media-format
parameters. `PcmEnvelope` contains real sample peaks and explicit unknown bins.


`FrontendAddressManagement` is an optional public base host extension for offline
address operations. `FrontendProfileAddressRequest` captures `profile`, original
`selected_profile` and strict `generate` (default true; false checks only).
`FrontendProfileOperationResult.onion` is optional public address metadata,
defaulting to None. These host DTOs are not IPC credentials or rotation grants.
The operation preserves existing identity keys according to Core semantics.

### GUI purge observation and encoded cache blocks

- `PurgeFacts` / `PurgeMonitor`: bounded, generation/profile/operation-qualified
  observation of actual Core destruction milestones on the initiating SDK
  connection. Observation grants no lifecycle authority and never initiates or
  repeats destruction. Only `SelfDestructSafeEvent` confirms destroyed profile
  access; disconnect, timeout and individual key/runtime milestones do not.
- `GuiLimits.PURGE_OBSERVE_SECONDS`: 65-second maximum observation of an
  initiated operation before displaying an unconfirmed outcome.
- `GuiLimits.PURGE_CLEANUP_SECONDS`: five-second bounded wait for terminal
  cleanup evidence after confirmed safe destruction. Missing cleanup evidence
  cannot undo the positive safe milestone or fabricate complete file cleanup.
- `GuiLimits.MEDIA_CACHE_BLOCK_BYTES`: 64 KiB coalesced encoded blocks. Small
  input fragments do not allocate one retained Python object/index entry each.
  Public range reads return immutable bytes within the existing total cache cap.

### Frontend-independent platform contracts

`metor.client.platform` owns typed local interfaces in the SDK. These are not
IPC payloads, settings keys or a combined notification hook.

| Term | Meaning |
| --- | --- |
| `HardwareStatusPort` / `HardwareStatus` | Nonblocking cached hardware observations with monotonic `observed_at` and exclusive `valid_until` bounds. |
| `BatteryStatus` | Optional `charge_fraction` in [0, 1], `charging` and `external_power` facts. Unknown is distinct from empty, disconnected or not charging. |
| `HardwareAvailability` | Unknown, available, unavailable, permission-denied or failed observation; only available observations carry current facts. |
| `HardwareInputPort` / `InputSubscription` | Ordered physical observation delivery with explicit subscription ownership and close. |
| `ButtonSample` | One sequence-qualified, timestamped complete PTT/Power observation with a validity flag; neither a semantic action nor an authorization grant. |
| `CapturePort` / `OutputPort` | Separate bounded streaming audio interfaces; stopping one direction does not stop the other. |
| `AudioCapabilities` / `AudioEndpoint` | Observed native directions and route metadata; no acoustic/AEC proof follows from enumeration. |
| `IndicatorPort` / `IndicatorState` | Content-free, privacy-filtered indicator requests with finite semantic states. |
| `HapticsPort` / `HapticPattern` | Optional finite capture-admitted, capture-rejected or purge-arming feedback requests. |
| `ShutdownPort` | Separate privileged local actuator used only after lifecycle authorization and host preparation. |
| `PlatformActionResult` | Accepted, unavailable, denied, failed or unknown local action outcome. Accepted does not prove completed shutdown or authorize Core destruction. |
| `PlatformBindings` | One validated adapter identity and separately typed status, input, optional indicator, haptic and shutdown ports injected through `FrontendLaunchContext`; composition does not merge authority, and device configuration gates each optional action port. |
