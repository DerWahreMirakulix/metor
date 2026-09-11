# Refactor 2 final remediation evidence

This report records the corrective C01–C11 implementation and the V01 evidence
available on 11 September 2026. It is a handoff for independent review, not a
self-declaration of final acceptance.

## Scope and provenance

- Branch: `embeddedui`.
- Reviewed and actual starting commit:
  `4c1e1eaf57cc9c60d3d63e965802a07c38dc418f` (`Complete core client terminal
acceptance refactor`). The worktree was clean and the branch had not advanced.
- Baseline reconciliation found no intervening commit or local owner change, and
  no C01–C11 item was reclassified as fully fixed at the starting commit. The
  already-correct subcontracts identified below were preserved rather than
  reimplemented.
- Final commit: the commit containing this report; the exact immutable SHA is
  recorded in the delivery handoff because a commit cannot contain its own hash.
- Package direction retained: `metor-sdk`, `metor`, and `metor-ui-terminal`
  remain three non-overlapping distributions. No daemon distribution, UI extra,
  all-UI metapackage, GUI package, toolkit, layout, hardware driver, or device
  configuration schema was added.
- Compatibility versions remain `APP_VERSION=0.2.0`; there was no breaking IPC,
  database, keyslot, blob-format, or derivation change requiring a generation
  bump. The frontend launch contract, which is an installed-plugin Python
  contract rather than an IPC wire contract, advances from 1 to 2.

## C01–C11 remediation trace

| ID  | Reproduction and root cause                                                                                                                                                                           | Production correction                                                                                                                                                                                                                                                                                                                                                                             | Evidence and result                                                                                                                                                                                                                                                                                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C01 | Windows MyPy rejected POSIX-only `os.fchmod` and `os.getuid`; PowerShell ACL helpers had no execution bound.                                                                                          | POSIX operations use availability-checked wrappers without removing owner/mode enforcement. Both ACL creation and validation have a centralized 10-second timeout and sanitized failures.                                                                                                                                                                                                         | `mypy --platform win32` passes; `test_windows_acl_helpers_are_bounded_and_fail_safely`, POSIX permission, unsafe-parent, malformed/oversized metadata, and mocked effective-ACL tests pass. Native Windows ACL execution remains unverified below.                                                                                                                                             |
| C02 | An idempotent authentication acknowledgement called `mark_authenticated()` with full-password strength after PIN/NONE reauthorization.                                                                | Full proof verification alone mints a purpose-scoped `QuickUnlockAction` grant tied to the IPC session, runtime generation, and 60-second expiry. The grant is one-use and clears on restriction, disconnect, runtime replacement, reauthorization, and use.                                                                                                                                      | `test_sensitive_grant_is_verified_scoped_consumed_and_session_local` plus the existing PIN/NONE/password recovery suite pass.                                                                                                                                                                                                                                                                  |
| C03 | An idle worker could retire while admission still succeeded; failure marked logical closure before socket cleanup; peer failure had no reliability transition.                                        | One worker remains for the bounded connection lifetime. Admission and closure are synchronized; frame count, queued bytes, and individual frame size are bounded; drain/cancel and idempotent socket cleanup are separate states. Peer failure/saturation enters the connection controller fallback path.                                                                                         | Real socket-pair startup, delivery, oversize, failed-write cleanup, invalidated claim, saturation, close, serialization, and slow-peer/daemon-dispatch tests pass.                                                                                                                                                                                                                             |
| C04 | Replay copied pending rows, released the transition lock, then used an allocator that could mint fresh eligibility after fallback.                                                                    | LIVE generation is allocated at durable admission. Replay, Text, and Voice consume an existing generation under the transition boundary. Fallback invalidates before payload promotion; stale producers cannot recreate authority.                                                                                                                                                                | Atomic selective fallback, stale ACK, queued-claim invalidation, purge-fence, same-identity Voice promotion, and unrelated-message preservation tests pass.                                                                                                                                                                                                                                    |
| C05 | Voice append/finalize mutated memory before persistence; raised errors could leave `finalized=True` and permit a later ACK. Partial blob promotion lacked reliable same-process retry.                | Every persistence call is exception-safe with rollback or canonical retry. Local commands emit typed `PERSISTENCE_FAILED`; inbound failures send no commit ACK. Revoked DROP promotion is idempotently retryable in the same manager and after restart.                                                                                                                                           | False/raised append/finalize, crash reconciliation, duplicate END, lost ACK, quota hit/crossing, draft commit/cancel, progress-versus-terminal ACK, and bounded read/release tests pass. Segment reads use persisted `chunk_sizes`: at most the intersecting chunks are decrypted, while metadata scan/storage is bounded by `VOICE_MAX_SEGMENTS`; no claim of constant metadata work is made. |
| C06 | False preparation and close/key-clear exceptions could skip later key destruction; logical closure could skip the socket close; terminal events were broad and unflushed.                             | A phase-aware coordinator attempts preparation, DB close, runtime-key release, and disk-key destruction independently. Key destruction controls cleanup; callback failure cannot stop cleanup. Milestone/failure/completion events are initiator-scoped and receive a bounded writer flush before shutdown.                                                                                       | Full destruction matrix, actual dispatch, abort and notification failure, worker-start failure, key-first cleanup, repeated request, and new false-preparation/close/key-clear schedule pass.                                                                                                                                                                                                  |
| C07 | Public Voice append discarded quota/finalization outcomes; callbacks could run on reader/request threads; reconnect reused mutable queue/reader/thread state.                                         | Request methods declare accepted terminal DTOs and retain typed unexpected outcomes. Runtime invalidations remain uncorrelated. Every connection generation owns a fresh decoder, queue, stop flag, reader, and callback worker; reconnect from `on_disconnect` starts new generation workers.                                                                                                    | Public append quota result, early event, synchronous response demux, leftover callback, concurrent first request, loss wake-up, and reconnect-from-callback tests pass.                                                                                                                                                                                                                        |
| C08 | Snapshot used an incomplete topology fingerprint, performed alias creation, and assigned revisions separately from FIFO enqueue.                                                                      | Snapshot reads are side-effect free and execute behind a real StateTracker mutation barrier with expanded pending/recovery/activity/generation state. Publication serializes request stamping, envelope revision assignment, serialization, and bounded enqueue. Revisions are envelope sequence numbers; content/results not represented by the content-free snapshot remain deliverable events. | Revision retry/exhaustion, mutate-and-restore exclusion, delayed publication ordering, recovery state, restricted fan-out, and no-alias-creation tests pass.                                                                                                                                                                                                                                   |
| C09 | Restricted clients lacked exact inbound LIVE media read/release; same-peer later conversations could inherit a socket-only scope; anonymous handles were peer-wide and consumed before authorization. | Locked media is direction-, delivery-, peer-, message-, runtime-, and logical-context-bound. Logical context generation survives recognized recovery but advances for a new conversation. Anonymous handles are unique, one-use, lock-generation-bound, consumed only after authorization, and cleared on lifecycle transitions. Denials are correlated typed events.                             | Continued-target versus unrelated/DROP/direction/old-context tests, recovery-versus-new-context test, privacy modes, unique handles, expiry, replay, and independent authenticated-client tests pass.                                                                                                                                                                                          |
| C10 | The coordinator published a candidate before its bootstrap/snapshot boundary and returned indistinguishable failures.                                                                                 | `ProfileSwitchResult`, `ProfileSwitchPhase`, and `ProfileSwitchError` expose deterministic phases and whether the old source was confirmed released. Partial candidates are disposed without masking the primary failure; the new client is published only after bootstrap and snapshot. No implicit old-profile reconnect occurs.                                                                | Failure-phase/candidate cleanup and durable profile-return tests pass. Full actual-client A→B→A with Tor is not claimed and remains listed as an environment gap.                                                                                                                                                                                                                              |
| C11 | CLI prompts/profile checks/daemon startup occurred before frontend invocation, and the launch DTO retained resolved startup state.                                                                    | Launch contract 2 passes a deferred `FrontendHost`. The base-owned `LocalFrontendHost` and public factory provide state, enumeration, creation, selection, autostart/attach, and one-use secret transfer. Terminal supplies its own interaction adapter.                                                                                                                                          | No-TTY fake GUI starts first, missing profile is typed, create/select consumes its secret, ask/never/always and remote behavior pass. A built test-only fake frontend installs beside base with no Terminal package and runs through the public entry point.                                                                                                                                   |

Key implementation paths are `metor.application.frontend`,
`metor.client.frontends`, `metor.client.ipc`, `metor.client.lifecycle`,
`metor.client.session`, `managed.engine.session_access`, `managed.writer`,
`managed.ipc`, `managed.handlers.snapshot`, `managed.network.state`,
`managed.network.router`, `managed.network.voice`, `quick_unlock`, and
`profile_destruction`.

The new host behavior was extracted from the already-large CLI handler into the
cohesive `metor.application.frontend` service. The Voice and session-access
modules remain large cohesive state machines; splitting transaction logic during
this security repair would have increased lock-order and rollback risk. Their
future decomposition should follow transactional ownership, not line-count-only
fragments.

## Quality and generated-reference commands

Executed from the checkout with CPython 3.11.4 on Linux x86_64 under WSL2
(`6.18.33.2-microsoft-standard-WSL2`):

```text
ruff check src/metor/ scripts/ tests/                         PASS
ruff format --check src/metor/ scripts/ tests/                PASS
mypy src/metor/ scripts/                                      PASS (282 files)
python -m mypy --platform win32 .../quick_unlock.py            PASS (supplementary)
python -m unittest discover -s tests -p 'test_*.py'            PASS (423 tests, 0 skips)
python scripts/validate_generated_docs.py                      PASS, two reproducible runs
python scripts/versioning.py validate                          PASS
```

The generated API/settings/schema/compatibility files had no drift after the
canonical two-pass validator. No generated file was edited manually.
The unittest run reported zero skipped tests. Native/platform gates that could
not be run are listed as unverified below rather than represented as skips or
passes.

Three clean wheels were built outside the checkout with
`pip wheel --no-deps --no-build-isolation` and validated together:

```text
metor-0.2.0-py3-none-any.whl             379597 bytes
  SHA256 12577461c7d02b2599599c77bc29da28a5230301aee92ca443d9f17e4796a00b
metor_sdk-0.2.0-py3-none-any.whl          71601 bytes
  SHA256 e959b9e1553d94b7eb07c8908e2d331967ab0621708e75697eb3090744844ef8
metor_ui_terminal-0.2.0-py3-none-any.whl   60694 bytes
  SHA256 f7662ef4f23cbdd78e617923218cd92521dccd09f1167e141fff90d59b041934
All Metor wheels report 0.2.0.
```

## Built-artifact installation matrix

All environments were fresh `/tmp` virtual environments without editable
installs, source `PYTHONPATH`, or `--system-site-packages`. Import checks used
isolated interpreter mode (`python -I`) where applicable, and every environment
ran `pip check`.

| Environment                | Observed result                                                                                                                                                                                                                                 |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SDK only                   | PASS. `metor.client`, `metor.core.api`, `metor.core.auth`, neutral frontend contracts, and proof construction imported from site-packages. `metor.data`, `metor.core.daemon`, and `metor.ui` were absent.                                       |
| Base + SDK                 | PASS. General help, version `0.2.0`, and `metor-daemon --help` worked. Selecting missing Terminal returned the explicit install error before daemon/profile bootstrap. `metor.ui` was absent.                                                   |
| Base + Terminal            | PASS. Installed entry point metadata selected only `terminal`; help/version/chat help and a real PTY first-run invocation worked; in-UI upper help remains covered by the Terminal renderer tests.                                              |
| Base + test-only fake GUI  | PASS. The separately built fake entry point printed `FAKE_GUI_STARTED` before querying the host, observed missing-profile state, received typed bootstrap failure, and installed with no `metor.ui` package. It is not part of a shipped wheel. |
| Frontend metadata variants | PASS in `test_refactor2_cli_contract`: duplicates, missing/broken/incompatible plugins, selected-only load, explicit/environment/default precedence, and user payload containing `--ui`.                                                        |
| Ownership                  | PASS. Pairwise intersections of non-`.dist-info` wheel members were empty.                                                                                                                                                                      |
| Uninstall/reinstall        | PASS. Removing Terminal left base+SDK functional; removing base left SDK functional; reinstalling the exact two local wheels with `--no-index` restored Terminal and `pip check` stayed green.                                                  |
| Linux wheelhouse/ZIP       | PASS. The canonical builder produced SDK, base, and Terminal `linux-x86_64-py311` ZIPs. Each archive's offline installer created its own venv; imports, SQLCipher backend, CLI entry points, frontend inventory, and `pip check` passed.        |
| Windows wheelhouse/ZIP     | UNVERIFIED locally. The Windows builder/installer contract tests pass, but a Windows dependency wheelhouse was not manufactured on Linux.                                                                                                       |

## R2-T01–R2-T36 traceability

| Requirements | Evidence                                                                                                          | Status                                                      |
| ------------ | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| T01          | SDK-only wheel import/use matrix                                                                                  | PASS Linux                                                  |
| T02–T03      | quick-unlock permission, unsafe-parent, metadata, helper timeout, effective ACL model                             | PASS Linux/mocked ACL; native Windows T03 unverified        |
| T04–T07      | auth fallback, rate limit, PIN/NONE strength, purpose grant, conservative purge matrix                            | PASS                                                        |
| T08–T09      | actual destruction dispatch and complete phase/failure matrix                                                     | PASS                                                        |
| T10          | slow/failed bounded writer through daemon dispatch                                                                | PASS                                                        |
| T11–T14      | selection/fallback generations, stale ACK, serialization, full-duplex and unrelated progress                      | PASS                                                        |
| T15–T21      | Voice quota, draft, persistence rollback, promotion/restart, duplicates, ACK distinction, bounded segmented reads | PASS                                                        |
| T22–T24      | snapshot mutation barrier, publication ordering, recovery-state distinction                                       | PASS                                                        |
| T25–T27      | fresh retained-media discovery/read/release, pagination/privacy, request/event generations                        | PASS                                                        |
| T28          | typed coordinator and durable profile return                                                                      | PARTIAL: controlled tests pass; actual Tor A→B→A unverified |
| T29          | local-only normal exit and purge precedence                                                                       | PASS                                                        |
| T30–T32      | UI-free help, Terminal help ownership, deterministic plugin selection                                             | PASS                                                        |
| T33          | built wheel ownership plus uninstall/reinstall                                                                    | PASS Linux                                                  |
| T34          | Linux built wheel/ZIP smoke                                                                                       | PASS Linux; native Windows unverified                       |
| T35          | complete Terminal/contact/history/privacy/read-receipt/DROP regressions                                           | PASS                                                        |
| T36          | canonical generated-doc and compatibility reproducibility                                                         | PASS                                                        |

## Original scenarios A–T

| Scenario | Regression evidence                                                                           | Status                                                                      |
| -------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| A–B      | selective atomic fallback, exact identity, mixed-selection rejection, bulk compatibility      | PASS                                                                        |
| C–D      | disconnected LIVE rejection and genuine reconnect/grace replay                                | PASS                                                                        |
| E        | headless unseen overflow terminates without ACK and preserves sender pending state            | PASS                                                                        |
| F–J      | DROP-only clear, delivery-aware reads/receipts, local delete, LIVE dismiss safety             | PASS                                                                        |
| K        | snapshot retry, mutation barrier, publication sequence, restricted fan-out                    | PASS                                                                        |
| L        | simultaneous inbound/outbound Voice plus Text and serialized frames                           | PASS controlled sockets; real Tor not run                                   |
| M–N      | resume offset, one identity, terminal ACK, LIVE→DROP promotion and stale-generation rejection | PASS                                                                        |
| O        | pressure/hard limit, admitted-prefix finalization, explicit DROP draft, capacity release      | PASS                                                                        |
| P        | client-local restriction, exact locked media, privacy and anonymous handles                   | PASS                                                                        |
| Q        | PIN failure escalation, password recovery, next-cycle PIN, no cold PIN unlock                 | PASS                                                                        |
| R        | local preservation, typed coordinator, no implicit reconnect/fallback                         | PARTIAL: isolated persistence/component coverage; real Tor A→B→A unverified |
| S        | normal exit waits only for durable local preservation                                         | PASS                                                                        |
| T        | purge fence beats Voice/fallback/reconnect; key-first destruction and observable result       | PASS                                                                        |

## Public GUI integration map

- Launcher contract: `FRONTEND_LAUNCH_CONTRACT_VERSION == 2`; entry-point
  preflight still occurs before profile or daemon side effects.
- Deferred host: `create_local_frontend_host()` returns `FrontendHost` with
  `profile_state`, `list_profiles`, `create_profile`, `select_profile`, and
  `bootstrap`. Frontend callbacks own confirmation, secret entry, and status
  presentation.
- Secrets: profile creation and daemon session-auth use `OneUseSecretProvider`;
  references are cleared on first take. Python cannot guarantee erasure of all
  interpreter copies, so no stronger memory-erasure claim is made.
- Runtime projection: use snapshot/revision/epoch for content-free state; retain
  request results, media bytes, and command events separately. Reconnect replaces
  decoder/queues/workers by generation.
- Retained media: enumerate with `ListRetainedMessagesCommand`, read bounded
  ranges with `GetVoiceChunkCommand`, then explicitly consume with
  `ReleaseVoiceCommand`.
- Locked media: only the frozen inbound LIVE peer/message/current logical context
  is readable/releasable. DROP/history/general inventory remains denied.
- Profile switching: handle `ProfileSwitchError.phase` and
  `source_released`; never assume rollback or reconnect of the old profile.
- Destruction authorization: prior authenticated lifecycle capability is always
  required. With `daemon.self_destruct_requires_unlock=true`, normal
  reauthorization is an additional gate. `false` relaxes only that extra gate;
  it never grants a new/unauthenticated/restricted session purge authority.
  Surface initiated, key-destroyed, completed, cleanup-failed, or transport-loss
  unknown state without promising filesystem cleanup before key destruction.

## Explicitly unverified and excluded work

- Native Windows execution, including effective PowerShell ACL creation and
  validation on temporary paths with spaces, Windows wheelhouse resolution, ZIP
  installation, and Windows unit/artifact gates. Win32 MyPy and Windows contract
  tests are supplementary only.
- Bare-metal Linux, macOS, ARM, GPIO, microphone/speaker, display, audio latency,
  suspend/resume, and actual Tor-network interoperability/performance.
- A real Tor-backed A→B→A coordinator run and physical full-duplex audio. Their
  component, persistence, socket, and controlled-collaborator coverage passed,
  but those results are not relabeled as native/Tor evidence.
- Independent reviewer acceptance and CI after the final commit. No branch push,
  release publication, or production peer/profile operation was performed.
- GUI screens, toolkit, layout, hardware/config schema, and ownership policy for
  disposable GUI recording drafts. These remain for the separate GUI workstream.
