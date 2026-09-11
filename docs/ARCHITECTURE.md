# Metor Architecture Decisions Guide

This document is the canonical architecture guide for the repository.
It records the long-lived design boundaries that should survive feature work, refactors, and UI changes.
Future architecture decisions should extend this file instead of creating separate top-level notes.

## Daemon lock lifecycle

The managed daemon has an explicit security lifecycle:

```text
START → LOCKED → UnlockCommand → UNLOCKED → LockCommand → LOCKED
```

`LockCommand` is an idempotent runtime lock, not a screen lock, shutdown, or
self-destruct operation. It revokes authenticated sessions and UI focus before
stopping profile-scoped workers, peer sessions, Tor, database access, and key
state. IPC stays available so the process can accept a later `UnlockCommand`,
which constructs a fresh profile runtime.

For encrypted profiles, unlock uses the configured `KeyProtector` to recover the
PMK and derives fresh DB, secret, and blob keys. Lock closes SQLCipher and the
blob store, clears their mutable runtime key buffers, clears the PMK hierarchy,
and releases all references. The protected PMK keyslot remains intact. Python
cannot guarantee deterministic erasure of every interpreter-created immutable
copy, so this is honest best-effort process-memory hygiene rather than a claim
of secure-memory behavior.

## Profile encryption and storage

### Retired development model

Before the first-release PMK design, the user password was passed directly to
SQLCipher. A separate Argon2i derivation of the same password encrypted Metor
and Tor identity files. There was no single random profile root, no blob-domain
key, and purge depended primarily on recursive overwrite/delete. The repository
is unreleased, so that development-only format is deliberately unsupported and
has no migration shim; affected profiles must be recreated.

### First-release encrypted profile model

Each encrypted local profile has exactly one independently random 32-byte
Profile Master Key (PMK), created with the operating system CSPRNG. The password
is an unlock credential and never becomes the SQLCipher key.

```text
Password
   │
Argon2id
   ▼
  KEK ── authenticated unwrap ──► PMK
                                  │
                      keyed BLAKE2b KDF
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              DB_KEY         SECRET_KEY      BLOB_KEY
             metor/db/v1  metor/secrets/v1 metor/blobs/v1
```

- `DB_KEY` is the raw 32-byte SQLCipher key. User passwords are never passed to
  SQLCipher.
- `SECRET_KEY` encrypts long-lived Metor signing and Tor Onion Service private
  identity files. These remain separate files because Tor consumes its own key
  format at runtime; moving them into SQLCipher would not remove the need for a
  carefully controlled Tor runtime export.
- `BLOB_KEY` is the root for encrypted external binary objects. It is not a
  network key and is never used by the typed message/delivery layer directly.

Domain derivation uses PyNaCl/libsodium keyed BLAKE2b with stable, versioned
labels. Raw material is never reused between domains. Runtime keys live in
mutable buffers where practical and are cleared on lock, shutdown, and purge.

### KeyProtector and password keyslot

Profile lifecycle code depends on `KeyProtector`, whose responsibilities are to
protect, unprotect, atomically rewrap, and destroy PMK access. The desktop
implementation is `PasswordKeyProtector`. Future TPM or Secure Element
implementations can replace it without changing SQLCipher, key derivation,
blob storage, message DTOs, or lock semantics.

The password keyslot is strict JSON containing:

- format `metor-password-keyslot`, version `1`;
- Argon2id algorithm, random salt, and persisted operation/memory limits;
- XSalsa20-Poly1305 SecretBox algorithm, random nonce, and authenticated PMK
  ciphertext.

Unknown fields, unsupported versions/algorithms/parameters, malformed Base64,
wrong passwords, and authentication failures are rejected. The keyslot never
stores the password, KEK, derived domain keys, or plaintext PMK. Argon2id uses
libsodium's interactive limits (operation limit `2` and a 64 MiB memory limit).
These parameters provide a memory-hard interactive unlock without applying the much larger sensitive
profile to every desktop daemon start. Unlock derives the KEK from the persisted
parameters, after validating the supported algorithm/version and bounded
Argon2id operation and memory limits. Future recommended defaults can therefore
change without invalidating existing valid keyslots, while hostile metadata
cannot request unbounded work or memory.

Keyslot creation and password rewrap use an owner-only temporary file, flush and
`fsync`, then atomic replacement. Before replacement, rewrap opens the staged
keyslot with the new password and verifies that it recovers the exact original
PMK. Rewrap authenticates the old password and wraps that same PMK with a new
salt and nonce. It does not re-encrypt SQLCipher, identity data, or blobs, so
`DB_KEY`, `SECRET_KEY`, and `BLOB_KEY` remain unchanged. A failed build or
read-back leaves the prior valid keyslot in place.
`ChangePasswordCommand(current_password, new_password)` requires explicit
current-password verification even from an authenticated unlocked daemon session;
this prevents a separate local IPC client from changing another session's
profile password. Password-bearing commands suppress dataclass `repr` output.

`PasswordKeyProtector.destroy` overwrites and `fsync`s its regular keyslot file,
unlinks it, and synchronizes the parent directory where supported. This is
best-effort software destruction only: flash wear-leveling, copy-on-write,
snapshots, backups, and remapped blocks can retain historical copies.

### Security-mode migration

Security-mode migration is a multi-resource staged transaction. It copies the
active profile to a sibling staged generation, transforms the staged database,
keyslot, private secret representation, metadata, and every persistent external
blob, then reopens and validates that staged target. Encrypted-to-plaintext
migration authenticates and decrypts each source blob with the source `BLOB_KEY`;
plaintext-to-encrypted migration writes the current authenticated blob format
with the target `BLOB_KEY`. Both paths preserve every logical blob ID, compare
each staged read-back with its source payload, and validate target database
`blob_id` references before commit. The active source and its key material are
not modified during preparation.

Temporary blobs are non-durable runtime spool state. Security migration requires
the profile daemon to be offline, so the staged target discards that namespace
instead of copying mode-incompatible runtime residue. Persistent blobs are all
migrated, including currently orphaned canonical objects, because ownership
metadata is not yet sufficient to discard them without risking data loss.

The explicit durable commit point is the atomic replacement of a sibling
migration journal from `prepared` to `committed`, after the complete staged tree
has been synchronized. Recovery reads this journal before opening a profile:
`prepared` discards the staged tree and continues using the unchanged source;
`committed` completes generation activation and then performs best-effort old
source cleanup. Cleanup failure after commit leaves the target authoritative and
usable; it never triggers destructive rollback.

### Profile layout

```text
profile/
├── config.json
├── storage.db                         # plaintext or DB_KEY-protected SQLCipher
├── storage.runtime.db                 # optional plaintext DEBUG mirror
├── protected-key-material/
│   └── keyslot.json                   # protected PMK, owner-only
├── blobs/
│   ├── persistent/                    # durable ciphertext or development plaintext
│   └── temporary/                     # non-durable mode-appropriate runtime spool
├── hidden_service/
│   ├── metor_secret.key               # SECRET_KEY ciphertext when encrypted
│   ├── hs_ed25519_secret_key.enc       # SECRET_KEY ciphertext when encrypted
│   └── hs_ed25519_secret_key           # runtime-only Tor plaintext, shredded
└── tor_data/                           # Tor runtime state
```

Sensitive directories use owner-only permissions where the platform supports
them. Permissions are defense in depth, not encryption.

### External blob stores

`EncryptedBlobStore` and `PlaintextBlobStore` implement the same logical
`BlobStore` API: `put`, `read`, `delete`, `promote`, and `exists`. Callers use
opaque IDs and never select filesystem paths or security-mode formats. The
plaintext implementation is development-only and writes payload bytes directly
to disk; it provides no at-rest confidentiality.

`EncryptedBlobStore` maps random 256-bit lowercase hexadecimal blob IDs to
internal files; callers never supply or receive filesystem paths. It supports
`put`, authenticated `read`, idempotent `delete`, and atomic temporary-to-
persistent `promote`. IDs are strictly validated, preventing path traversal.

Each object derives an independent key from `BLOB_KEY`, the versioned
`metor/blob-object/v1` context, and its blob ID using keyed BLAKE2b. Files use an
explicit `METORB01` magic value and format version followed by a fresh
XChaCha20-Poly1305 nonce and authenticated ciphertext. Magic/version and blob ID
form immutable authenticated context. Reads reject truncated, unsupported,
relocated, wrong-key, or modified objects before returning plaintext. Writes
encrypt in memory and atomically persist ciphertext without creating a
plaintext temporary file. The initial whole-object implementation caps
plaintext objects at 64 MiB to bound corrupt-file reads; future streaming media
work may introduce a different documented limit with a new format version.

The whole-object API establishes crypto and ownership semantics. Voice adds a
bounded, resumable application protocol while keeping encrypted object paths and
formats behind `BlobStore`. `VoiceContent` carries `blob_id`, codec, byte count,
and optional duration metadata only; raw binary data does not become a permanent
NDJSON message representation. A future `FileContent` can reuse these ownership
and bounded-transfer principles without changing message semantics.

Temporary and persistent objects use the same encryption model. Consequently a
`LIVE + VOICE` object can be promoted to `DROP + VOICE` during fallback
without changing keys or embedding content in transport messages. Promotion
changes ownership/lifecycle only; LIVE content does not become history merely
because it required encrypted crash-safe spooling.

### Lock versus purge and self-destruct

```text
LOCK                              PURGE / SELF DESTRUCT
stop profile runtime              stop profile runtime
close SQLCipher/blob handles      close SQLCipher/blob handles
clear PMK and derived keys        clear PMK and derived keys
keep protected PMK                destroy protected PMK access
keep encrypted profile data       then best-effort filesystem cleanup
keep IPC available                stop/remove profile data
```

All destructive paths use the central `destroy_profile_storage` lifecycle.
Callers first stop or exclude runtime activity; the lifecycle then closes pooled
SQLCipher access, clears any injected runtime keys, calls
`KeyProtector.destroy`, and only afterward invokes recursive filesystem cleanup.
`SelfDestructCommand`, individual profile removal, and global purge share this
key-first ordering. If cleanup fails after key destruction, nothing recreates
protected key material.

Hard-locked daemons reject anonymous self-destruction. An authenticated client
may deliberately enter restricted mode with the `device_lifecycle` capability;
only that fixed lock-cycle capability can prepare profile exit or self-destruct
while the client remains restricted. Merely reaching the local IPC socket never
grants destructive access.

`secure_remove_path` remains defense in depth. Portable Python overwrite and
unlink cannot guarantee physical erasure on SSD, SD, flash, copy-on-write,
snapshotted, journaled, remapped, or backed-up storage. The software password
protector's keyslot is itself stored on that media, so historical physical
copies may remain recoverable. Software purge therefore provides clean logical
key destruction plus best-effort cleanup, not guaranteed irreversible hardware
sanitization. Full-disk encryption is still recommended. A future hardware
protector can make purge stronger by destroying a non-exportable wrapping key.

### Plaintext and debug modes

Plaintext local profiles remain an explicit DEVELOPMENT/DEBUG option for testing
workflows, but are not appropriate for normal or hardened deployment. They have
no PMK, no at-rest confidentiality, no password-backed local unlock, no
encrypted external blob store, and no cryptographic-erasure guarantee. Their
external blob payloads are plaintext on disk; purge is filesystem cleanup only.
`daemon.allow_plaintext_profiles` defaults to `false`;
development environments must deliberately enable it, while hardened/device
builds keep it disabled to prohibit plaintext profile creation and migration.

`daemon.enable_runtime_db_mirror` is disabled by default and is explicitly a
DEBUG/DEVELOPMENT-ONLY facility. When enabled it writes a plaintext database
copy beside encrypted storage. It is removed on disable, lock, shutdown, purge,
and self-destruct, but PMK destruction cannot retroactively protect deliberately
created plaintext copies, snapshots, or backups. Hardened device configuration
must prohibit this setting.

### Threat-model separation and future hardware work

Tor and Onion Services protect network transport and network-identity
properties. PMK-derived keys protect persistent data on the local device. The
blob key exists for local at-rest protection, not because Tor transport lacks
encryption.

A future `TPMKeyProtector` or `SecureElementKeyProtector` must implement the same
protector contract, define versioned provider metadata, provision a
non-exportable wrapping key, map authentication failures to the existing error
boundary, register/select the provider, inject it through `KeyManager` and the
central destruction lifecycle, and destroy that hardware key during purge. No
SQLCipher, key-hierarchy, blob, message, or lock semantic requires redesign.

Voice uses authenticated, exact-offset chunks with receiver-enforced frame and
retention limits. Receipt metadata owns blob references, and fallback promotes
temporary ownership only after the message transition commits. Platform audio
capture/playback and frontend playback cursors stay outside Core. File transfer
and a `FileContent` DTO remain future work.

## Messages: delivery and content

Messages have two independent dimensions. `Delivery` is either `LIVE`
(ephemeral interactive delivery, with a temporary reliability spool) or `DROP`
(persistent asynchronous delivery). `ContentType` is `TEXT` or `VOICE`,
represented by `TextContent` and `VoiceContent`.

```text
LIVE + TEXT → ephemeral interactive text
DROP + TEXT → persistent asynchronous text
LIVE + VOICE → ephemeral, resumable interactive Voice
DROP + VOICE → persistent asynchronous Voice
```

The public boundary uses `SendMessageCommand(target, delivery, content,
msg_id)` and `MessageReceivedEvent(alias, delivery, content, msg_id)`. Fallback
changes only `Delivery.LIVE` to `Delivery.DROP`; logical identity and content
remain unchanged.

One Voice capture turn is one logical message and stable `msg_id`. Bounded
Base64 chunks exist only in authenticated transfer frames; the stored/public
content DTO is a blob reference. Voice uses the same ACK, dedupe, pending,
reconnect/replay, selective fallback, consume, and DROP history semantics as
text. `FILE` and `PAYMENT_REQUEST` remain extension examples.

## Purpose

Use this document when you need to answer one of these questions:

- Which layer is allowed to own state or side effects?
- Which behaviors should remain configurable, and which should stay hard safety guardrails?
- How should new IPC, transport, or persistence features fit into the existing design?
- Which other repository documents should be updated when architecture changes?

## Document Map

- [README.md](../README.md): Master entry point for installation, usage, and repository navigation.
- [SETTINGS.md](./generated/SETTINGS.md): Generated, first-class reference for user-facing settings and structural profile config keys.
- [API.md](./generated/API.md): Generated, first-class reference for the typed IPC contract.
- [api.schema.json](./generated/api.schema.json): Generated JSON Schema wire contract for the typed IPC DTOs.
- [GLOSSARY.md](./GLOSSARY.md): Canonical terminology reference for settings namespaces, transport fields, and renamed symbols.
- [EMBEDDED_UI.md](./contracts/EMBEDDED_UI.md): Embedded frontend ownership, platform ports, projections, recovery rules, and contract matrix.
- [AUDIT.md](./governance/AUDIT.md): Review checklist for security, OPSEC, concurrency, and architecture risks.
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

Settings keys live in exactly three namespaces (see [GLOSSARY.md](./GLOSSARY.md)):

| Prefix            | Scope                                                                   | Validated by                 |
| ----------------- | ----------------------------------------------------------------------- | ---------------------------- |
| `client.*`        | Client-machine behavior, paradigm-neutral (e.g. `client.history_limit`) | Client registry              |
| `daemon.*`        | Daemon-host behavior                                                    | Daemon `SettingKey` registry |
| `ui.<frontend>.*` | Frontend-owned presentation and behavior                                | Registering UI frontend      |

Validation is a two-registry rule: the daemon accepts only `daemon.*` keys that
exist in its own `SettingKey` registry. Any client-scope key (`client.*` or
`ui.<frontend>.*`) that gets routed to the daemon is rejected with the typed
`CLIENT_SCOPE_KEY_REJECTED` event instead of the legacy
`DAEMON_CANNOT_MANAGE_UI` naming.

Request defaults are resolved client-side, not daemon-side:
`client.history_limit` and `client.messages_limit` are read by the client and
carried into the `limit` field of `GetHistoryCommand` / `GetMessagesCommand`.
The daemon falls back to its own request constants only when no `limit` is
present in the request.

The drop-transport policy is one decision with two knobs:
`daemon.reuse_live_for_drops` and `daemon.allow_drop_standby_on_live` are
documented together as a policy group, not as independent switches. When live
reuse is enabled, queued drops ride the existing live session channel and a
cached drop tunnel is closed while live exists, so `allow_drop_standby_on_live`
only has meaning when reuse is disabled:

| `reuse_live_for_drops` | `allow_drop_standby_on_live` | Drop routing while live is active                                                                      |
| ---------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| `true` (default)       | `false` (default)            | Drops ride the live session channel; no drop tunnel cache is kept warm.                                |
| `true`                 | `true`                       | Same routing; the standby flag is moot because the cache is closed while live exists.                  |
| `false`                | `false`                      | Drops use tunnel/direct delivery; no warm standby cache.                                               |
| `false`                | `true`                       | Drops use tunnel/direct delivery; the cached drop tunnel stays warm as fallback while live is primary. |

The ledger `transport` field is written only when the live-history policy allows
it: when `daemon.record_live_history` is `false`, the field is omitted from ALL
ledger rows, including drop rows — uniform absence, never selective absence.

Configuration should follow these rules:

- User-relevant runtime behavior belongs in documented settings metadata and appears in the generated [settings reference](./generated/SETTINGS.md).
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

## IPC Contract Evolution

The typed IPC contract is versioned so client/daemon drift becomes a typed error
instead of silent misbehavior. Two version axes exist:

1. IPC wire protocol (`IPC_PROTOCOL_VERSION` / `IPC_PROTOCOL_MIN_SUPPORTED` from
   `metor.versioning`):
   negotiated over the local IPC socket between UI clients and the daemon.

2. Peer wire protocol (`PEER_PROTOCOL_VERSION` / `PEER_PROTOCOL_MIN_SUPPORTED`
   from `metor.versioning`):
   negotiated between daemons inside the Tor peer handshake.

### Additive-Only Within an IPC Generation

- New commands, events, and payload fields may be added within the same IPC
  generation, but every new field MUST have a default so writers from older
  versions stay valid.
- Removing or renaming a field, event, or command requires an incompatible IPC
  protocol generation bump.
  Renames are never aliased; every caller migrates in the same release.
- Strict unknown-field rejection stays in place: a payload with an unknown field
  is a hard error, never a silent ignore. The version handshake converts
  version drift into a typed `ProtocolMismatchEvent` before any payload parsing
  could otherwise fail with an untyped error.

### IPC Version Handshake (UI -> Daemon)

1. The client sends `InitCommand(current_version, min_supported)` to advertise
   its inclusive IPC support range.
2. The daemon intersects that range with
   `[IPC_PROTOCOL_MIN_SUPPORTED, IPC_PROTOCOL_VERSION]`. If there is no overlap,
   it returns `ProtocolMismatchEvent` containing both ranges.
3. Otherwise the daemon selects the highest common generation and returns it as
   `InitEvent.negotiated_version`, alongside its advertised range. The client
   independently validates that result before accepting the session.

For the complete generated command/event reference, see [API.md](./generated/API.md).

### Canonical Client Lifecycle and Wire Sequence (Track 1 & Track 2)

Metor provides two complementary client integration surfaces:

- **Track 1 (Reference Client):** A reusable Python library (`metor-sdk`, providing `MetorClient`) that handles connection lifecycle, framing, auth derivation, and dispatching.
- **Track 2 (Documented Wire Contract):** The newline-delimited JSON IPC wire protocol allowing implementations in any programming language.

The canonical wire sequence is:

1. **Connect:** Connect to the daemon's local IPC listener (`127.0.0.1:<daemon_port>`). When connecting to a remote VPS daemon, the port is forwarded locally via SSH tunnel, keeping remote transparent.
2. **Handshake:** Send `InitCommand(current_version, min_supported)` with a unique `request_id`. Await `InitEvent(negotiated_version)`.
3. **Auth & Unlock Gate:**
   - If the daemon responds with `DaemonLockedEvent`, send `UnlockCommand(password=...)` and await `DaemonUnlockedEvent`.
   - If the daemon responds with `AuthRequiredEvent(challenge, salt)`, compute `proof = HMAC-SHA256(Argon2i(password, salt), challenge)` and send `AuthenticateSessionCommand(proof=...)`, awaiting `SessionAuthenticatedEvent`.
4. **Register Live Consumer:** Send `RegisterLiveConsumerCommand()`. The daemon will now stream asynchronous push events (messages, status updates, contact requests) to this socket.
5. **Initial State & Event Loop:** Terminal may fetch its compatibility projection
   with `GetChatStartupStateCommand`. Rich clients request
   `GetRuntimeSnapshotCommand`, install its `revision` as the projection
   baseline, then apply buffered/later events with greater revisions. Process
   continuous streaming events delimited by newlines.

### Aggregate Runtime Projection

`RuntimeSnapshotEvent` is the authoritative content-free reattachment boundary.
It aggregates profile/Onion identity, saved and discovered contacts, DROP
conversation summaries, LIVE contexts, pending incoming requests, unread and
pending counts, terminal disconnect reasons, and a settings revision. Every IPC
event carries a monotonically assigned daemon `revision`, so registration before
snapshot retrieval cannot create an undetectable state-change gap. Frontends do
not reconstruct this truth from logs or human-readable strings, and the snapshot
never contains message bodies, Voice bytes, drafts, playback position, or
notification history.

### Per-Client Restriction Versus Hard Lock

`LockCommand` retains its security meaning: it releases the complete active
profile runtime and its keys. Device-style screen locking uses
`RestrictClientCommand`, which freezes an authorization/privacy policy for only
the requesting IPC session while other authenticated clients and the profile
runtime remain active. Core gates commands, locked Voice target ownership,
incoming acceptance, and identity disclosure; it does not trust frontend
presentation state as an authorization boundary.

Optional quick unlock is a one-use challenge proof backed by a salted Argon2id
PIN verifier. It is not a PMK/keyslot credential and cannot start a cold or
hard-locked profile. Three failed PIN proofs disable PIN for that session's lock
cycle and require the normal profile-password proof.

### Peer Wire Version (Daemon -> Daemon)

- The CHALLENGE and authenticated AUTH frames each advertise the sender's
  inclusive current/minimum peer-generation range.
- Each daemon intersects the two ranges and selects the highest common
  generation. Either future-only or legacy-only non-overlap rejects the
  connection before peer payloads are accepted.

For application releases and every compatibility axis, see [RELEASING.md](./RELEASING.md).

### Delivery-Only Connect Hint (deliberately not implemented)

A `delivery_only` handshake hint — an outbound connect that must not surface an
accept prompt at the peer — was considered and deliberately rejected. It only
makes sense for an automatic live-connect path, and automatic live connect was
itself rejected: the UI sends `SendMessageCommand` with `Delivery.LIVE` or
`Delivery.DROP`
and never asks the daemon to auto-establish a session. A flag without a caller
would be dead protocol surface, so it is not implemented. If a future UI
paradigm reintroduces automatic live connect, this document must be revisited
before any flag is added.

## Notification Sinks

The daemon may surface asynchronous user-facing notifications to headless
consumers that are not connected as interactive UI clients. This is the
canonical contract for that path:

- Notifications use a structured `NotificationPayload` with typed fields, never
  free-form display text. Consumers branch on payload fields, and the payload is
  derived from the existing typed event DTOs — it is never a second wire format.
- A sink is a named registration with a documented payload contract. Sinks are
  configured through the `daemon.notification_sink` setting and receive the
  daemon's structured notifications.
- Sinks fire only while the daemon has no connected interactive clients. As soon
  as an interactive client attaches, sink delivery is suspended because the
  attached client is the authoritative notification consumer.
- UI developers register their own sink types for their frontend instead of
  bolting display logic onto the daemon broadcast path.

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

- `ui.terminal.inbox_notification_delay`
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
   The message store retains outbound rows with `delivery = live` and `status = pending` until ACK, terminal fallback conversion, or explicit manual fallback. That durable spool is the crash-safe source for recoverable live sends.

3. Live lifecycle state is derived, not stored redundantly.
   For each peer the daemon derives one `LiveTransportState`: `DISCONNECTED`, `CONNECTING`, `PENDING`, `CONNECTED`, or `RETUNNELING`.

4. The chat UI owns presentation-only transport state.
   The UI may mark one peer as `LIVE`, `SWITCHING`, `RECONNECTING`, or `DROP`, but that state is only a rendering/send-policy mirror driven by typed IPC events.

5. The UI does not own a recoverable outgoing buffer.
   When the user types while the chat still routes through live semantics, the UI sends `SendMessageCommand(delivery=Delivery.LIVE, content=TextContent(...))` immediately and renders a pending self-message. Whether that message is sent now, durably deferred, replayed after recovery, or promoted to drop is daemon logic.

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
   If `daemon.fallback_to_drop` is enabled, the daemon changes any remaining durable pending rows from `delivery = live` to `delivery = drop` before shutdown. If fallback-to-drop is disabled, those durable pending live rows remain pending for a future live recovery.

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
3. Update the generated [settings](./generated/SETTINGS.md) or [IPC API](./generated/API.md) references through their generators; [api.schema.json](./generated/api.schema.json) is generated with the API reference.
4. Update the [audit checklist](./governance/AUDIT.md) and [contribution guide](./CONTRIBUTE.md) if the new behavior changes review or implementation rules.

## CLI and frontend distribution boundary

The `metor` distribution owns the general command parser, one-shot renderers,
daemon/profile orchestration, and both `metor` and `metor-daemon` executable
entries. It contains no interactive frontend. `metor-sdk` owns `metor.client`,
typed `metor.core.api` DTOs, shared proof helpers, protocol/version data, and the
versioned `FrontendLaunchContext`. `metor-ui-terminal` owns
`metor.ui.terminal`, including slash-command definitions, the upper help panel,
rendering and key handling. These distributions share PEP 420 namespace paths
but never ship the same file.

`metor chat` discovers metadata from the `metor.ui_frontends` entry-point group.
Selection is explicit `--ui`, then `METOR_UI`, then `client.default_ui`. The
base loads only the selected callable and validates its contract version before
profile validation or daemon startup. Missing, duplicate, broken and
incompatible frontends are explicit errors. General help and chat launcher help
return before profile construction and never import or enumerate a UI. UI and
daemon-autostart options are scoped to `chat`; other commands retain `--ui`
text as ordinary user data.

Peer and IPC sockets use finite per-socket FIFO writers. Canonical state locks
cover mutation and generation assignment, never blocking socket writes. LIVE
Text and Voice emissions carry last-moment generation claims so fallback or
purge invalidation wins over queued stale work. Queue saturation is an explicit
connection error and shutdown closes sockets to interrupt blocked writers.

Runtime snapshots validate both the event revision and an atomic content-free
network-state token around composition. Per-client FIFO writers stamp events
before enqueue, so a delayed writer preserves revision order. Recovery state is
typed as connected, connecting, pending, retunneling, reconnect grace,
scheduled reconnect, or terminal disconnected with machine-readable actor and
reason; receipt existence is not a recovery signal.

Retained media discovery uses `ListRetainedMessagesCommand` and a stable,
filter-bound opaque cursor. Inventory entries expose identity and safe metadata,
never message bytes or storage paths. `GetVoiceChunkCommand` performs bounded
non-consuming exact-identity reads; only `ReleaseVoiceCommand` consumes one
eligible finalized inbound Voice item.

## Terminal UI Design Guidelines

One convention for every CLI and chat surface. These rules are the
codified version of how the terminal output already renders; keep new
output inside them instead of inventing new visual vocabulary.

### Multi-Line Output Convention

1. **The first line is the header.** It starts directly at the status
   prefix (`sys$`, `inf$`, `err$`) with no leading blank line. A
   multi-line command output must never open with an empty line.

2. **No decorative separators.** Dashes are not used as headers or
   dividers anywhere (`---`, `- - -`, divider lines). Structure comes
   from the header line, indentation, and section spacing — not from
   box-drawing characters.

3. **Header to content: exactly one blank line.** The header is
   followed by one empty line before the first content line, giving
   multi-line blocks a consistent title + body rhythm.

4. **Sections: one blank line before the section header.** When a single
   output has multiple sections (e.g. `Active session:` / `Pending
session:`, or saved contacts / discovered peers), separate them with
   exactly one empty line placed _before_ the next section header.

5. **Chat continuation lines are indented** by the visible prefix width
   (timestamp + `sys$`/`To X$`/`From X$`) via `indent_multiline_text`, so
   wrapped and multi-line output aligns under the first content column.

6. **Single-line results render inline.** A command that resolves to one
   message (e.g. `No active sessions.`) prints just that message at the
   prefix — no header wrapper.

### Color Semantics

Colors carry meaning only; they are never decorative. The palette is
fixed — do not introduce new colors without updating this section.

| Color       | Meaning                                                                      |
| ----------- | ---------------------------------------------------------------------------- |
| `CYAN`      | System context: `sys$` prefix, command names, peer identity in headers       |
| `YELLOW`    | State values (`session_state: connected`), user input echoes, warnings       |
| `GREEN`     | Success/active state: own messages (`To X`), active sessions, saved contacts |
| `RED`       | Errors: `err$` prefix, failed messages, destructive warnings                 |
| `PURPLE`    | Remote context: `From X` messages, remote-profile markers                    |
| `DARK_GREY` | Incidental detail: markers, `none` values, unfocused/unbound entries         |

Consequences: value labels stay uncolored (`session_state:`) while the
value itself is colored; peers are identified with `CYAN` in headers and
`GREEN`/`DARK_GREY` in lists depending on saved state; `RESET` is
applied after every colored span.

### Enforcement

- Each distribution owns its presentation helpers. Base CLI formatters and
  Terminal chat renderers may follow the same conventions but do not import
  one another.
- The chat renderer only adds the prefix and continuation indentation; it
  does not decorate content.
- Tests assert the convention (no leading blank line, no `---`, header
  before content) for representative multi-line outputs.
