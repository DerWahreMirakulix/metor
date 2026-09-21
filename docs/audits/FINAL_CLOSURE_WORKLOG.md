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
| A02     | verified | `src/metor/core/tor.py`, `tests/test_tor_path_resolution.py`, `tests/test_closure_integration.py`, this worklog | A02 gates below      | A03: bound secure cleanup and reject unsafe link/partial-write cases       |
| A03     | open     | None                                                                                                            | Not run              | Inspect every secure-file cleanup caller and supported filesystem behavior |
| A04–A25 | open     | None                                                                                                            | Not run              | Follow the mandated package order, including A10b                          |

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
