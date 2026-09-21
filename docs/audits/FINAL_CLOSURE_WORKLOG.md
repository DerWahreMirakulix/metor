# Final closure worklog

This is the single resumable worklog for closure packages A00–A25. Historical
reports remain evidence and are not competing implementation backlogs.

## Baseline

- Starting SHA: `bb7ae07b5f83f8cae9ac8f38c35f9a9a757a43d7`
- Starting branch/worktree: `embeddedui`, tracking `origin/embeddedui`, clean
- Environment: WSL2 Linux x86_64, kernel 6.18.33.2, Python 3.11.4 at
  `/home/yoda/miniconda3/bin/python`, Node 24.18.0, npm 11.16.0
- Unavailable baseline environments: native Windows and Python 3.12/3.13
- Unavailable design evidence: no Penpot connector is installed in this
  environment; the pinned revision therefore remains an explicit native visual
  evidence gap rather than an inferred result
- Version registry: application 0.2.0; IPC 2 (minimum 2); peer 3 (minimum 3);
  DB 4 (minimum 3); keyslot/blob 1; profile-key/blob-object derivation 1;
  frontend launch contract 2
- Distributions: `metor-sdk`, `metor`, `metor-ui-terminal`, `metor-ui-gui`
- Active frontend entry points: `terminal`, `gui`
- Tracked inventory: 763 files, including 549 Python files
- Functional specification SHA-256:
  `8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7`
- Layout specification SHA-256:
  `3202019b3fd3e7aef472d281006cdb35c1caf073dbaaf2ee75bf691eeaadf5b0`
- The two checked-in `docs/.temp/` copies match those hashes. They remain
  historical evidence until package A21 updates active references and removes
  the duplicates.

Every tracked file is assigned by the following complete, precedence-ordered
ownership map. Counts sum to 763; no path is unclassified.

| Class                   | Paths                                                                                                  | Count |
| ----------------------- | ------------------------------------------------------------------------------------------------------ | ----: |
| Test                    | `tests/**`                                                                                             |    84 |
| UI                      | `src/metor/ui/**`                                                                                      |   256 |
| SDK                     | `src/metor/{versioning,client,shared}/**`, `src/metor/core/{api,auth}/**`                              |    67 |
| Runtime                 | Remaining `src/**`                                                                                     |   208 |
| Generated reference     | `docs/generated/**`                                                                                    |     4 |
| Immutable specification | The two canonical GUI specifications in `docs/specs/`                                                  |     2 |
| Historical evidence     | `docs/audits/**`, `docs/.temp/**`                                                                      |    83 |
| Active documentation    | Remaining `docs/**`, `README.md`, `AGENTS.md`, `LICENSE`                                               |    16 |
| Build/Release           | `packaging/**`, `scripts/**`, `requirements/**`, repository/CI/editor configuration and build metadata |    43 |

## Package status

| Package | State    | Changed files                                                                                                   | Verification         | Next step                                                                  |
| ------- | -------- | --------------------------------------------------------------------------------------------------------------- | -------------------- | -------------------------------------------------------------------------- |
| A00     | verified | `docs/audits/FINAL_CLOSURE_WORKLOG.md`                                                                          | Baseline gates below | Complete                                                                   |
| A01     | verified | `src/metor/data/sql/manager.py`, `tests/test_gui_purge.py`, this worklog                                        | A01 gates below      | Complete                                                                   |
| A02     | verified | `src/metor/core/tor.py`, `tests/test_tor_path_resolution.py`, `tests/test_closure_integration.py`, this worklog | A02 gates below      | Complete                                                                   |
| A03     | verified | `src/metor/utils/{constants,security}.py`, `tests/test_security_contract.py`, this worklog                      | A03 gates below      | Complete                                                                   |
| A04     | verified | `src/metor/shared/security.py`, `tests/test_security_contract.py`, this worklog                                 | A04 gates below      | Complete                                                                   |
| A05     | verified | `src/metor/utils/lock.py`, `tests/test_lock_contract.py`, this worklog                                          | A05 gates below      | Complete                                                                   |
| A06     | verified | `src/metor/data/profile/{support,paths,manager,catalog,lifecycle}.py`, `src/metor/data/profile/migration/{journal,orchestrator}.py`, `tests/test_profile_path_security.py`, this worklog | A06 gates below | Complete |
| A07     | verified | `src/metor/{utils/process.py,data/profile/manager.py,application/runtime/maintenance.py,application/frontend/host.py,core/tor.py}`, `tests/test_application_runtime_contract.py`, this worklog | A07 gates below | Complete |
| A08     | verified | `src/metor/core/api/{base.py,events/shared.py,events/entries.py}`, `tests/test_ipc_type_validation.py`, this worklog | A08 gates below | Complete |
| A09     | verified | `scripts/{generate_api_docs.py,release/compatibility.py}`, `docs/generated/{API.md,api.schema.json,compatibility.json}`, `tests/test_api_generation_contract.py`, this worklog | A09 gates below | Complete |
| A10–A25 | open     | None                                                                                                            | Not run              | A10: repair CLI argument loss                                                |

## A00 verification

Commands were run from the starting SHA on 21 September 2026. The first full
suite and installed-artifact attempts ran inside a socket-restricted sandbox and
produced artificial socket failures; they are environment diagnostics, not
repository failures. Both were rerun with local socket access, and only the
reruns are acceptance results.

| Command                                                                                                                      | Result                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `python -m ruff check src/metor/ scripts/ tests/`                                                                            | PASS                                                                             |
| `python -m ruff format --check src/metor/ scripts/ tests/`                                                                   | PASS; 546 files already formatted                                                |
| `python -m mypy src scripts/`                                                                                                | PASS; 462 source files                                                           |
| `python scripts/check_boundaries.py`                                                                                         | PASS                                                                             |
| `python scripts/versioning.py validate`                                                                                      | PASS                                                                             |
| `python scripts/validate_generated_docs.py`                                                                                  | PASS; fresh and reproducible                                                     |
| `python -m unittest discover -s tests -p 'test_*.py'`                                                                        | PASS outside the socket sandbox; 676 tests in 625.610 seconds                    |
| Four `python -m pip wheel --no-deps --no-build-isolation ...` builds followed by `python scripts/validate_wheel_versions.py` | PASS; all four distributions report 0.2.0                                        |
| `python scripts/build_release_wheelhouse.py --variant all --skip-pip-upgrade --output-dir <temporary>`                       | PASS with network access; four Linux x86_64 CPython 3.11 bundles                 |
| `python scripts/validate_installed_artifacts.py <temporary-bundle-root>`                                                     | PASS outside the socket sandbox; isolated SDK/base/UI and both UI-removal orders |
| `python scripts/validate_release_installers.py <temporary-bundle-root>`                                                      | PASS; all four native offline ZIP installers                                     |

No native Windows, Python 3.13, Penpot, real desktop session, real audio route,
or physical-device gate was executed in A00. Those are recorded environment or
later-package gates, not passes. The repository worktree was clean again after
all generators and tests.

## A01 verification

`SqlManager.close_connection()` now serializes against active database work and
does not discard pooled connection or repository ownership until the underlying
connection confirms close. A lower close exception propagates to the existing
release/destruction coordinators, which continue independent key and cleanup
steps but suppress runtime-released, Safe, and successful profile-exit outcomes.
The retained pool state permits a later release attempt. An already absent
connection remains an idempotent success.

No wire, database-schema, keyslot, blob, derivation, launcher, or application
version changes are required: this corrects error reporting and retry state for
the current runtime contract.

| Command                                                                                                                                                                                                                                                                                                     | Result                                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Focused lower-close destruction regression before implementation                                                                                                                                                                                                                                            | EXPECTED FAIL; the injected `connection.close()` error was swallowed |
| `python -m unittest -v test_gui_purge test_daemon_lock_lifecycle test_final_remediation_contract.FinalRemediationContractTests.test_destruction_attempts_disk_key_after_every_preparation_failure test_closure_integration.ClosureDaemonTests.test_release_failure_attempts_all_resources_and_retries_stop` | PASS; 10 tests in 29.123 seconds with local IPC socket access        |
| `python -m unittest -v test_data_persistence_contract test_gui_metadata test_profile_storage_security test_gui_lifecycle`                                                                                                                                                                                   | PASS; 71 tests in 79.621 seconds with local IPC socket access        |
| Focused lower-close destruction regression after implementation                                                                                                                                                                                                                                             | PASS; retry succeeds and a third close is idempotent                 |
| `python -m ruff check src/metor/data/sql/manager.py tests/test_gui_purge.py`                                                                                                                                                                                                                                | PASS                                                                 |
| `python -m ruff format --check src/metor/data/sql/manager.py tests/test_gui_purge.py`                                                                                                                                                                                                                       | PASS                                                                 |
| `python -m mypy src/metor/data/sql/manager.py src/metor/core/profile_destruction.py src/metor/core/daemon/managed/engine/release.py src/metor/core/daemon/managed/engine/lifecycle.py`                                                                                                                      | PASS; 4 source files                                                 |
| `git diff --check`                                                                                                                                                                                                                                                                                          | PASS                                                                 |

## A02 verification

Tor process ownership is now released only after an already-ended poll or a
successful bounded wait. A terminate error or timeout falls through to kill and
a second bounded wait. Unconfirmed exit retains the process reference and raises
to the caller. Runtime-key cleanup is attempted independently, missing files are
idempotent, and access/removal failures propagate into the existing release
coordinator. Consequently, failed Tor release leaves the daemon in `LOCKING`,
retains runtime owners for retry, and cannot emit a prepared-exit or Safe result.

`src/metor/core/tor.py` is above the 500-line review threshold, but the modified
behavior remains its existing cohesive responsibility: lifecycle of one Tor
process and that process's exported plaintext key. Extracting these two atomic
release steps would fragment ownership without reducing unrelated behavior. No
new subsystem or compatibility axis is introduced.

| Command                                                                                                                                                                                                                                                                                | Result                                                                     |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `python -m unittest -v test_tor_path_resolution.TorLifecycleTests` before implementation                                                                                                                                                                                               | EXPECTED FAIL; 5 of 6 tests exposed swallowed/unconfirmed release outcomes |
| `python -m unittest -v test_tor_path_resolution test_closure_integration.ClosureDaemonTests.test_tor_release_failure_blocks_prepared_exit_and_retains_runtime test_closure_integration.ClosureDaemonTests.test_release_failure_attempts_all_resources_and_retries_stop test_gui_purge` | PASS; 19 tests in 25.260 seconds with local IPC socket access              |
| `python -m ruff check src/metor/core/tor.py tests/test_tor_path_resolution.py tests/test_closure_integration.py`                                                                                                                                                                       | PASS                                                                       |
| `python -m ruff format --check src/metor/core/tor.py tests/test_tor_path_resolution.py tests/test_closure_integration.py`                                                                                                                                                              | PASS                                                                       |
| `python -m mypy src/metor/core/tor.py src/metor/core/daemon/managed/engine/release.py src/metor/core/daemon/managed/engine/lifecycle.py`                                                                                                                                               | PASS; 3 source files                                                       |
| `git diff --check`                                                                                                                                                                                                                                                                     | PASS                                                                       |

## A03 verification

Sensitive regular files are now opened without following direct links and are
validated through that same descriptor. Overwrites allocate at most one named
64-KiB block, complete every partial write, reject zero progress, sync before
removal, and preserve visible failures. Files with multiple hard links are
rejected. The pathname is checked against the opened device/inode before unlink
so a deterministically exchanged path is preserved rather than removed.

Recursive cleanup uses `lstat()`, unlinks POSIX symlinks without traversing their
targets, rejects Windows reparse points, and refuses unsupported file types.
Windows file shredding opens the reparse point itself through `CreateFileW` and
validates attributes on that handle before converting ownership to a Python file
descriptor. The Windows-specific guard is covered structurally, but native
Windows execution remains unavailable in this environment and is not claimed.

This is best-effort logical cleanup only. It does not claim physical erasure of
SSD or copy-on-write storage, backups, or external copies. No wire, database,
keyslot, blob, derivation, launcher, or application version changes are required.

| Command                                                                                                                                                                                                                                             | Result                                                                  |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| A03 reproduction supplied by the closure assignment                                                                                                                                                                                                 | CONFIRMED FINDING: whole-file allocation, partial-write unlink, and direct-link overwrite |
| `python -m unittest -v test_security_contract test_profile_storage_security test_tor_path_resolution test_gui_purge test_gui_purge_observation`                                                                                                    | PASS; 70 tests in 43.923 seconds with local IPC socket access           |
| `python -m ruff check src/metor/utils/security.py src/metor/utils/constants.py tests/test_security_contract.py`                                                                                                                                     | PASS                                                                    |
| `python -m ruff format --check src/metor/utils/security.py src/metor/utils/constants.py tests/test_security_contract.py`                                                                                                                            | PASS; 3 files already formatted                                         |
| `python -m mypy src/metor/utils/security.py src/metor/core/profile_keys.py src/metor/core/tor.py src/metor/core/profile_destruction.py src/metor/core/daemon/managed/engine/lifecycle.py src/metor/data/profile/lifecycle.py src/metor/data/profile/migration src/metor/data/sql/runtime_mirror.py` | PASS; 11 source files                                                    |
| `python scripts/check_boundaries.py`                                                                                                                                                                                                                | PASS                                                                    |
| `git diff --check`                                                                                                                                                                                                                                  | PASS                                                                    |

## A04 verification

`secure_clear_buffer()` now rejects read-only views with `TypeError` and
non-C-contiguous views with `BufferError`, leaving both unchanged. A mutable
C-contiguous view is cast to bytes and cleared using that byte view's full
`nbytes`, so typed views no longer confuse element count with byte count.
Bytearrays, empty views, and repeated clearing retain their existing successful
contract.

The helper remains in the host-free shared/SDK package. This is best-effort
clearing of the caller-owned mutable view only; it does not claim to remove
immutable Python copies or independently owned native buffers. No compatibility
version changes are required.

| Command                                                                                                                                                                                                                                                                | Result                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Three focused `secure_clear_buffer` regressions before implementation                                                                                                                                                                                                   | EXPECTED FAIL; typed view raised `ValueError` and strided view had no explicit `BufferError` contract |
| `python -m unittest -v test_security_contract test_session_auth_contract test_profile_storage_security test_data_persistence_contract test_closure_architecture`                                                                                                       | PASS; 87 tests in 34.664 seconds with local IPC socket access             |
| `python -m ruff check src/metor/shared/security.py tests/test_security_contract.py`                                                                                                                                                                                     | PASS                                                                      |
| `python -m ruff format --check src/metor/shared/security.py tests/test_security_contract.py`                                                                                                                                                                            | PASS; 2 files already formatted                                           |
| `python -m mypy src/metor/shared/security.py src/metor/core/key.py src/metor/core/auth src/metor/core/daemon/managed/local_auth.py src/metor/data/blob/store.py src/metor/data/sql/manager.py src/metor/core/profile_keys.py`                                              | PASS; 9 source files                                                       |
| `python scripts/check_boundaries.py`                                                                                                                                                                                                                                    | PASS                                                                      |
| `git diff --check`                                                                                                                                                                                                                                                      | PASS                                                                      |

## A05 verification

Lock acquisition now writes the complete ownership payload, rejects zero write
progress, and rolls back every write or sync failure after exclusive creation.
Rollback and ordinary release close the descriptor before removing the pathname,
retain ownership after an unconfirmed close, and remove the pathname only when
its device/inode still identifies the created lock. A replacement lock is
preserved in both release and failed-acquisition paths.

Acquisition deadlines now use the monotonic clock. Stale-owner classification is
tri-state: confirmed matching lifetime remains live, confirmed process absence
or PID lifetime mismatch is stale, and missing creation metadata or
`AccessDenied` remains unknown and is never treated as proof of a crash. Empty
metadata therefore cannot be removed merely because it is old.

The real child-process exclusion test passed on Linux. It is written using the
same filesystem protocol on Windows, but native Windows execution is unavailable
in this environment and is not claimed. No compatibility version changes are
required.

| Command                                                                                                                                                      | Result                                                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| `python -m unittest -v test_lock_contract` before implementation                                                                                             | EXPECTED FAIL; 6 failures covered rollback leaks, partial writes, close hiding, wall-clock deadline, and unknown identity |
| `python -m unittest -v test_lock_contract test_settings_contract test_profile_storage_security test_data_persistence_contract`                              | PASS; 92 tests in 11.162 seconds with local IPC socket access                  |
| `python -m ruff check src/metor/utils/lock.py tests/test_lock_contract.py`                                                                                    | PASS                                                                            |
| `python -m ruff format --check src/metor/utils/lock.py tests/test_lock_contract.py`                                                                           | PASS; 2 files already formatted                                                 |
| `python -m mypy src/metor/utils/lock.py src/metor/data/settings.py src/metor/data/profile/config/config.py`                                                  | PASS; 3 source files                                                            |
| `python scripts/check_boundaries.py`                                                                                                                         | PASS                                                                            |
| `git diff --check`                                                                                                                                           | PASS                                                                            |

## A06 verification

Public profile identities now retain the existing exact semantic contract:
one to 255 Unicode alphanumeric, dash, or underscore characters. Invalid names
are rejected rather than stripped into a different identity. `Paths` enforces
that contract before recovery or profile I/O and rejects an existing root that
is a symbolic link, Windows reparse point, or non-directory. Catalog discovery
uses the same rules and never follows path aliases.

Security migration now uses an explicit internal factory bound to the exact
`.<profile>.security-migration.staged` child beneath `Constants.DATA`; ordinary
`ProfileManager` construction cannot opt out of public validation. Invalid
absolute paths, traversal, both separator forms, empty/dotted/overlong names,
and link roots cannot select another profile. Global purge enumerates validated
public profiles before its existing bounded recursive cleanup, so transaction
artifacts and aliases are not misclassified as public identities.

Existing encrypted/plaintext migrations, password rewrap, pre-commit abort,
post-commit recovery, and GUI/CLI profile operations remain green. Native
Windows reparse behavior is structurally covered but not executed on Windows in
this environment. No compatibility version changes are required.

| Command                                                                                                                                         | Result                                                                     |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `python -m unittest -v test_profile_path_security` before implementation                                                                        | EXPECTED FAIL; strict public validators and explicit staging factory did not exist |
| `python -m unittest -v test_profile_path_security test_profile_storage_security test_gui_profiles test_application_runtime_contract test_settings_contract` | PASS; 87 tests in 11.581 seconds with local IPC socket access             |
| `python -m unittest test_gui_purge test_profile_storage_security.ProfileStorageSecurityTests.test_profile_destruction_is_idempotent_when_files_are_missing` | PASS; 7 tests in 24.971 seconds with local IPC socket access              |
| `python -m ruff check src/metor/data/profile tests/test_profile_path_security.py`                                                               | PASS                                                                       |
| `python -m ruff format --check src/metor/data/profile tests/test_profile_path_security.py`                                                      | PASS; 15 files already formatted                                           |
| `python -m mypy src/metor/data/profile`                                                                                                         | PASS; 14 source files                                                      |
| `python scripts/check_boundaries.py`                                                                                                            | PASS                                                                       |
| `git diff --check`                                                                                                                              | PASS                                                                       |

## A07 verification

New daemon and Tor PID metadata binds the PID to its process creation time and
exact public profile. PID-only legacy state remains readable for ordinary status
checks but is insufficient to authorize termination. Cleanup now requires a
matching process lifetime, current OS account, profile metadata, and exact
supported command shape. Unknown ownership, `AccessDenied`, PID reuse, malformed
metadata, and profile mismatch preserve both process and state while emitting a
diagnostic.

Daemon recognition covers the canonical `metor daemon`, the installed
`metor-daemon` headless entry, and the actual internal
`python -m metor.daemon_main ... daemon` launch without substring matching.
Foreign scripts and lookalike executables are rejected. Tor additionally requires
the exact profile-owned `DataDirectory` and `HiddenServiceDir`. Profile discovery
does not follow symlink or Windows-reparse directory aliases. Force discovery can
only act on an exact command with an explicit known profile.

Linux ownership paths were executed. Windows username matching and
`AccessDenied` are covered structurally; native Windows execution remains
unavailable and is not claimed. Runtime PID metadata is ephemeral and its legacy
read path is retained, so no wire, storage, launcher, or application version bump
is required.

| Command                                                                                                                                                                                                       | Result                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Three focused ownership regressions before implementation                                                                                                                                                      | EXPECTED FAIL; 11 errors exposed missing profile arguments, lifetime metadata, and OS-owner validation |
| `python -m unittest test_application_runtime_contract test_tor_path_resolution test_daemon_lock_lifecycle test_gui_profiles`                                                                                  | PASS; 36 tests in 0.738 seconds with local IPC socket access         |
| `python -m unittest -v test_application_runtime_contract test_tor_path_resolution test_platform_contracts` plus three focused daemon-entrypoint release tests                                                 | PASS; 29 tests in 0.166 seconds                                      |
| `python -m ruff check src/metor/utils/process.py src/metor/data/profile/manager.py src/metor/application/runtime/maintenance.py src/metor/application/frontend/host.py src/metor/core/tor.py tests/test_application_runtime_contract.py` | PASS                                                                 |
| `python -m ruff format --check src/metor/utils/process.py src/metor/data/profile/manager.py src/metor/application/runtime/maintenance.py src/metor/application/frontend/host.py src/metor/core/tor.py tests/test_application_runtime_contract.py` | PASS; 6 files already formatted                                     |
| `python -m mypy src/metor/utils/process.py src/metor/data/profile/manager.py src/metor/application/runtime/maintenance.py src/metor/application/frontend/host.py src/metor/core/tor.py`                      | PASS; 5 source files                                                 |
| `python scripts/check_boundaries.py`                                                                                                                                                                           | PASS                                                                 |
| `git diff --check`                                                                                                                                                                                             | PASS                                                                 |

## A08 verification

The existing IPC decoder now validates every decoded value recursively against
the registered DTO annotation. Both `typing.Union` and PEP 604 unions preserve
explicit optional nulls; primitives use exact JSON-compatible runtime types so
a Boolean cannot satisfy an integer field. Lists and sequences validate every
element, mappings validate both keys and values, and nested dataclasses reject
unknown fields and require their declared content discriminator. Recursive
`JsonValue` mappings remain open to arbitrary JSON trees while rejecting
non-JSON Python objects.

The nested-entry compatibility helpers now delegate to the same validator for
each entry, including mixed or later list elements, rather than retaining a
second permissive hydration path. `VoiceContent.duration_ms` consequently
preserves explicit `None`, accepts an integer, and rejects strings and Booleans;
unknown duration is not converted to zero. Request IDs, epochs, and revisions
retain their existing nullable envelope behavior, with integer revisions now
rejecting Booleans.

This enforces the already-declared DTO annotations and rejects inputs that were
never valid under the generated contract. It adds no route, field, peer format,
or IPC format and therefore requires no compatibility-axis or application
version bump. `base.py` remains below the mandatory 500-line decomposition
review threshold, and the added behavior is its existing cohesive
responsibility: strict JSON-to-DTO hydration.

| Command | Result |
| ------- | ------ |
| `python -m unittest -v test_ipc_type_validation` before implementation | EXPECTED FAIL; accepted Boolean integers, bad later list/dictionary values and arbitrary open-map objects, while valid structured content and explicit Voice null failed |
| `python -m unittest -v test_ipc_type_validation` | PASS; 7 tests, including valid JSON roundtrips for all 66 command and 160 event registrations |
| `python -m unittest -v test_raw_client_contract` | PASS; 3 tests in 4.316 seconds with local IPC socket access |
| `python -m unittest -v test_gui_handoff test_gui_metadata test_ui_boundaries test_session_auth_contract test_history_contract test_gui_pages test_gui_producers test_embedded_contract test_closure_security` | PASS; 70 tests in 142.071 seconds with local IPC socket access |
| `python -m unittest -v test_ipc_type_validation test_ui_boundaries test_history_contract test_message_architecture_contract test_ui_ipc_contract` | PASS; 62 tests |
| Three focused `test_daemon_hardening.DaemonHardeningTests` IPC writer/rejection/dispatch tests | PASS; 3 tests in 0.008 seconds with local socket-pair access |
| `python -m ruff check src/metor/core/api/base.py src/metor/core/api/events/shared.py src/metor/core/api/events/entries.py tests/test_ipc_type_validation.py` | PASS |
| `python -m ruff format --check src/metor/core/api/base.py src/metor/core/api/events/shared.py src/metor/core/api/events/entries.py tests/test_ipc_type_validation.py` | PASS; 4 files already formatted |
| `python -m mypy src/metor/core/api/base.py src/metor/core/api/events/shared.py src/metor/core/api/events/entries.py` | PASS; 3 source files |
| `python scripts/check_boundaries.py` | PASS |
| `git diff --check` | PASS |

## A09 verification

API examples now resolve annotations before constructing required values and
recursively construct nested dataclasses with their exact discriminators. All
66 command and 160 event examples therefore pass the real decoder, including
structured text content for `send_message` and `message_received`.

The schema generator now emits typed `Sequence` items, typed dictionary values,
strict nested DTO objects, exact content discriminator constants, and a
recursive `JsonValue` definition. Unsupported annotations abort generation
instead of silently degrading to `{}`. The generated schema and API reference
state that the schema root is a route/definition catalog: consumers select the
matching `commands` or `events` reference to validate a complete message,
rather than treating the catalog root as a complete message validator. Route
discriminators are required constants in those definitions; the compatibility
checker ignores only their first schema representation because route presence
and removal are already compared by the catalog keys.

The unchanged compatibility comparator classifies the two formerly `{}`
history sequence schemas as narrowings when the new schema is compared directly
with the internal A08 artifact. This is a reviewed documentation correction:
both fields were already declared and decoded as typed sequences, A08 made that
existing decoder contract complete, and Metor has no prior public release. The
release compatibility gate therefore accepts the corrected artifact as the
first baseline. No route, field, peer wire, persisted format, compatibility
generation, or application version changed.

`scripts/generate_api_docs.py` is 562 lines after the change, so decomposition
was evaluated. Its single responsibility remains generating the paired Markdown
and machine-readable views from the same registries; separating annotation
resolution at this size would duplicate or obscure that shared contract. It
remains below the exceptional 800-line ceiling and introduces no new subsystem.

| Command | Result |
| ------- | ------ |
| `python -m unittest -v test_api_generation_contract` before implementation | EXPECTED FAIL; invalid content examples, untyped dictionary values, permissive open mappings, missing catalog semantics, and silent unknown annotations were reproduced |
| `python -m unittest -v test_api_generation_contract` | PASS; 6 tests covering all 226 examples, complete route definitions, negative containers/discriminators, open JSON, fail-closed annotations, compatibility classification, and repeated generation |
| `python scripts/generate_api_docs.py` and `python scripts/generate_compatibility_manifest.py` | PASS; canonical API, schema, and compatibility artifacts regenerated from source |
| `python scripts/validate_generated_docs.py` | PASS; all four generated artifacts remained byte-identical across two generations |
| Direct `ipc_breaking_changes()` comparison with the A08 checked-in schema | REVIEWED; only `history_data.entries` and `history_raw_data.entries` schema corrections classified as narrowed |
| `python scripts/check_release_compatibility.py --current docs/generated/compatibility.json` | PASS; first public baseline, no automatic bump |
| `python scripts/versioning.py validate` | PASS; application 0.2.0 and IPC generation 2 remain valid |
| `python -m unittest -v test_api_generation_contract test_ipc_type_validation test_message_architecture_contract test_versioning_release` | PASS; 51 tests in 3.294 seconds |
| `python -m ruff check scripts/generate_api_docs.py scripts/release/compatibility.py tests/test_api_generation_contract.py` | PASS |
| `python -m ruff format --check scripts/generate_api_docs.py scripts/release/compatibility.py tests/test_api_generation_contract.py` | PASS; 3 files already formatted |
| `python -m mypy scripts/generate_api_docs.py scripts/release/compatibility.py` | PASS; 2 source files |
| `python scripts/check_boundaries.py` | PASS |
| `git diff --check` | PASS |
