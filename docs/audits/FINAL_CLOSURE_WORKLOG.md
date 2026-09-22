# Final closure worklog

This is the single resumable worklog for closure packages A00–A25. Historical
reports remain evidence and are not competing implementation backlogs.

## Current targeted follow-up status

| Package | State       | Commit                       | Tests                                                                                        | Result                                                    | Next step                                                          |
| ------- | ----------- | ---------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------ |
| R01     | implemented | `7e7ab8e`                    | `test_lock_contract` plus settings/profile/security neighbors; 103 tests; Ruff; format; mypy | PASS on Linux; Windows static typing passes for `lock.py` | Native Windows lock execution remains an R05/R07 gate              |
| R02     | implemented | R02 checkpoint (this commit) | Parser/frontend/host-policy/chat/release neighbors; 78 tests; Ruff; format; mypy              | PASS on Linux                                           | Continue with the literal dispatcher boundary in R03               |
| R03     | open        | —                            | —                                                                                            | —                                                         | Preserve the parser literal boundary through dispatch              |
| R04     | open        | —                            | —                                                                                            | —                                                         | Keep managed children in the selected installation/venv            |
| R05     | open        | —                            | —                                                                                            | —                                                         | Repair Windows typing and execute the native matrix when available |
| R06     | open        | —                            | —                                                                                            | —                                                         | Make native GUI/audio evidence capability-selected and generic     |
| R07     | open        | —                            | —                                                                                            | —                                                         | Consolidate local, CI, artifact, and native acceptance evidence    |

R01 replaces path-presence ownership and rename-based stale reaping with one
persistent private lock object guarded by the operating system's exclusive file
lock. Normal acquisition, release, and crash recovery never rename or unlink
that object. POSIX uses `flock`; Windows uses the standard descriptor-region
lock while its no-reparse handle denies delete sharing. Exact descriptor/path
identity, regular-file type, single-link ownership, bounded metadata, and
owner-only POSIX mode remain fail-closed checks. Native unlock and close errors
remain visible while every descriptor is closed at most once.

The deterministic regression first terminates an actual lock-owning child, then
releases two synchronized contenders against the same retained inode. Each
contender exposes attempt/entry/release markers and shares one atomic critical
sentinel; only one enters until explicitly released, no overlap marker appears,
and the lock inode remains unchanged across crash and both acquisitions. Direct
tests also cover a running owner, timeout, FIFO/symlink/hardlink/oversize and
unreadable objects, exchange at the native-lock boundary, partial/zero writes,
write/fsync rollback, and unlock/close failures. All 103 direct lock,
settings, profile-path/storage, and security neighbors pass locally. Native
Windows behavior remains deliberately unclaimed until R05/R07.

R02 makes the missing chat daemon-start override a genuine third state. The
canonical `OptionDef` owns the single explicit `None` default; the parser no
longer repairs that field after parsing. The real grammar now preserves
absent/positive/negative intent as `None`/`True`/`False` for both Terminal and
GUI, while its mutually exclusive group still rejects contradictory flags.
Dispatcher coverage proves the value reaches the frontend-host boundary
unchanged, and the production host resolver proves that `None` retains each
configured `ask`/`always`/`never` policy while explicit flags override it.
Help and frontend inventory remain profile- and daemon-side-effect free. All
78 parser, frontend, host-policy, Terminal chat, and release neighbors pass;
Ruff, format, and strict mypy pass for the changed production surface.

## Current follow-up status

| Package | State       | Commit    | Tests                                                                                                                                                 | Next step                                                                       |
| ------- | ----------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| N01     | verified    | `1834520` | CLI, daemon bootstrap, release parser, GUI parser; Ruff; mypy                                                                                         | Complete                                                                        |
| N02     | verified    | `e033e7e` | Runtime/cleanup, Tor/Stem, live shebang; Ruff; mypy                                                                                                   | Complete                                                                        |
| N03     | implemented | `1c50e43` | POSIX race regressions, profile/storage neighbors, Windows handle structure; Ruff; mypy                                                               | Native Windows junction/error execution remains an N11 gate                     |
| N04     | verified    | `c1770a0` | Lock modes/bounded safe reads/process generations/races/real child, settings/profile neighbors; Ruff; mypy; boundaries                                | Complete on Linux; native Windows ACL/error execution remains an N11 gate       |
| N05     | implemented | `5b9b140` | POSIX FIFO/link/type/size/TOML, configuration/launcher neighbors; Ruff; mypy                                                                          | Native Windows 3.11/3.13 mypy and ACL/reparse execution remain N09/N11 gates    |
| N06     | verified    | `8ff228f` | All DTO factories, SDK NDJSON, real daemon socket dispatcher, generated references, IPC/auth neighbors; Ruff; mypy                                    | Complete                                                                        |
| N07     | implemented | `d5aeebd` | 10k coalescing, controlled logind/session/owner/loss/startup/cleanup, Windows failure paths, GUI lifecycle/security neighbors; Ruff; mypy; boundaries | Native Windows WTS/Power and real Linux lock/suspend/resume remain N11 gates    |
| N08     | verified    | `725fc09` | Real GUI/SDK/Core inbound LIVE duplex, interruption neighbors, 20 MiB pressure; Ruff                                                                  | Controlled-port software scope complete; native audio route remains an N11 gate |
| N09     | implemented | `bc26414` | Dynamic 3.11/3.13 installer oracles, EGL/SDL workflow contract, local native renderer, release neighbors; Ruff; mypy                                  | Fresh four-lane hosted CI remains an N11 gate                                   |
| N10     | implemented | `a79de49` | 79 release/batch tests (4 native Windows skips), four fresh offline bundles/installed consumers, atomic ref rejection; Ruff; mypy                     | Native Windows batch execution and release dry run remain N11 gates             |
| N11     | blocked     | `605c54c` | 842 tests (4 native Windows skips), all static gates, four Linux bundles/consumers, native renderer and 20 MiB pressure                               | Fresh hosted CI/release dry run and mandatory native lifecycle/media gates      |

N03 cohesion review: `metor.utils.security` is now 726 physical lines because
the POSIX descriptor and Windows handle implementations must share exact entry
identity, reparse, overwrite, and removal rules. It remains one security-critical
filesystem responsibility and stays below the 800-line exceptional ceiling.
Splitting the mutually dependent native backends during the race correction
would obscure the shared invariants; a later extraction is not part of this
bounded remediation.

The N07 lifecycle neighbor run exposed one N03 caller regression: sibling blob
roots beneath a not-yet-created private parent no longer initialized. Both blob
store modes now create that parent and its two children in one anchored tree
operation; all 36 profile-storage security tests and the real switch path pass.

N06 rejects values that standard JSON cannot represent, so it narrows no valid
IPC message and requires no protocol-generation bump. The schema already uses
JSON Schema `number`; strict runtime decoding and serialization now enforce the
same finite-number domain.

N07 cohesion review: Linux provider discovery, exact session/service binding,
and signal validation moved to `platform/linux_lifecycle.py`. The 737-line
shared lifecycle module remains below the exceptional ceiling and owns one
bounded handoff/coordinator plus native source orchestration. A wider package
promotion would mix structural churn into the remaining native acceptance work.

N08 extends the existing combined controller/worker integration instead of
replacing it with a synthetic controller. A separately authenticated GUI SDK
connection subscribes to actual Core events and obtains its own producer lease;
an active controlled socket establishes the LIVE context. During a local LIVE
capture, Core persists and publishes an inbound Voice start/chunk/end sequence
plus parallel text. The real transcript and autoplay path selects only the
foreground peer, reads the exact PCM bytes through the SDK, overlaps actual
capture/output worker progress, and releases only the completely drained
inbound item. A second peer's distinct bytes remain retained and unheard, the
text draft remains unpublished, and input/output termination stays independent.

The direct capture, playback, lifecycle, security, continuation, and device
lifecycle neighbors cover microphone/output failure, focus/lock/suspend
revocation, transport loss, and generation/profile fencing. The repeated
20 MiB production worker fixture passed with 20,971,520 exact output bytes,
64 KiB maximum reads, 640-byte frames, the 16 MiB cache ceiling, and a sampled
60-record mailbox peak. These controlled ports are software evidence only;
installed native audio duplex remains a mandatory N11 gate.

N09 keeps 3.11 as the deliberate native bundle/installed-consumer lane while
making the installer source assertions follow the interpreter that generated
the bundle. The Linux 3.11 lane now installs Mesa's EGL loader/vendor/DRI
runtime explicitly and proves `libEGL.so.1` is loadable before starting Kivy.
Both renderer invocations and the 20 MiB pressure fixture retain their stdout
and stderr; an always-running pinned artifact step collects both PNGs, all
three logs, and the pressure JSON even when a later fixture fails.

The new workflow contract failed before that provisioning/evidence path was
added and passed afterward. All 40 release/quality contract tests passed, as
did Ruff and strict mypy over the complete configured source sets. Both native
SDL views then ran locally with CPython 3.11.15, Kivy 2.3.1, Mesa llvmpipe and
the offscreen SDL2 provider; their 360 × 640 / 150% PNGs were inspected. The
missing optional `libmtdev` and unavailable sandbox clipboard helpers remained
diagnostics and did not prevent renderer completion. This host has neither
native Windows nor Python 3.13, and this assignment forbids pushing solely to
start CI, so a fresh hosted Linux/Windows × 3.11/3.13 run remains a precise N11
acceptance gate rather than a claimed pass.

N10 makes GUI installation a first-class release smoke on both operating
systems: the workflow installs the GUI ZIP, checks its environment, resolves
the public `gui` frontend entry point, and invokes the canonical
`metor chat --ui gui --help` path. Fresh Linux CPython 3.11 bundles for SDK,
Base, Terminal, and GUI passed both native offline installer validation and the
complete isolated installed-consumer sequence. That sequence now identifies
its intentionally in-process daemon as a static remote endpoint; it therefore
tests the public host/SDK/frontend boundary without weakening N02's canonical
managed-process ownership rule.

The generated Windows installer no longer reads `%ERRORLEVEL%` inside a
parenthesized block. Its `py` and `python` probes execute in subroutines and use
execution-time `if errorlevel` checks, so an unsuitable launcher falls through
to a suitable `python` candidate while incomplete or incompatible existing
environments remain untouched. Native `cmd.exe` branch tests cover launcher
match/fallback/absence, no matching interpreter, existing compatible and
incompatible environments, and paths containing spaces and `!`. This WSL host
exposes only Inkscape's embedded Windows Python, which cannot create or execute
a standard child venv; those native cases remain a hosted Windows N11 gate and
are not reported as local passes.

Release publication now validates short ref names and performs one required
`git push --atomic` for the branch and annotated tag. A disposable bare remote
with a branch-rejecting pre-receive hook proved that the rejected transaction
advances neither the branch nor the tag. No real remote, release, branch, or
tag was mutated.

N11 aligns the active README, architecture, frontend/GUI contracts, platform
decision, support manifest, release guide, operator examples, agent routing,
and affected file headers with the single public `metor` CLI and current
acceptance state. Active examples now use `metor daemon --locked` and the exact
`chat --list-uis` option. Other historical audits and the approved
specifications remain unmodified evidence. The obsolete A20–A25 row below now
reflects the verified sections that already followed it instead of presenting
them as open.

The first complete N11 gate found one stale integration harness: it started an
in-process daemon but expected N02's managed-process detector to accept the
unittest interpreter as a canonical daemon child. The harness now identifies
that actual daemon as an explicitly configured endpoint and continues through
the public host, SDK, IPC, and real snapshot path. It does not weaken production
ownership. The focused test and its 24 daemon/start neighbors passed, followed
by a clean complete discovery of 842 tests in 670.608 seconds. Four native
Windows batch cases were skipped only because this host has no standard native
Windows Python environment.

The final local environment is WSL2 Linux x86-64 with system CPython 3.11.4 for
the complete repository gates and repository CPython 3.11.15, Kivy 2.3.1,
SDL2, and Mesa llvmpipe for native rendering. Ruff checked the complete source,
all 562 configured Python files were format-clean, strict mypy checked 465
sources, distribution boundaries passed, and generated references were fresh
and reproducible. Fresh Linux CPython 3.11 SDK, Base, Terminal, and GUI ZIPs
passed exact target/hash verification, RECORD ownership, offline installation,
SDK-only/Base-only/UI isolation and coexistence, positive/negative external
typing, both UI removal orders, and final SDK reimport. Their local temporary
paths and SHA-256 values are:

- `metor-sdk-wheelhouse-linux-x86_64-py311.zip`:
  `af24a3b11ab1c39ed0ef4069c29b03fa52bb6800184c7d7277ff939932e2536f`
- `metor-wheelhouse-linux-x86_64-py311.zip`:
  `15cfb603cb43d4a358478bec859d6e520ce07742d87e89436de87bf614462f32`
- `metor-ui-terminal-wheelhouse-linux-x86_64-py311.zip`:
  `1887caa88f0eddcb26f51820a81a70abd012c20c3ab6e744449670078e3b376f`
- `metor-ui-gui-wheelhouse-linux-x86_64-py311.zip`:
  `c8fb04423a8381a40cebda6da6953f2576ab25b9958178f3390c32cd40e95886`

Both production Kivy/SDL2 views ran at 360 × 640 / 150% and were visually
inspected from `/tmp/metor-n11-root-refresh.png` and
`/tmp/metor-n11-setting-keyboard.png`. The 20 MiB production-worker fixture at
`/tmp/metor-n11-stream-pressure.json` emitted 20,971,520 exact bytes with
64 KiB maximum reads, 640-byte maximum frames, the 16 MiB cache ceiling, and a
39-record sampled queue peak. Optional mtdev and sandbox clipboard diagnostics
did not prevent either renderer result. These are Linux offscreen and
controlled-port evidence, not physical audio, live desktop lifecycle, or
Windows evidence.

No current hosted CI run or release dry run exists because this local task did
not authorize a remote push or workflow dispatch. Consequently there are no
new CI run/job IDs to report, and the Linux/Windows × Python 3.11/3.13 matrix,
native Windows batch/release lanes, and release dry run remain blocked rather
than inferred from local tests. After an authorized push of the exact final
commit, the executable continuation is:

1. Let `.github/workflows/ci.yml` run its four declared lanes and retain the
   Linux 3.11 `gui-native-evidence-linux-py311` artifact plus all run/job IDs.
2. Dispatch `.github/workflows/release.yml` at that same ref with
   `release_type=current` and `dry_run=true`; verify both operating-system jobs
   and all four distributions without publication.
3. On an authorized installed Windows 3.11 system, run the native batch branch
   tests, exercise WTS Lock/Unlock and power transitions while capture/playback
   are active, and run the `tests/gui_native_voice.py` probe with
   `--headset-confirmed` and an explicit `--result` path on the documented Razer
   BlackShark V2 HS 2.4 route.
4. In an authorized real Linux desktop session, run the installed
   `tests/gui_native_lifecycle.py --expect lock,suspend,resume` while observing
   capture, playback, privacy cover, and no implicit resume. Do not suspend an
   unattended or unrelated user system.

This host cannot execute those Windows/session/hardware gates and has no Penpot
connector for a fresh reference inspection. Therefore the accurate final
status is **software corrections implemented; native overall acceptance
pending**. No physical GPIO/appliance adapter, certification, publication,
tag, push, completion percentage, or error-free claim is implied.

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

| Package | State    | Changed files                                                                                                                                                                                                                                                                       | Verification         | Next step                            |
| ------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------ |
| A00     | verified | `docs/audits/FINAL_CLOSURE_WORKLOG.md`                                                                                                                                                                                                                                              | Baseline gates below | Complete                             |
| A01     | verified | `src/metor/data/sql/manager.py`, `tests/test_gui_purge.py`, this worklog                                                                                                                                                                                                            | A01 gates below      | Complete                             |
| A02     | verified | `src/metor/core/tor.py`, `tests/test_tor_path_resolution.py`, `tests/test_closure_integration.py`, this worklog                                                                                                                                                                     | A02 gates below      | Complete                             |
| A03     | verified | `src/metor/utils/{constants,security}.py`, `tests/test_security_contract.py`, this worklog                                                                                                                                                                                          | A03 gates below      | Complete                             |
| A04     | verified | `src/metor/shared/security.py`, `tests/test_security_contract.py`, this worklog                                                                                                                                                                                                     | A04 gates below      | Complete                             |
| A05     | verified | `src/metor/utils/lock.py`, `tests/test_lock_contract.py`, this worklog                                                                                                                                                                                                              | A05 gates below      | Complete                             |
| A06     | verified | `src/metor/data/profile/{support,paths,manager,catalog,lifecycle}.py`, `src/metor/data/profile/migration/{journal,orchestrator}.py`, `tests/test_profile_path_security.py`, this worklog                                                                                            | A06 gates below      | Complete                             |
| A07     | verified | `src/metor/{utils/process.py,data/profile/manager.py,application/runtime/maintenance.py,application/frontend/host.py,core/tor.py}`, `tests/test_application_runtime_contract.py`, this worklog                                                                                      | A07 gates below      | Complete                             |
| A08     | verified | `src/metor/core/api/{base.py,events/shared.py,events/entries.py}`, `tests/test_ipc_type_validation.py`, this worklog                                                                                                                                                                | A08 gates below      | Complete                             |
| A09     | verified | `scripts/{generate_api_docs.py,release/compatibility.py}`, `docs/generated/{API.md,api.schema.json,compatibility.json}`, `tests/test_api_generation_contract.py`, this worklog                                                                                                      | A09 gates below      | Complete                             |
| A10     | verified | `src/metor/cli/{parser,entry}.py`, `tests/test_refactor2_cli_contract.py`, this worklog                                                                                                                                                                                             | A10 gates below      | Complete                             |
| A10b    | verified | Terminal renderer/presenter hardening and regression coverage; this worklog                                                                                                                                                                                                         | A10b gates below     | Complete                             |
| A11     | verified | Canonical daemon bootstrap/runtime preparation and regression coverage; this worklog                                                                                                                                                                                                | A11 gates below      | Complete                             |
| A12     | verified | Producer recovery correlation ordering and regression coverage; this worklog                                                                                                                                                                                                        | A12 gates below      | Complete                             |
| A13     | verified | `src/metor/ui/gui/platform/{configuration,configuration_security}.py`, `tests/test_device_configuration_security.py`, this worklog                                                                                                                                                  | A13 gates below      | Complete                             |
| A14     | verified | `src/metor/ui/gui/{app.py,platform/lifecycle.py,runtime/controller.py}`, `packaging/gui/setup.py`, `requirements/gui.lock`, `tests/{test_gui_os_lifecycle.py,gui_native_lifecycle.py,test_gui_lifecycle.py}`, `docs/contracts/{GUI_PLATFORM_ADR.md,gui/support.json}`, this worklog | A14 gates below      | Complete                             |
| A15     | verified | `tests/{test_gui_capture.py,test_gui_audio.py,gui_native_voice.py}`, `docs/contracts/{GUI_PLATFORM_ADR.md,gui/support.json}`, this worklog                                                                                                                                          | A15 gates below      | Complete                             |
| A16     | verified | `src/metor/core/daemon/managed/{notify/notification.py,notify/sinks.py,ipc.py,engine/daemon.py}`, `tests/{test_notification_delivery.py,test_gui_capture.py}`, this worklog                                                                                                         | A16 gates below      | Complete                             |
| A17     | verified | Removed `src/metor/ui/embedded/**` and `tests/test_embedded_contract.py`; `tests/{test_ui_boundaries.py,test_contact_qr.py}`, this worklog                                                                                                                                          | A17 gates below      | Complete                             |
| A18     | verified | `scripts/{build_release_wheelhouse.py,release/bundle.py}`, Base/shared/Core owner imports, `src/metor/utils/{__init__,constants}.py`, `tests/{test_release_contract.py,test_closure_architecture.py}`, `docs/ARCHITECTURE.md`, this worklog                                         | A18 gates below      | Complete                             |
| A19     | verified | `src/metor/core/daemon/managed/network/voice/{manager,inbound,retained,capture,outbound}.py`, `tests/{test_voice_contract.py,test_gui_producers.py}`, `docs/ARCHITECTURE.md`, this worklog                                                                                          | A19 gates below      | Complete                             |
| A20–A25 | verified | Production-tree audit, canonical docs, CI/release closure, bundle integrity, final evidence; this worklog                                                                                                                                                                           | A20–A25 gates below  | Complete at their recorded revisions |

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

| Command                                                                                                                                                                                                                                                                                             | Result                                                                                    |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| A03 reproduction supplied by the closure assignment                                                                                                                                                                                                                                                 | CONFIRMED FINDING: whole-file allocation, partial-write unlink, and direct-link overwrite |
| `python -m unittest -v test_security_contract test_profile_storage_security test_tor_path_resolution test_gui_purge test_gui_purge_observation`                                                                                                                                                     | PASS; 70 tests in 43.923 seconds with local IPC socket access                             |
| `python -m ruff check src/metor/utils/security.py src/metor/utils/constants.py tests/test_security_contract.py`                                                                                                                                                                                     | PASS                                                                                      |
| `python -m ruff format --check src/metor/utils/security.py src/metor/utils/constants.py tests/test_security_contract.py`                                                                                                                                                                            | PASS; 3 files already formatted                                                           |
| `python -m mypy src/metor/utils/security.py src/metor/core/profile_keys.py src/metor/core/tor.py src/metor/core/profile_destruction.py src/metor/core/daemon/managed/engine/lifecycle.py src/metor/data/profile/lifecycle.py src/metor/data/profile/migration src/metor/data/sql/runtime_mirror.py` | PASS; 11 source files                                                                     |
| `python scripts/check_boundaries.py`                                                                                                                                                                                                                                                                | PASS                                                                                      |
| `git diff --check`                                                                                                                                                                                                                                                                                  | PASS                                                                                      |

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

| Command                                                                                                                                                                                                                       | Result                                                                                                |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Three focused `secure_clear_buffer` regressions before implementation                                                                                                                                                         | EXPECTED FAIL; typed view raised `ValueError` and strided view had no explicit `BufferError` contract |
| `python -m unittest -v test_security_contract test_session_auth_contract test_profile_storage_security test_data_persistence_contract test_closure_architecture`                                                              | PASS; 87 tests in 34.664 seconds with local IPC socket access                                         |
| `python -m ruff check src/metor/shared/security.py tests/test_security_contract.py`                                                                                                                                           | PASS                                                                                                  |
| `python -m ruff format --check src/metor/shared/security.py tests/test_security_contract.py`                                                                                                                                  | PASS; 2 files already formatted                                                                       |
| `python -m mypy src/metor/shared/security.py src/metor/core/key.py src/metor/core/auth src/metor/core/daemon/managed/local_auth.py src/metor/data/blob/store.py src/metor/data/sql/manager.py src/metor/core/profile_keys.py` | PASS; 9 source files                                                                                  |
| `python scripts/check_boundaries.py`                                                                                                                                                                                          | PASS                                                                                                  |
| `git diff --check`                                                                                                                                                                                                            | PASS                                                                                                  |

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

| Command                                                                                                                        | Result                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `python -m unittest -v test_lock_contract` before implementation                                                               | EXPECTED FAIL; 6 failures covered rollback leaks, partial writes, close hiding, wall-clock deadline, and unknown identity |
| `python -m unittest -v test_lock_contract test_settings_contract test_profile_storage_security test_data_persistence_contract` | PASS; 92 tests in 11.162 seconds with local IPC socket access                                                             |
| `python -m ruff check src/metor/utils/lock.py tests/test_lock_contract.py`                                                     | PASS                                                                                                                      |
| `python -m ruff format --check src/metor/utils/lock.py tests/test_lock_contract.py`                                            | PASS; 2 files already formatted                                                                                           |
| `python -m mypy src/metor/utils/lock.py src/metor/data/settings.py src/metor/data/profile/config/config.py`                    | PASS; 3 source files                                                                                                      |
| `python scripts/check_boundaries.py`                                                                                           | PASS                                                                                                                      |
| `git diff --check`                                                                                                             | PASS                                                                                                                      |

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

| Command                                                                                                                                                     | Result                                                                             |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `python -m unittest -v test_profile_path_security` before implementation                                                                                    | EXPECTED FAIL; strict public validators and explicit staging factory did not exist |
| `python -m unittest -v test_profile_path_security test_profile_storage_security test_gui_profiles test_application_runtime_contract test_settings_contract` | PASS; 87 tests in 11.581 seconds with local IPC socket access                      |
| `python -m unittest test_gui_purge test_profile_storage_security.ProfileStorageSecurityTests.test_profile_destruction_is_idempotent_when_files_are_missing` | PASS; 7 tests in 24.971 seconds with local IPC socket access                       |
| `python -m ruff check src/metor/data/profile tests/test_profile_path_security.py`                                                                           | PASS                                                                               |
| `python -m ruff format --check src/metor/data/profile tests/test_profile_path_security.py`                                                                  | PASS; 15 files already formatted                                                   |
| `python -m mypy src/metor/data/profile`                                                                                                                     | PASS; 14 source files                                                              |
| `python scripts/check_boundaries.py`                                                                                                                        | PASS                                                                               |
| `git diff --check`                                                                                                                                          | PASS                                                                               |

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

| Command                                                                                                                                                                                                                                           | Result                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Three focused ownership regressions before implementation                                                                                                                                                                                         | EXPECTED FAIL; 11 errors exposed missing profile arguments, lifetime metadata, and OS-owner validation |
| `python -m unittest test_application_runtime_contract test_tor_path_resolution test_daemon_lock_lifecycle test_gui_profiles`                                                                                                                      | PASS; 36 tests in 0.738 seconds with local IPC socket access                                           |
| `python -m unittest -v test_application_runtime_contract test_tor_path_resolution test_platform_contracts` plus three focused daemon-entrypoint release tests                                                                                     | PASS; 29 tests in 0.166 seconds                                                                        |
| `python -m ruff check src/metor/utils/process.py src/metor/data/profile/manager.py src/metor/application/runtime/maintenance.py src/metor/application/frontend/host.py src/metor/core/tor.py tests/test_application_runtime_contract.py`          | PASS                                                                                                   |
| `python -m ruff format --check src/metor/utils/process.py src/metor/data/profile/manager.py src/metor/application/runtime/maintenance.py src/metor/application/frontend/host.py src/metor/core/tor.py tests/test_application_runtime_contract.py` | PASS; 6 files already formatted                                                                        |
| `python -m mypy src/metor/utils/process.py src/metor/data/profile/manager.py src/metor/application/runtime/maintenance.py src/metor/application/frontend/host.py src/metor/core/tor.py`                                                           | PASS; 5 source files                                                                                   |
| `python scripts/check_boundaries.py`                                                                                                                                                                                                              | PASS                                                                                                   |
| `git diff --check`                                                                                                                                                                                                                                | PASS                                                                                                   |

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

| Command                                                                                                                                                                                                       | Result                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `python -m unittest -v test_ipc_type_validation` before implementation                                                                                                                                        | EXPECTED FAIL; accepted Boolean integers, bad later list/dictionary values and arbitrary open-map objects, while valid structured content and explicit Voice null failed |
| `python -m unittest -v test_ipc_type_validation`                                                                                                                                                              | PASS; 7 tests, including valid JSON roundtrips for all 66 command and 160 event registrations                                                                            |
| `python -m unittest -v test_raw_client_contract`                                                                                                                                                              | PASS; 3 tests in 4.316 seconds with local IPC socket access                                                                                                              |
| `python -m unittest -v test_gui_handoff test_gui_metadata test_ui_boundaries test_session_auth_contract test_history_contract test_gui_pages test_gui_producers test_embedded_contract test_closure_security` | PASS; 70 tests in 142.071 seconds with local IPC socket access                                                                                                           |
| `python -m unittest -v test_ipc_type_validation test_ui_boundaries test_history_contract test_message_architecture_contract test_ui_ipc_contract`                                                             | PASS; 62 tests                                                                                                                                                           |
| Three focused `test_daemon_hardening.DaemonHardeningTests` IPC writer/rejection/dispatch tests                                                                                                                | PASS; 3 tests in 0.008 seconds with local socket-pair access                                                                                                             |
| `python -m ruff check src/metor/core/api/base.py src/metor/core/api/events/shared.py src/metor/core/api/events/entries.py tests/test_ipc_type_validation.py`                                                  | PASS                                                                                                                                                                     |
| `python -m ruff format --check src/metor/core/api/base.py src/metor/core/api/events/shared.py src/metor/core/api/events/entries.py tests/test_ipc_type_validation.py`                                         | PASS; 4 files already formatted                                                                                                                                          |
| `python -m mypy src/metor/core/api/base.py src/metor/core/api/events/shared.py src/metor/core/api/events/entries.py`                                                                                          | PASS; 3 source files                                                                                                                                                     |
| `python scripts/check_boundaries.py`                                                                                                                                                                          | PASS                                                                                                                                                                     |
| `git diff --check`                                                                                                                                                                                            | PASS                                                                                                                                                                     |

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

| Command                                                                                                                                  | Result                                                                                                                                                                                             |
| ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python -m unittest -v test_api_generation_contract` before implementation                                                               | EXPECTED FAIL; invalid content examples, untyped dictionary values, permissive open mappings, missing catalog semantics, and silent unknown annotations were reproduced                            |
| `python -m unittest -v test_api_generation_contract`                                                                                     | PASS; 6 tests covering all 226 examples, complete route definitions, negative containers/discriminators, open JSON, fail-closed annotations, compatibility classification, and repeated generation |
| `python scripts/generate_api_docs.py` and `python scripts/generate_compatibility_manifest.py`                                            | PASS; canonical API, schema, and compatibility artifacts regenerated from source                                                                                                                   |
| `python scripts/validate_generated_docs.py`                                                                                              | PASS; all four generated artifacts remained byte-identical across two generations                                                                                                                  |
| Direct `ipc_breaking_changes()` comparison with the A08 checked-in schema                                                                | REVIEWED; only `history_data.entries` and `history_raw_data.entries` schema corrections classified as narrowed                                                                                     |
| `python scripts/check_release_compatibility.py --current docs/generated/compatibility.json`                                              | PASS; first public baseline, no automatic bump                                                                                                                                                     |
| `python scripts/versioning.py validate`                                                                                                  | PASS; application 0.2.0 and IPC generation 2 remain valid                                                                                                                                          |
| `python -m unittest -v test_api_generation_contract test_ipc_type_validation test_message_architecture_contract test_versioning_release` | PASS; 51 tests in 3.294 seconds                                                                                                                                                                    |
| `python -m ruff check scripts/generate_api_docs.py scripts/release/compatibility.py tests/test_api_generation_contract.py`               | PASS                                                                                                                                                                                               |
| `python -m ruff format --check scripts/generate_api_docs.py scripts/release/compatibility.py tests/test_api_generation_contract.py`      | PASS; 3 files already formatted                                                                                                                                                                    |
| `python -m mypy scripts/generate_api_docs.py scripts/release/compatibility.py`                                                           | PASS; 2 source files                                                                                                                                                                               |
| `python scripts/check_boundaries.py`                                                                                                     | PASS                                                                                                                                                                                               |
| `git diff --check`                                                                                                                       | PASS                                                                                                                                                                                               |

## A10 verification

The outer parser now recognizes only global options and preserves every other
token in order. The first remaining token establishes the actual command
boundary; ordinary commands receive their subcommand and free-form remainder,
while `chat` reparses exactly the tokens after that boundary. This removes the
optional-positional/unknown-option interaction that lost values across Python
argparse versions. Both separated and equals forms work for frontend and device
options, global profile selection remains valid before or after `chat`, and
`--ui`-looking tokens in `send` text remain literal message data.

Unknown `chat` operands survive parsing and are rejected before environment,
profile, frontend, device, or daemon initialization. The CLI emits an explicit
`Unexpected chat arguments.` diagnostic, displays launcher usage, and exits 2.
Help, version, and UI inventory retain their pre-profile fast paths.

The current Python 3.11.4 interpreter was exercised in fresh subprocesses.
Python 3.13 is not installed in this environment, so its native matrix remains
an explicit environment gap rather than a claimed pass. The parser no longer
depends on the positional `parse_known_args()` behavior that differed there.
No CLI spelling, launcher contract, wire/storage format, compatibility axis, or
application version changed.

| Command                                                                                                                         | Result                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Four focused parser/entry regressions before implementation                                                                     | EXPECTED FAIL; `chat unexpected` was dropped and proceeded into frontend launch, including in a fresh process |
| Focused pre-initialization invalid-argument regression before entry fix                                                         | EXPECTED FAIL; profile construction occurred before invalid chat operands were reported                       |
| `python -m unittest -v test_refactor2_cli_contract test_gui_contract test_ui_ipc_contract`                                      | PASS; 59 tests in 4.725 seconds                                                                               |
| Fresh `python -m metor` subprocess matrix for `--help`, `help`, both chat-help forms, both version forms, and `chat --list-uis` | PASS; 7 processes, all exit 0 without profile/daemon/toolkit requirements                                     |
| `python -m ruff check src/metor/cli/parser.py src/metor/cli/entry.py tests/test_refactor2_cli_contract.py`                      | PASS                                                                                                          |
| `python -m ruff format --check src/metor/cli/parser.py src/metor/cli/entry.py tests/test_refactor2_cli_contract.py`             | PASS; 3 files already formatted                                                                               |
| `python -m mypy src/metor/cli/parser.py src/metor/cli/entry.py`                                                                 | PASS; 2 source files                                                                                          |
| `python scripts/check_boundaries.py`                                                                                            | PASS                                                                                                          |
| `git diff --check`                                                                                                              | PASS                                                                                                          |

## A10b verification

Terminal-facing untrusted text now passes through the narrowly scoped
`shared.terminal.escape_terminal_text()` encoder. It preserves Unicode and
intentional newlines while rendering every other C0 control, DEL, and C1
control as visible `\\xNN` data. Message content and voice-codec labels are
encoded only during CLI/terminal projection; the typed content object, JSON
wire representation, and persisted source value remain unchanged.

SELF and REMOTE chat lines no longer interpret `{alias}`. Only STATUS lines
whose trusted translation selected a non-`NONE` alias policy perform dynamic
alias substitution. The alias is encoded before substitution. The same
rendered-text path now drives formatting and wrap accounting, and visible
prefix length includes the expanded control notation, so redraw calculations
match the emitted line. Renderer-owned ANSI colors and cursor commands remain
unchanged.

Translation parameters are recursively encoded before insertion into trusted
templates. Presenter boundaries also encode peer aliases, onion/profile names,
setting metadata, history details, transport metadata, daemon/Tor/SQL log
lines, local runtime errors, focused prompts, startup summaries, and direct
read-receipt aliases before adding program-owned colors. String-backed enums
retain their enum identity so existing error-code interpretation is unchanged.

This is presentation hardening only: no route, DTO, CLI spelling, stored
format, compatibility axis, or application version changed. The shared helper
is host-free and has one terminal-encoding responsibility; it does not create a
general UI layer.

| Command                                                                                                                                                                                                                                                                         | Result                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python -m unittest tests.test_terminal_rendering_security -v` before completing the renderer                                                                                                                                                                                   | EXPECTED FAIL; 4 of 6 initial regressions reproduced control injection, ordinary-message placeholder substitution, unsafe translation parameters, and inconsistent wrapping |
| `python -m unittest tests.test_terminal_rendering_security tests.test_chat_contract tests.test_ui_boundaries tests.test_history_contract tests.test_settings_contract tests.test_refactor2_cli_contract tests.test_message_architecture_contract tests.test_ui_ipc_contract -q` | PASS; 138 tests in 0.427 seconds; expected non-TTY diagnostic and plaintext-test notice were emitted by existing tests                                                      |
| `ruff check src/metor tests/test_terminal_rendering_security.py`                                                                                                                                                                                                                | PASS                                                                                                                                                                        |
| `ruff format --check` for all A10b-touched source and test files                                                                                                                                                                                                                | PASS after canonical formatting                                                                                                                                             |
| `mypy` for all 28 A10b-touched source paths and the regression test                                                                                                                                                                                                             | PASS; strict project configuration, no issues                                                                                                                               |
| `python scripts/check_boundaries.py`                                                                                                                                                                                                                                            | PASS; distribution and frontend boundaries                                                                                                                                  |
| `git diff --check`                                                                                                                                                                                                                                                              | PASS                                                                                                                                                                        |

## A11 verification

Daemon startup now has one Application-runtime preparation contract. It checks
profile existence, global/profile integrity, remote/local ownership, an already
running daemon, locked/plaintext incompatibility, storage mode, and plaintext
session-auth requirements. The interactive CLI and the noninteractive child
adapter consume the same immutable preparation result, so credential prompting
remains a CLI concern while the runtime owns startup eligibility.

Autostart now executes the installed public `metor` entry with an internal
`--daemon-child` marker instead of `python -m metor.daemon_main`. The public
main module is import-light and routes only the child marker before importing
the CLI package; the child import graph contains neither `metor.cli` nor
`metor.ui`. The retired `metor-daemon` console script was removed from package
metadata, active architecture/release/user documentation, installed-artifact
validation, and accepted process-identification forms. `daemon_main.py` remains
an internal implementation module used behind the canonical public entry, not
an independently documented executable.

Argument parsing no longer reads the default profile. For actual child work,
the environment is initialized first and then the default is resolved only
when `-p` was absent; an explicit profile never reads the default. Help exits
without profile, environment, terminal frontend, GUI toolkit, or daemon work.
The `.env` data-parent projection was exercised before profile resolution.

The duplicated stdin readers were replaced by one bounded UTF-8-aware reader.
Empty EOF aborts, overlong or multiline secrets fail explicitly, and secrets
remain on the existing stdin pipe rather than argv or logs. Autostart resolves
the public executable beside the active interpreter (falling back to an exact
PATH lookup), verifies complete writes, and closes the pipe. Missing pipes,
write/flush/close failures, readiness timeout, and interrupted handshakes now
perform bounded terminate/wait/kill cleanup of the process they spawned.

This changes the pre-public launcher surface but no wire, peer, database,
keyslot, blob, or derivation format. Metor still has no prior public release,
so no compatibility generation or application-version bump is required.
Linux subprocess behavior was executed; the Windows detached flags and `.exe`
resolution are structurally covered by the existing platform matrix but no
native Windows run is claimed here.

| Command                                                                                                                                                                                                                                                 | Result                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python -m unittest tests.test_daemon_bootstrap_contract -v` before implementation                                                                                                                                                                      | EXPECTED FAIL; 4 failures and 2 errors reproduced eager default/CLI loading, module-based launch, missing bounded reader, and leaked failed children |
| `python -m unittest tests.test_daemon_bootstrap_contract tests.test_application_runtime_contract tests.test_ui_ipc_contract tests.test_release_contract tests.test_refactor2_cli_contract tests.test_closure_frontend tests.test_platform_contracts -q` | PASS; 105 tests in 2.939 seconds; expected cleanup diagnostics, plaintext notice, and temporary bundle paths were emitted                            |
| Fresh subprocess imports of `metor.main` and `metor.daemon_main`, plus `python -m metor --daemon-child --help`                                                                                                                                          | PASS; no CLI/UI eager import in the child graph and help exited 0 without profile access                                                             |
| Fresh `python -m metor --help`, `python -m metor daemon --help`, and installed `metor daemon --help`                                                                                                                                                    | PASS; canonical help paths exit without daemon/profile work                                                                                          |
| `ruff check` for all A11 source, script, and test files                                                                                                                                                                                                 | PASS                                                                                                                                                 |
| `ruff format --check` for all A11 source, script, and test files                                                                                                                                                                                        | PASS after canonical formatting                                                                                                                      |
| `mypy` for the 10 A11 runtime/entry/script/test paths                                                                                                                                                                                                   | PASS under strict project configuration                                                                                                              |
| `python scripts/check_boundaries.py`                                                                                                                                                                                                                    | PASS; distribution and frontend boundaries                                                                                                           |
| `python scripts/versioning.py validate`                                                                                                                                                                                                                 | PASS; application 0.2.0 and compatibility registry remain valid                                                                                      |
| Active-source search for `metor-daemon` outside immutable historical/spec evidence                                                                                                                                                                      | PASS; only an explicit negative process-detector regression remains                                                                                  |
| `git diff --check`                                                                                                                                                                                                                                      | PASS                                                                                                                                                 |

## A12 verification

Explicit interrupted-LIVE recovery now temporarily clears the originating IPC
request context while `ProducerCleanup.reclaim()` performs accepted-prefix
finalization and publishes its domain event. Both the requesting SDK client and
other authenticated observers can still receive that `VoiceFinalizedEvent`
asynchronously, but it has no request ID and therefore cannot terminate the
in-flight recovery exchange.

After finalization, retained-object reconciliation, allocation-debris cleanup,
and producer repository release all succeed, the outer request context is
restored and the service sends exactly one correlated terminal projection to
the requester. The SDK waiter therefore cannot complete while the producer
claim still exists. A false return or exception from `reclaim()` now produces a
correlated `PERSISTENCE_FAILED` rejection and retains the producer for retry;
even a hypothetical success projection cannot override that result. Repeating
finalization remains idempotent and preserves the same accepted 640-byte audio
prefix.

The deterministic regression blocks `VoiceProducerRepository.release()`
itself, uses the real daemon, SQLCipher/blob stores, two authenticated public
SDK clients, request demultiplexing, and observer callbacks, and contains no
sleep-based ordering assertion. Existing journal assertions and owner binding
remain intact. This changes neither IPC DTO shape nor protocol semantics; it
corrects when correlation is attached, so no compatibility or application
version bump is required.

| Command                                                                                                                                                                                      | Result                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Two focused real-IPC recovery regressions before implementation                                                                                                                              | EXPECTED FAIL; the release-barrier test timed out waiting for the requester to receive an uncorrelated observation because the premature correlated inner event had already satisfied its waiter |
| `python -m unittest` for the release-barrier, reclaim-false, and original accepted-prefix tests                                                                                              | PASS; 3 tests in 18.425 seconds with local IPC sockets                                                                                                                                           |
| `python -m unittest tests.test_gui_producers -q` outside the socket sandbox                                                                                                                  | PASS; 12 real daemon/SQLCipher/blob/SDK producer tests                                                                                                                                           |
| `python -m unittest tests.test_client_demux_contract tests.test_gui_producers tests.test_gui_resend tests.test_gui_capture tests.test_gui_live` outside the socket sandbox                   | PASS; 21 SDK demux, producer, resend, capture, and LIVE tests                                                                                                                                    |
| `mypy src/metor/core/daemon/managed/producers/service.py src/metor/core/daemon/managed/producers/cleanup.py src/metor/core/daemon/managed/network/voice/outbound.py src/metor/client/ipc.py` | PASS; 4 source files under strict project configuration                                                                                                                                          |
| `ruff check src/metor/core/daemon/managed/producers/service.py tests/test_gui_producers.py`                                                                                                  | PASS                                                                                                                                                                                             |
| `ruff format --check src/metor/core/daemon/managed/producers/service.py tests/test_gui_producers.py`                                                                                         | PASS; 2 files already formatted                                                                                                                                                                  |
| `python scripts/check_boundaries.py`                                                                                                                                                         | PASS; distribution and frontend boundaries                                                                                                                                                       |
| `git diff --check`                                                                                                                                                                           | PASS                                                                                                                                                                                             |

## A13 verification

Device configuration bytes are now read through one already-open object. On
POSIX, `O_NOFOLLOW` prevents following the final symbolic link and `fstat()` on
that descriptor verifies a regular, single-link file owned by the current user
without group or world write access. Size is checked both from descriptor
metadata and after a bounded read. A pathname replacement after open therefore
cannot redirect the parser to different bytes.

Windows uses `CreateFileW` with read-only sharing and
`FILE_FLAG_OPEN_REPARSE_POINT`, rejects reparse objects using handle metadata,
and obtains owner and DACL information from that same handle. The owner must be
the current user and writable allow entries may name only that user or Local
System; null DACLs and unknown ACE forms fail closed. The native handle is
converted to a Python descriptor only after these checks, after which the same
regular-file, single-link, size, and bounded-read path applies. Any inability
to establish Windows trust produces a safe explicit error rather than a POSIX
mode-bit bypass.

The strict TOML tables, scalar types, limits, simulator adapter registration,
and physical-binding checks remain unchanged. The checked-in JSON schema and
example already label and implement only the currently registered simulator
subset, so they were reviewed without broadening their hardware claims. This
is local file-validation hardening and changes no wire, storage, launcher,
compatibility, or application version.

Native Windows is unavailable in this WSL environment. The Windows dispatch
and fail-closed contract are covered structurally, while a native Windows ACL
and reparse execution remains an explicit environment gap rather than a
claimed pass.

| Command                                                                                                                                                                      | Result                                                                                                                   |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `python -m unittest tests.test_device_configuration_security -v` before implementation                                                                                       | EXPECTED FAIL; group-writable, symbolic/hard-link, path-stat race, and Windows secure-opener regressions were reproduced |
| `python -m unittest tests.test_device_configuration_security -v`                                                                                                             | PASS; 7 permission, read-only, link/swap, type/size, simulator, and Windows dispatch/fail-closed tests                   |
| `python -m unittest tests.test_device_configuration_security tests.test_gui_contract tests.test_gui_device_lifecycle tests.test_gui_bootstrap -q` outside the socket sandbox | PASS; 36 device, lifecycle, bootstrap, and transport tests                                                               |
| `python -m ruff check src/metor/ui/gui/platform/configuration.py src/metor/ui/gui/platform/configuration_security.py tests/test_device_configuration_security.py`            | PASS                                                                                                                     |
| `python -m ruff format --check src/metor/ui/gui/platform/configuration.py src/metor/ui/gui/platform/configuration_security.py tests/test_device_configuration_security.py`   | PASS after canonical formatting                                                                                          |
| `python -m mypy src/metor/ui/gui/platform/configuration.py src/metor/ui/gui/platform/configuration_security.py`                                                              | PASS; 2 source files under strict project configuration                                                                  |
| `python scripts/check_boundaries.py`                                                                                                                                         | PASS; distribution and frontend boundaries                                                                               |
| `git diff --check`                                                                                                                                                           | PASS                                                                                                                     |

## A14 verification

Windows desktop lock/unlock and suspend/resume now enter through an owned hidden
Win32 top-level window registered for WTS session notifications and power
broadcasts. This deliberately does not subclass Kivy's HWND and therefore does
not create a second chain competing with AccessKit's existing Windows subclass
or alter its required post-input-provider teardown order. The lifecycle window
and message pump have one bounded daemon-thread owner and a bounded close.

Native callbacks publish only `LOCK`, `SUSPEND`, or `RESUME` into a four-record
synchronized inbox. Duplicate transitions coalesce; overload drops resume
before a privacy departure. GUI-thread application first revokes AccessKit
nodes and tooltip text, then performs the existing input-loss, capture stop,
playback stop, and per-client restriction path. Resume retains the cover,
re-revokes input/media ownership, checks that the captured SDK transport remains
connected, and never reconstructs a press, starts capture, starts playback, or
unlocks. Kivy's own pause/resume callbacks use the same coordinator.

Linux separately subscribes to systemd-logind `PrepareForSleep` and Session
`Lock`/`Unlock` on the system bus, plus freedesktop, GNOME, and Cinnamon
`ActiveChanged` screen-lock signals on the session bus. At least one bus must be
subscribable; otherwise startup reports unavailable lifecycle integration. The
new pure-Python `dbus-next` dependency is Linux-qualified in both the canonical
GUI lock and wheel metadata. An isolated real session bus delivered actual
lock/unlock signal messages through the source and bounded teardown.

Native Windows execution is unavailable in the current WSL environment, so the
numeric WTS/power mapping, bounded handoff, privacy ordering, and fail-closed
registration code are structurally exercised without claiming an installed OS
broadcast pass. WSL also cannot produce a real system suspend or a complete
desktop session with native audio. Those exact Windows WTS/power, Linux logind
suspend, compositor-variant, and simultaneous native-media event runs remain
truthfully marked as environment gaps in the active support manifest; Windows
and Linux x86-64 were not removed as product targets.

This is local native lifecycle and dependency integration only. It changes no
IPC route/DTO, persisted data, launcher spelling, compatibility generation, or
application version.

| Command                                                                                                                                              | Result                                                                             |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `python -m unittest tests.test_gui_os_lifecycle -v` before implementation                                                                            | EXPECTED ERROR; the native lifecycle module did not exist                          |
| `python -m unittest tests.test_gui_os_lifecycle -v`                                                                                                  | PASS; 8 bounded inbox/factory, Win32, Linux D-Bus, privacy-order, and resume tests |
| `PYTHONPATH=tests python -m unittest test_gui_lifecycle.NativeLifecycleTests -v`                                                                     | PASS; 4 focus/suspend/resume transport and no-auto-media tests                     |
| `PYTHONPATH=tests python -m unittest test_gui_lifecycle -q` outside the socket sandbox                                                               | PASS; toolkit-independent lifecycle plus real SDK/IPC/Core coverage                |
| `dbus-run-session -- env PYTHONPATH=/tmp/metor-dbus-next:src python tests/gui_native_lifecycle.py` outside the socket sandbox                        | PASS; real isolated Linux session-bus Lock/Resume delivery and teardown            |
| `PYTHONPATH=tests python -m unittest test_gui_lifecycle test_gui_press test_gui_playback test_gui_capture -q` outside the socket sandbox             | PASS; lifecycle, lost key-up, playback, and real SDK/Core capture regressions      |
| `PYTHONPATH=tests python -m unittest test_release_contract test_platform_contracts -q`                                                               | PASS; 40 distribution and platform-boundary tests                                  |
| GUI wheel build plus METADATA inspection                                                                                                             | PASS; Linux-qualified `dbus-next==0.2.3` dependency present                        |
| `python -m ruff check` for all A14 source, packaging, and test paths                                                                                 | PASS                                                                               |
| `python -m ruff format --check` for all A14 source, packaging, and test paths                                                                        | PASS                                                                               |
| `python -m mypy src/metor/ui/gui/platform/lifecycle.py src/metor/ui/gui/app.py src/metor/ui/gui/runtime/controller.py tests/gui_native_lifecycle.py` | PASS; strict project configuration                                                 |
| `python -m json.tool docs/contracts/gui/support.json`                                                                                                | PASS; support manifest remains valid JSON                                          |
| `python scripts/check_boundaries.py`                                                                                                                 | PASS; distribution and frontend boundaries                                         |
| `git diff --check`                                                                                                                                   | PASS                                                                               |

## A15 verification

A new deterministic integration keeps a real `VoiceController` and
`CaptureWorker` recording through the public SDK into a temporary encrypted
Core while the real `PlaybackController` and `PlaybackWorker` read and play a
different finalized PCM source from that same SDK/Core activation. Only the
audio endpoints are controlled test ports. The output port blocks at its actual
frame boundary and observes the capture worker still running, so this is an
ordering proof rather than a mock of `play()` eligibility.

While both media workers are active, the production mailbox/controller drains
updates and a text draft remains editable. On completion the new recording is
still an unsent `draft`; the played outgoing source remains `pending`; playback
does not fabricate Delivered, Read, Safe, consume, or outbox-removal outcomes.
The captured owner, profile instance, epoch, peer, message ID, and activation
generation remain immutable through the overlap.

The broader matrix retains cache/queue bounds, accepted-prefix recovery,
cancel/abort, focus/suspend, device cleanup, permission denial, lost key-up, and
profile-switch barriers. The 20 MiB production-worker pressure run used 64 KiB
maximum SDK reads, 640-byte frames, a 16 MiB cache peak, and a sampled 42-record
mailbox peak without overload.

The existing explicitly authorized Razer native probe now seeds a synthetic
pending PCM source in temporary Core, plays it through the production GUI
controller during actual HeadsetAudio capture, observes capture ownership at
the real output write, then still plays the captured review. It exports no
microphone bytes. Native Windows/Kivy/audio hardware is unavailable here, so
that updated scenario is a required rerun rather than a claimed pass; the prior
native simultaneous port result remains scoped to its exact Razer route. No
speaker AEC, arbitrary-headset, Linux-headset, or appliance claim is made.

No production semantics changed in A15; this closes an evidence gap with
integration/native probes and permission regressions. No protocol, persistence,
compatibility, or application version changes are required.

| Command                                                                                                                                                                                      | Result                                                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Pre-change review of `test_gui_playback.py` and native evidence                                                                                                                              | GAP CONFIRMED; only mocked controller eligibility plus separate port/sequential native proofs existed                       |
| `PYTHONPATH=tests python -m unittest test_gui_capture.CaptureIntegrationTests.test_full_gui_capture_and_sent_playback_overlap_over_real_sdk -v` outside the socket sandbox                   | PASS; actual production controllers/workers, SDK, IPC, SQLCipher/blob Core, concurrent controlled ports and truthful states |
| `PYTHONPATH=tests python -m unittest test_gui_capture test_gui_playback test_gui_producers test_gui_press test_gui_audio test_gui_lifecycle test_gui_profiles -q` outside the socket sandbox | PASS; full A15 capture/playback/recovery/input/device/profile matrix                                                        |
| `python tests/gui_stream_pressure.py --result /tmp/metor-a15-stream-pressure.json`                                                                                                           | PASS; 20 MiB output, 16 MiB cache peak, 64 KiB read, 640-byte frame, 42-record sampled queue peak, no overload              |
| `python -m unittest tests.test_gui_audio -v`                                                                                                                                                 | PASS; 5 framing, inert-open, cleanup, microphone-permission and speaker-permission tests                                    |
| `PYTHONPATH=tests python -m mypy tests/gui_native_voice.py`                                                                                                                                  | PASS; updated concrete-route native probe is structurally typed                                                             |
| Updated installed Windows Razer GUI full-duplex probe                                                                                                                                        | NOT RUN; native Windows/Kivy/Razer route unavailable in current WSL environment                                             |
| `python -m ruff check tests/test_gui_capture.py tests/test_gui_audio.py tests/gui_native_voice.py`                                                                                           | PASS                                                                                                                        |
| `python -m ruff format --check tests/test_gui_capture.py tests/test_gui_audio.py tests/gui_native_voice.py`                                                                                  | PASS                                                                                                                        |
| `python -m json.tool docs/contracts/gui/support.json`                                                                                                                                        | PASS; claims remain explicit and machine-readable                                                                           |
| `python scripts/check_boundaries.py`                                                                                                                                                         | PASS; distribution and frontend boundaries                                                                                  |
| `git diff --check`                                                                                                                                                                           | PASS                                                                                                                        |

## A16 verification

Optional notification delivery now has one daemon-owned worker and a fixed
64-record transient queue. Callers only attempt a nonblocking enqueue. When the
queue is full, new optional work is dropped, an overload bit is coalesced, and
the worker emits one generic error without aliases, onions, URLs, payload data,
or exception text. Configuration resolution, sink construction, file/webhook
I/O, and error callbacks all run outside media and authorization callers.

Daemon stop closes the service as an independent release phase: it stops new
admission, drops queued optional work, wakes the worker, and joins only for the
configured one-second bound. Built-in webhook I/O retains its five-second
network timeout but does not read any response body; opening and closing the
HTTP response is sufficient. Sink exceptions propagate only to the service,
which reports a generic bounded diagnostic. The public sink `deliver(payload)`
shape and configured sink registry remain unchanged.

A controlled sink was held blocked while a real capture worker continued
through authenticated SDK/IPC, SQLCipher/blob staging, append, and finalization.
Queue saturation did not spawn workers or requeue records. A controlled local
HTTP endpoint declared and delayed an 8 MiB response body; webhook delivery
returned after headers without reading it.

Fresh IPC sockets rejected at the client ceiling now close in `finally`, even
when sending the typed rejection fails. The adjacent acceptor construction
failure and writer saturation/interrupt paths were reviewed and their existing
cleanup regressions passed; no general network ownership or transport policy
was changed.

This is internal optional-I/O isolation and descriptor cleanup. It changes no
notification payload schema, IPC DTO, peer behavior, persistence format,
compatibility generation, or application version.

| Command                                                                                                                                                                       | Result                                                                                                                                                    |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python -m unittest tests.test_notification_delivery -v` before implementation                                                                                                | EXPECTED FAIL/ERROR; response body was read, slow dispatch was synchronous, bounded queue/stop controls were absent, and reject-send failure leaked close |
| `python -m unittest tests.test_notification_delivery -v` outside the socket sandbox                                                                                           | PASS; 6 large/slow response, slow/failing/full/stop queue, and reject-close tests using only local controlled counterparts                                |
| `PYTHONPATH=tests python -m unittest test_gui_capture.CaptureIntegrationTests.test_blocked_optional_notification_does_not_delay_media_progress -v` outside the socket sandbox | PASS; real SDK/Core capture finalized 640 accepted bytes while the sink remained blocked                                                                  |
| `PYTHONPATH=tests python -m unittest test_gui_producers test_closure_integration test_daemon_lock_lifecycle test_release_contract -q` outside the socket sandbox              | PASS; real Voice, IPC, lifecycle release, and packaging regressions                                                                                       |
| Two focused IPC client-ceiling/writer-saturation contract tests outside the socket sandbox                                                                                    | PASS; typed reject and interruptible finite writer behavior                                                                                               |
| `python -m mypy` for the four changed daemon source files                                                                                                                     | PASS; strict project configuration                                                                                                                        |
| `python -m ruff check` for all A16 source/test files                                                                                                                          | PASS                                                                                                                                                      |
| `python -m ruff format --check` for all A16 source/test files                                                                                                                 | PASS                                                                                                                                                      |
| `python scripts/check_boundaries.py`                                                                                                                                          | PASS; distribution and frontend boundaries                                                                                                                |
| `git diff --check`                                                                                                                                                            | PASS                                                                                                                                                      |

## A17 verification

The five-file historical `metor.ui.embedded` production namespace and its
dedicated legacy contract test are removed rather than redirected. No active
source, test, registration, packaging path, or installation path imports or
names that namespace. The architecture regression now recognizes exactly the
two shipped source packages, `metor.ui.terminal` and `metor.ui.gui`, and checks
that neither imports the other.

The removed prototype's combined battery/power, audio-blob, settings, clock,
revision-gate, fixture, and privacy-logger abstractions were not copied into a
new compatibility layer. Current platform input and lifecycle requirements
remain exercised through the GUI platform ports and SDK/Core contracts. The
one still-current requirement that lost direct automated coverage was the
frontend-neutral contact QR parser used by the GUI; a focused client-contract
test now pins malformed input, unknown fields, unsupported versions, and a
normalized valid version-one identity without retaining any embedded test
double.

Historical mentions in immutable specifications and audit evidence remain.
The active frontend-neutral documentation still named `EMBEDDED_UI.md` and is
deliberately left for the A21 documentation move required by the closure
sequence. This removal changes no current IPC DTO, persistence schema,
compatibility generation, launcher, or application version.

| Command                                                                                                                                                                                                                          | Result                                                                                  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Pre-change import and reference inventory across the five embedded files, legacy test, boundary tests, active client/platform code, and GUI ADR                                                                                  | PASS; namespace was self-contained except for its dedicated test and boundary assertion |
| `PYTHONPATH=tests python -m unittest tests.test_contact_qr tests.test_ui_boundaries tests.test_platform_contracts tests.test_gui_device_lifecycle tests.test_gui_contacts tests.test_gui_contract -q` outside the socket sandbox | PASS; 58 current QR, boundary, platform, lifecycle, contact, and GUI contract tests     |
| `python scripts/check_boundaries.py`                                                                                                                                                                                             | PASS; distribution and frontend boundaries                                              |
| Active source/test/packaging search for `metor.ui.embedded`, `ui/embedded`, the legacy test, and prototype-only names                                                                                                            | PASS; no active reference, registration, or install path remains                        |
| Source-package inventory below `src/metor/ui`                                                                                                                                                                                    | PASS; only `gui` and `terminal` contain production package initializers                 |
| `ruff check tests/test_contact_qr.py tests/test_ui_boundaries.py`                                                                                                                                                                | PASS                                                                                    |
| `ruff format --check tests/test_contact_qr.py tests/test_ui_boundaries.py`                                                                                                                                                       | PASS                                                                                    |
| `mypy tests/test_contact_qr.py tests/test_ui_boundaries.py`                                                                                                                                                                      | PASS after adding an explicit existing text-content narrowing assertion                 |
| `git diff --check`                                                                                                                                                                                                               | PASS                                                                                    |

## A18 verification

Release wheelhouse construction is now repository tooling at
`scripts.release.bundle`. The documented
`python scripts/build_release_wheelhouse.py` command imports that owner from the
checkout and still exposes all four variants plus `all`. Its repository root is
the canonical value from `scripts.release.paths`, adjusted for the builder's new
location. The former `metor.utils.release_bundle` runtime module is removed with
no redirect.

A real Base wheel and its RECORD contain neither the old builder nor any
`scripts/` path. Builder command-construction, bundle names, installers, locks,
and Base/Terminal/SDK variant ownership remain covered by the release contract
and canonical release workflow tests.

`DEFAULT_COLS`, `INPUT_SELECT_TIMEOUT_SEC`, and `INPUT_SLEEP_SEC` now exist only
in the Terminal constants owner, their sole production consumer. Shared wire
bounds remain SDK-owned and the Base `Constants` class continues to inherit
them without duplicating or changing protocol values.

The lazy `metor.utils` facade now contains only Base-owned runtime utilities:
runtime constants, file lock, process manager, JSON validator, secure path
cleanup, and the intentionally retained pure human-input `TypeCaster`. Core
session-auth primitives and shared onion/buffer helpers are imported directly
from `metor.core.auth` and `metor.shared` by active callers. A fresh isolated
process proves resolving `TypeCaster` performs no host path lookup and loads no
Core, process, or cryptographic dependency. These ownership corrections change
no wire value, persistence format, launcher spelling, compatibility generation,
or application version.

| Command                                                                                                                                                                                                                                           | Result                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New A18 release-owner, Base-wheel, constants-owner, utils-facade and inert-caster regressions before implementation                                                                                                                               | EXPECTED FAIL/ERROR; `scripts.release.bundle` was absent, the Base constants remained duplicated, and the utils facade still redirected Core/shared APIs |
| `python -m unittest tests.test_release_contract tests.test_closure_architecture tests.test_security_contract tests.test_session_auth_contract tests.test_final_remediation_contract tests.test_raw_client_contract -q` outside the socket sandbox | PASS; 89 release, ownership, security, authentication, and raw-client tests                                                                              |
| `python -m unittest tests.test_versioning_release -q`                                                                                                                                                                                             | PASS; 30 wheel metadata, compatibility, release-workflow, and generated-reference tests                                                                  |
| `python scripts/build_release_wheelhouse.py --help`                                                                                                                                                                                               | PASS; public repository command exposes `base`, `terminal`, `sdk`, `gui`, and `all`                                                                      |
| `python -m pip wheel . --no-deps --no-build-isolation -w /tmp/metor-a18-wheel`                                                                                                                                                                    | PASS; real Base wheel built                                                                                                                              |
| Base wheel archive/RECORD ownership inspection                                                                                                                                                                                                    | PASS; no `metor/utils/release_bundle.py` and no `scripts/release` entry                                                                                  |
| `ruff check` and `ruff format --check` for all 28 changed Python files                                                                                                                                                                            | PASS                                                                                                                                                     |
| `mypy` for all 28 changed Python files                                                                                                                                                                                                            | PASS under strict project configuration                                                                                                                  |
| Active source/test/tooling search for old builder and cross-owner utils imports                                                                                                                                                                   | PASS; only the negative no-compatibility regression names the old module                                                                                 |
| `python scripts/check_boundaries.py`                                                                                                                                                                                                              | PASS; distribution and frontend boundaries                                                                                                               |
| `python scripts/versioning.py validate`                                                                                                                                                                                                           | PASS; application 0.2.0 and compatibility registry remain valid                                                                                          |
| `git diff --check`                                                                                                                                                                                                                                | PASS                                                                                                                                                     |

## A19 verification

`VoiceTransferManager` is now a 104-line composition that alone constructs the
shared transition lock, purge fence, dependencies, and inbound/outbound turn
maps. The Voice package names four cohesive behavior owners: `inbound.py`
admits and acknowledges peer begin/chunk/end frames; `retained.py` owns
metadata, hydration, object lifecycle, canonical reconciliation, and retained
projections; `capture.py` owns outbound begin/append/finalize mutation; and
`outbound.py` owns replay, fallback, acknowledgement, read/release, commit, and
cancel behavior. No extracted mixin constructs a second lock, state dictionary,
event bus, or service locator.

The three extractions were made as separate checkpoints. The receive methods
and capture mutation methods have exactly one implementation owner, while
shared metadata helpers moved out of the former outbound abstract placeholders
into the retained owner. Physical module sizes are now 104, 648, 488, 707, and
523 lines respectively; the former 1,078-line manager and 1,184-line outbound
modules no longer exist, and no code was compressed or stripped of explanatory
docstrings to reach that result.

The first complete neighborhood run caught one omitted concrete helper,
outbound ambiguous-write reconciliation; restoring it to `retained.py` made
both commit-then-error regressions pass. The same run also exposed an existing
A12 repeat-finalization timeout when automatic fallback had already removed the
RAM turn. An isolated execution against the untouched A18 commit reproduced
that timeout, proving it was not introduced by the extraction. The narrow
correction projects a repeated finalize only when canonical retained inventory
contains exactly one matching, finalized outbound Voice item. It reads no
content and reports no success for absent, unfinalized, or ambiguous identity.

Accepted protocol frames, persisted metadata and segmented object bytes,
security ordering, producer ownership, and the shared lock contract remain
unchanged. The idempotent canonical projection closes an existing request
completion gap without changing DTO shape, persistence format, protocol
generation, or application version.

| Command                                                                                                                                                                                                                         | Result                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| New inbound, retained, and capture single-owner structure regressions before each extraction                                                                                                                                    | EXPECTED ERROR; each dedicated module was absent before its checkpoint                                                                 |
| `PYTHONPATH=tests python -m unittest test_voice_contract test_closure_voice_edges test_acceptance_repair_contract -q` after inbound extraction                                                                                  | PASS; 36 Voice admission, edge, and repair tests                                                                                       |
| Same focused extraction suite after retained extraction                                                                                                                                                                         | PASS; 37 tests including the added owner regression                                                                                    |
| First full A12/A15 neighborhood run                                                                                                                                                                                             | 93 PASS, 3 ERROR; identified the omitted outbound reconciliation helper and the independently reproducible A12 repeat-finalization gap |
| Three focused ambiguous-write/recovery regressions after correction                                                                                                                                                             | PASS                                                                                                                                   |
| `PYTHONPATH=tests python -m unittest test_voice_contract test_closure_voice_edges test_acceptance_repair_contract test_gui_producers test_gui_capture test_gui_playback test_closure_integration -q` outside the socket sandbox | PASS; 96 actual SDK/IPC, SQLCipher/blob, producer recovery, capture/playback, fallback, and Voice edge tests                           |
| Isolated repeat-finalization test against temporary archive of A18 commit `c90b9f8`                                                                                                                                             | EXPECTED BASELINE ERROR; reproduced the same timeout after canonical LIVE-to-DROP fallback                                             |
| `mypy` for all five Voice implementation modules and the focused contract test                                                                                                                                                  | PASS under strict project configuration                                                                                                |
| `ruff check` and `ruff format --check` for the Voice package and changed tests                                                                                                                                                  | PASS                                                                                                                                   |
| `python scripts/check_boundaries.py`                                                                                                                                                                                            | PASS; distribution and frontend boundaries                                                                                             |
| Voice method-owner and physical-size inventory                                                                                                                                                                                  | PASS; receive only in `inbound.py`, begin/append/finalize only in `capture.py`, every production module below 800 physical lines       |
| `git diff --check`                                                                                                                                                                                                              | PASS                                                                                                                                   |

## A20 verification

The ordered production-source audit covered all 446 tracked Python modules,
excluding ignored build products rather than treating them as source. Every
file received an ownership/header/documentation decision in the required
order. The table records how many files needed callable-contract work and how
many were reviewed unchanged; a changed file remains counted in its one owning
group.

| Owner group                                   | Audited | Updated | Unchanged |
| --------------------------------------------- | ------: | ------: | --------: |
| SDK, shared contract, and versioning          |      63 |       9 |        54 |
| Base, application, CLI, and root entry points |      55 |      12 |        43 |
| Core and storage                              |     155 |      34 |       121 |
| Terminal frontend                             |      36 |       4 |        32 |
| GUI frontend                                  |     137 |      12 |       125 |
| **Total**                                     | **446** |  **71** |   **375** |

All 446 modules have a top-level role header. The one materially incorrect
header was `metor.cli.entry`: it described the general CLI as the Terminal
frontend even though it owns Base command dispatch and selects either frontend
through the public client contract. Its header and `run_cli` description now
state that boundary and its configuration side effect honestly. Historical or
prototype wording was not added to current code, and accurate compatibility
or migration descriptions were retained where they describe live behavior.

A repository test now parses every tracked production module. It requires a
meaningful callable description and explicit `Args:` and `Returns:` sections
for implementations, nested callbacks, Protocol methods, and `TYPE_CHECKING`
signatures alike. The first executable-code form of the test failed on 271
callables; expanding it to declaration signatures exposed the remaining 42.
After correction, all 2,595 functions and methods satisfy the complete rule,
and no module header is missing. Existing behavior descriptions were preserved;
security-sensitive outcomes were made explicit for authenticated IPC connect,
pending-call grants, quick-unlock ACL/owner checks, startup-secret handling,
and frontend credential mode.

The CLI and Terminal presentation trees were compared file by file and through
their import consumers. Both adapters are live: Base commands consume
`metor.cli` presenters/prompts/translations, while interactive chat consumes
`metor.ui.terminal` equivalents. Even the intentionally parallel content and
prompt adapters are independently imported and tested by their distribution.
Removing one copy or introducing a generic UI package would either remove a
live command surface or create the prohibited Base-to-frontend dependency, so
no presentation owner was redirected or merged.

Every one of the 100 pass-only exception handlers was inspected in its owning
operation: 23 are bounded `OSError` descriptor/file cleanup paths, 13 are
typed validation or platform fallbacks, and the remainder are isolated socket
shutdown, rollback-after-primary-failure, optional callback/notification,
hardware-feedback, or best-effort encrypted-object cleanup paths. Mandatory
profile release and destruction do not rely on those passes: database close,
runtime-key release, persistent-key destruction, and cleanup phase failures
are recorded and propagated by `destroy_profile_storage`; file-lock cleanup
also preserves paired acquisition/cleanup failures. No broad catch was changed
merely for style, and optional failures remain bounded and documented.

The repository-control review found no tracked `.env`, `.metor` state,
bytecode, cache, build, distribution, egg-info, virtual environment, private
key, credential, or secret file. `.gitignore` covers those local products
without hiding tracked fixtures or generated references. `.gitattributes`
keeps generated references reproducible and GUI assets byte-exact.
`.env.example` contains only the documented data-parent and optional Tor path,
with no credential value. Python and Node dependency locks are exact-version
inputs and `package-lock.json` resolves cleanly. VS Code settings are valid
JSON; `extensions.json` is editor-owned JSONC and its trailing comma is accepted
by that owner. No tracked data was removed by an ignore-rule change, and no
repository-control file required modification.

The complete suite exposed an earlier safe-settings wire defect unrelated to
the documentation edits. The same two failures reproduced against an untouched
archive of A19 commit `36fa264`: integer registry bounds were placed into DTO
fields whose existing public type is `Optional[float]`, so the strict SDK
discarded the entire descriptor event and the request timed out. The narrow
fix converts present bounds to `float` at the descriptor boundary. It changes
no field, schema, registry value, setting behavior, compatibility generation,
or application version; it makes emitted data conform to the already published
DTO contract.

| Command                                                                                                                                                              | Result                                                                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `python -m unittest tests.test_source_documentation` before callable corrections                                                                                     | EXPECTED FAIL; 271 executable callables lacked a description or complete sections before declaration signatures were added to the same rule |
| Final AST inventory of tracked production Python                                                                                                                     | PASS; 446 module headers, 2,595 callable docstrings, zero missing `Args:`/`Returns:` contracts                                              |
| `python -m unittest tests.test_source_documentation tests.test_terminal_rendering_security tests.test_message_architecture_contract tests.test_closure_architecture` | PASS; 26 documentation, independent-adapter, rendering-security, and owner-boundary tests                                                   |
| First full `python -m unittest discover -s tests -p 'test_*.py'` outside the socket sandbox                                                                          | 786 PASS, 1 FAIL, 1 ERROR; isolated the safe-descriptor timeout                                                                             |
| The two failing GUI settings tests against temporary archive of A19 `36fa264`                                                                                        | EXPECTED BASELINE FAIL/ERROR; identical timeout and unloaded state reproduced before A20                                                    |
| Direct production DTO round trip before correction                                                                                                                   | EXPECTED FAIL; `min_value` declared `Optional[float]` but emitted as `int`                                                                  |
| `PYTHONPATH=tests python -m unittest test_gui_settings -v` after correction                                                                                          | PASS; 5 covered, stale, unknown-result, and descriptor IPC tests                                                                            |
| Final `python -m unittest discover -s tests -p 'test_*.py'` outside the socket sandbox                                                                               | PASS; 788 tests in 662.623 seconds                                                                                                          |
| `ruff check src packaging tests/test_source_documentation.py`                                                                                                        | PASS                                                                                                                                        |
| `ruff format --check src packaging tests/test_source_documentation.py`                                                                                               | PASS; 447 files formatted                                                                                                                   |
| `mypy src`                                                                                                                                                           | PASS; strict project configuration, 444 source files                                                                                        |
| `python scripts/check_boundaries.py`                                                                                                                                 | PASS; distribution and frontend boundaries                                                                                                  |
| `python scripts/versioning.py validate`                                                                                                                              | PASS; version registry unchanged and valid                                                                                                  |
| `python scripts/validate_generated_docs.py`                                                                                                                          | PASS; generated references fresh and reproducible                                                                                           |
| `npm ls --package-lock-only --ignore-scripts --depth=0`                                                                                                              | PASS; locked Prettier dependency resolves locally                                                                                           |
| `git diff --check`                                                                                                                                                   | PASS                                                                                                                                        |

## A21 verification

The documentation now has one human entry point and one active owner for each
contract class. `README.md` describes the framework, the four independently
owned distributions, release-bundle versus source installation, and canonical
`metor` frontend selection. Root `AGENTS.md` remains the short coding-agent
router; `docs/AGENTS.md` sends GUI work to the GUI contract, approved specs, and
the shared frontend boundary. No `docs/README.md` or third product specification
was introduced.

The still-current neutral content formerly named `EMBEDDED_UI.md` now lives only
at `docs/contracts/FRONTENDS.md`. Its introduction describes Terminal, GUI, and
third-party clients of the shared Core/SDK contract without promising a future
Embedded product. Active README, agent, architecture, and GUI-contract links
use the new name. The old path has no redirect or compatibility copy. Historical
source names inside immutable specs and dated audit evidence remain historical
provenance, not active contract links.

The two owner-approved GUI inputs remain byte-identical at their durable
`docs/specs/` paths: functional SHA-256
`8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7`
and layout SHA-256
`3202019b3fd3e7aef472d281006cdb35c1caf073dbaaf2ee75bf691eeaadf5b0`.
The active integration map names those durable inputs. Their byte-identical
`docs/.temp` copies and the now-empty directory are removed; immutable spec
links to older repository history were not edited.

`.prettierignore` protects `docs/specs/` and `docs/generated/` from a broad
Markdown write. Generated Markdown retains its dedicated owner: the generator
formatter supplies an explicit empty ignore file and therefore still formats
only the selected generated target. Repeated generated-reference validation
passes. During verification, the existing mutating `format:md` command was
accidentally invoked with a trailing `--check`; its eight authored/historical
format-only diffs were immediately reversed before semantic edits were
reapplied. The protected specs and generated files never changed, and no
historical evidence rewrite remains in the final diff.

The governance audit now names the actual version registry package and links
to this closure worklog instead of a removed remediation file. Its frontend
review criterion uses typed IPC plus the narrow public host/settings contracts,
not direct profile/process access or a required ephemeral executor. Shared
logic, key cleanup, and thread-failure criteria now preserve owner boundaries,
best-effort physical-erasure limits, and observable mandatory release failures.

Active status text follows the evidence rather than a percentage. Functional
desktop/simulator code is implemented and Linux/Windows installation evidence
is retained, but the current installed Windows WTS/power media, real Linux
suspend/lock media, and updated full-GUI Razer duplex reruns remain mandatory
native acceptance blockers. `GUI.md`, `RELEASING.md`, the current header of the
dated GUI report, and `gui/support.json` agree on that boundary. The machine
manifest contains no completion percentage and reports acceptance false while
those named gates are pending. Historical dated measurements and implementation
SHAs were preserved. The README purge command now promises key-first logical
destruction and best-effort filesystem cleanup, not impossible physical erasure.

| Command                                                                                               | Result                                                                                                                  |
| ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `python -m unittest tests.test_documentation_contract` before changes                                 | EXPECTED FAIL/ERROR; neutral contract, Prettier protection, live governance link, and `.temp` ownership were unresolved |
| `python -m unittest tests.test_documentation_contract tests.test_source_documentation`                | PASS; 5 documentation/source ownership tests                                                                            |
| Active Markdown local file/anchor traversal                                                           | PASS; README, agent, architecture, contribution, glossary, release, governance, frontend and GUI contract links resolve |
| `sha256sum docs/specs/METOR_GUI_SPEC.md docs/specs/METOR_GUI_LAYOUT_SPEC.md` before and after changes | PASS; exact approved hashes unchanged                                                                                   |
| `node node_modules/prettier/bin/prettier.cjs --check` for new/changed focused contracts               | PASS; FRONTENDS, agent, governance and GUI contract use pinned formatting                                               |
| Broad Prettier-write protection plus post-run hash/status inspection                                  | PASS; specs/generated excluded; unintended authored format-only diffs reversed                                          |
| `python scripts/validate_generated_docs.py`                                                           | PASS; targeted formatter bypasses broad ignore and outputs remain fresh/reproducible                                    |
| `python -m metor --version`, `--help`, `chat --help`, and `chat --list-ui`                            | PASS; documented canonical nonmutating entry paths parse; installed Terminal entry point is listed                      |
| `python -m json.tool docs/contracts/gui/support.json`                                                 | PASS; machine-readable status is valid and names pending gates                                                          |
| `ruff check` and `ruff format --check` for changed Python tooling/tests                               | PASS                                                                                                                    |
| `mypy scripts/format_generated_docs.py tests/test_documentation_contract.py`                          | PASS under strict project configuration                                                                                 |
| `git diff --check`                                                                                    | PASS                                                                                                                    |

## A22 verification

The executable distribution-boundary guard now covers the dependency forms
behind the actual package promises. SDK code rejects direct imports of Kivy,
SoundDevice, AccessKit, host configuration, SQL, Tor, and process runtimes. It
also resolves ordinary relative imports, literal `importlib.import_module`
calls (including imported aliases), literal `__import__` calls, and the
repository's `_LAZY_EXPORTS`/`LAZY_EXPORTS` module tuples. Positive fixtures
retain standard-library and SDK-owned imports. Module names assembled from
arbitrary runtime expressions remain intentionally outside this static guard;
the checker says so rather than claiming general dynamic-Python analysis.

Installed acceptance now distinguishes source visibility from an installed
product. A fresh SDK-only venv imports every public SDK owner under `python -I`,
has no Base or UI module, has none of the three GUI toolkits installed or
loaded, and changes neither the environment nor host paths. The next Base-only
stage has no `metor.ui` namespace and no registered frontend. The GUI-only
stage lists exactly GUI before Terminal is installed. Both UI removal orders
still preserve the remaining frontend, and the final SDK reimport proves that
toolkit packages left behind by pip dependency uninstall are not imported by
the SDK. Wheel RECORD ownership and the external strict-mypy positive and
three-error negative consumers remain part of the same isolated gate.

Developer commands now separate changes from checks. `format:*`, `fix:py`, and
`generate:docs` are explicit mutating operations. `check` and its `ready` alias
only inspect state and include Markdown/Python format checks, Ruff, strict
mypy, distribution boundaries, reproducible generated-reference freshness,
and unittest discovery. Making the broad Markdown check executable exposed an
existing eight-file authored/historical formatting backlog. Those eight files
were intentionally normalized with the pinned Prettier; immutable specs and
generated references remained excluded and byte-stable.

CI now exercises both the minimum Python 3.11 and a newer Python 3.13 on Linux
and Windows instead of silently treating `>=3.11` as a 3.11-only promise.
Wheel construction runs throughout the matrix; the heavier native offline
bundle/installed-consumer gate remains on the minimum runtime for both OSes.
On Linux 3.11, two representative native SDL fixtures and the bounded 20 MiB
stream-pressure fixture run in named steps outside `test_*.py` discovery, so
their evidence cannot be mistaken for ordinary unit-test coverage.

Executing those native files exposed two retained-fixture defects that normal
discovery could not see. The synthetic capture still imported live-control
helpers from a path that A17 had converted into the real Linux D-Bus probe;
the helpers now have their own cohesive fixture module. The renderer also
started the unrelated desktop lifecycle subscription, making a synthetic
offscreen capture depend on a live session bus. Only that synthetic harness
now substitutes no lifecycle source; the real Linux lifecycle probe remains
unchanged and separate. The first system-Python attempt lacked Kivy, and the
project venv initially lacked its locked `dbus-next` dependency; these were
environment failures, not product passes. After installing the exact lock and
fixing the fixture boundaries, both native cases exited successfully. Missing
optional `libmtdev` and sandbox clipboard helpers produced Kivy diagnostics but
did not affect the SDL fixture results.

| Command                                                                                                               | Result                                                                                                                         |
| --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| New toolkit/dynamic/lazy-export negative tests before guard changes                                                   | EXPECTED FAIL; all seven forbidden forms passed the import-only scanner                                                        |
| `python -m unittest tests.test_closure_architecture tests.test_quality_gate_contract tests.test_source_documentation` | PASS; 13 boundary, command, CI-matrix, and source-contract tests                                                               |
| `npm run check:md`, `check:py`, `check:types`, `check:boundaries`, and `check:generated`                              | PASS; nonmutating format/lint/type/architecture/freshness path                                                                 |
| First `npm run check` test phase inside the restricted sandbox                                                        | INTERRUPTED after expected local socket errors; static phases had passed, no product result claimed                            |
| Authorized `npm test` outside the socket sandbox                                                                      | PASS; 796 tests in 653.926 seconds                                                                                             |
| `python scripts/validate_installed_artifacts.py <A00 Linux bundle root>` inside sandbox                               | EXPECTED ENVIRONMENT ERROR at temporary local IPC socket; SDK/Base/type stages had passed                                      |
| Same installed-artifact acceptance outside the socket sandbox                                                         | PASS; SDK-only, Base-only, GUI-only, Terminal, both UI removal orders, external mypy positive/negative, and final SDK reimport |
| `gui_native_capture.py --view root_refresh` and `--view setting_keyboard` at 360x640/150% with offscreen SDL          | PASS after fixture repair; explicit native renderer/widget execution outside discovery                                         |
| `gui_stream_pressure.py --result /tmp/metor-a22-stream-pressure.json`                                                 | PASS; 20 MiB source/output, 16 MiB cache ceiling, 64 KiB maximum read, 640-byte maximum frame, 51-record sampled queue peak    |
| `python scripts/check_boundaries.py`                                                                                  | PASS; complete current source tree plus positive/negative regression guards                                                    |
| `ruff check`, `ruff format --check`, and strict `mypy` for changed Python                                             | PASS                                                                                                                           |
| `git diff --check`                                                                                                    | PASS                                                                                                                           |

## A23 verification

Generated-reference update and validation now have different executable
semantics. Normal CI continues to call `validate_generated_docs.py`; the
validator compares the checked-in bytes with two generations, reports stale
and non-deterministic outputs independently, and restores every canonical
artifact to its original byte state in a `finally` block. A failing generator
therefore cannot turn an inspection into an implicit documentation update.

The intentional documentation workflow performs `npm run generate:docs`
first, then runs the nonmutating deterministic freshness check, then stages
only the four canonical generated artifacts. A stale checked-in original still
fails normal CI, while an intentional update remains as a reviewable staged
change. Authored documents remain outside that allowlist.

Release quality now installs and runs static gates without tests, generates all
four references after applying the candidate application version, validates
their determinism and the version registry, and only then runs the complete
candidate test suite. Compatibility comparison, wheel/bundle construction,
installed-consumer validation, and artifact preservation remain downstream of
those gates. The publish job still requires both `prepare` and `quality` and is
unreachable in a dry run, so a generator, compatibility, static, test, build,
or installer failure prevents publication.

Patch `0.2.1` and minor `0.3.0` candidates were exercised in separate temporary
archives of commit `ceb0af5`, with local pinned Node tooling copied into each
archive. In each archive the version registry was changed, all references were
generated, deterministic freshness and the no-previous-release compatibility
path passed, `compatibility.json` contained the exact candidate version, and a
second explicit generation was byte-identical. No repository version, tag,
branch, release, or generated file was changed by these simulations.

First-release behavior remains explicit: `current` is accepted only without a
stable baseline, and compatibility validation without a previous manifest
establishes a baseline without changing any compatibility generation.
Historical comparison tests use synthetic manifests to exercise additive and
breaking IPC, peer classification, SQL migration, keyslot/blob, and derivation
axes; they do not claim an earlier public Metor release or an already required
migration. Application SemVer remains independent from those axes.

| Command                                                                                                | Result                                                                                                       |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Four new workflow/freshness/candidate regressions before implementation                                | EXPECTED FAIL/ERROR; workflows generated in the wrong order and stale validation left modified bytes         |
| `python -m unittest tests.test_versioning_release`                                                     | PASS; 34 registry, SemVer, first-release, synthetic-baseline, generation-order, and candidate-manifest tests |
| `PYTHONPATH=tests python -m unittest test_remaining_closure_contract.RemainingGeneratedReferenceTests` | PASS; stale, nondeterministic, and newline-only drift remain distinct failures                               |
| `npm run generate:docs` followed by `python scripts/validate_generated_docs.py`                        | PASS; intentional generation then two identical validation generations                                       |
| Temporary patch candidate `0.2.1` generation/validation/first-release compatibility/second generation  | PASS; matching manifest and byte-identical repeat, isolated under `/tmp`                                     |
| Temporary minor candidate `0.3.0` generation/validation/first-release compatibility/second generation  | PASS; matching manifest and byte-identical repeat, isolated under `/tmp`                                     |
| Post-validation repository status                                                                      | PASS; no generated reference or version registry change remained                                             |
| `ruff check`, `ruff format --check`, and strict `mypy` for changed Python                              | PASS                                                                                                         |
| `git diff --check`                                                                                     | PASS                                                                                                         |

## A24 verification

Every native offline bundle now declares its exact CPython minor/ABI, operating
system, architecture, distribution, and variant in `BUNDLE.json`. The shipped
stdlib-only verifier rejects a mismatched interpreter or host before creating
or changing `.venv`, then requires a complete, duplicate-free checksum manifest
and validates every bundled file, including the pip wheel. Existing incomplete
or incompatible environments are preserved and rejected rather than silently
reused or deleted. Both installers continue to name one explicit distribution;
they do not install wheel globs. Documentation describes these SHA-256 values as
internal completeness/integrity checks, not signatures or publisher provenance.

The release validators agree on exactly four Metor distribution identities:
SDK, Base, Terminal, and GUI. Missing and duplicate identities fail before the
RECORD ownership checks. Fresh Linux CPython 3.11/x86_64 bundles for all four
variants were built online into a temporary directory; each extracted installer
then installed solely from its wheelhouse. The isolated consumer sequence
verified SDK-only, Base-without-UI, each UI, both UIs together, both UI removal
orders, external strict-mypy consumers, and the final SDK reimport. The Windows
installer has equivalent target/integrity logic and remains an explicit Windows
CI matrix gate; this Linux host cannot honestly supply a fresh native Windows
execution result.

All external GitHub Actions now use immutable commits verified against their
official repositories: checkout v6 `d23441a48e516b6c34aea4fa41551a30e30af803`,
setup-python v6 `ece7cb06caefa5fff74198d8649806c4678c61a1`, setup-node
v6 `249970729cb0ef3589644e2896645e5dc5ba9c38`, upload-artifact v4
`ea165f8d65b6e75b540449e92b4886f43607fa02`, and download-artifact v4
`d3f86a106a0bac45b974a628896c90dbdf5c8093`. Workflow defaults grant no
permissions; each job declares only what it needs. Release jobs checkout the
recorded candidate SHA, publication refuses a moved main branch or an existing
version tag, and the eventual branch/tag push is one explicit command. No tag,
upload, release, or remote mutation was performed here. The unused duplicate
`requirements/runtime.lock` was removed; the active SDK, Base, and GUI locks
remain the single inputs used by the builder.

| Command                                                                                          | Result                                                                                                                    |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| New target/hash/identity/workflow regressions before implementation                              | EXPECTED FAIL; installers accepted broad interpreters, ignored checksums, GUI was optional, and Actions used mutable tags |
| `python -m unittest tests.test_release_contract tests.test_versioning_release`                   | PASS; 74 installer, integrity, wheel-set, immutable-workflow, SemVer, and release-contract tests                          |
| Fresh `python scripts/release/bundle.py --variant all` under Linux CPython 3.11/x86_64           | PASS; SDK, Base, Terminal, and GUI directories and ZIPs built with complete wheelhouses                                   |
| `python scripts/validate_release_installers.py /tmp/metor-a24-bundles.IIjo3C`                    | PASS; all four fresh ZIPs verified hashes first and installed with `--no-index`                                           |
| `python scripts/validate_installed_artifacts.py /tmp/metor-a24-bundles.IIjo3C`                   | PASS; all isolated package/type/ownership/removal scenarios; `ALL_ISOLATED_ARTIFACT_SCENARIOS_OK`                         |
| Wrong Python/architecture, changed/missing wheel, and preserved incompatible `.venv` regressions | PASS; each fails before environment mutation                                                                              |
| Official Action `git ls-remote` verification                                                     | PASS; every pinned commit above resolves from its named official Action repository                                        |
| Windows native installer execution                                                               | NOT RUN locally; non-Windows host, retained as the pinned Windows CPython 3.11 release-matrix gate                        |
| `ruff check`, `ruff format --check`, and strict `mypy` for changed Python                        | PASS                                                                                                                      |
| `npm run check:md` and `git diff --check`                                                        | PASS                                                                                                                      |

## A25 final acceptance

The final local acceptance candidate was
`8b2a9bc3683b1ea9ca455e74fc4ad87c608c12e9` on branch `embeddedui`, tested on
Linux WSL2 x86_64. The complete nonmutating `npm run check` path used system
CPython 3.11.4; the explicit native SDL fixtures used the repository environment
with CPython 3.11.15 and Kivy 2.3.1. Every A00–A24 checkpoint, including A10b,
has a dedicated section above with its implementation decision, evidence, and
any scope limit. No confirmed software defect from the assignment remains
reclassified as a documentation or hardware issue.

The functional and visual review followed
`docs/contracts/GUI_INTEGRATION_MAP.md`, not test count alone. Its mapped owners
and evidence cover bootstrap/profile switching; Text, Voice, and LIVE admission,
continuation, accepted-prefix recovery, and truthful outcomes; lock/privacy,
lost input, lifecycle/power, purge fencing, offline/recovery behavior, contacts,
history, settings, QR, and local keyboard; accessibility/tooltip revocation; and
minimum 360 × 640 at 150% plus wider layouts. The current root-refresh and
settings-keyboard fixtures executed the production Kivy renderer at 360 × 640
and 150% and their PNGs were visually inspected. Unit, encrypted Core/IPC,
controlled-port, simulator, offscreen-native, installed-artifact, and physical
hardware evidence remain explicitly distinct throughout the map and worklog.

The complete gate passed 804 discovered tests in 649.606 seconds after Markdown,
Ruff lint/format, strict mypy, distribution boundaries, and two identical
generated-reference passes. The separate 20 MiB production-worker pressure
fixture passed with 64 KiB maximum reads, 640-byte frames, a 16 MiB cache ceiling,
and a sampled 52-record queue peak. The first native renderer attempt used the
system interpreter and failed before product execution because Kivy was absent;
the exact same fixtures then passed in the project environment. Missing optional
`libmtdev` and unavailable sandbox clipboard helpers produced Kivy diagnostics
but did not fail the SDL renderer. These are recorded as environment diagnostics,
not hidden skips.

A24's fresh Linux bundles remain the package acceptance for this unchanged
product tree: all four exact wheels and ZIPs passed version/dependency, real
RECORD hash/ownership, namespace/type-marker, isolated noneditable install, both
UI coexistence, and both removal-order checks without checkout/PYTHONPATH or
online installation. The final A25-only change is this report. Windows native
installer behavior remains required in the pinned Windows CI/release matrix and
was not rerun on this Linux host.

The approved functional and layout specs still hash to
`8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7` and
`3202019b3fd3e7aef472d281006cdb35c1caf073dbaaf2ee75bf691eeaadf5b0`.
Version registry and machine-readable support JSON validate. Human GUI/release
contracts and `support.json` agree that implementation exists but mandatory
acceptance is pending. The tracked-file inventory has 777 files; checkpoint
ownership above accounts for the introduced packages, scripts, tests, assets,
contracts, and retained dated evidence. There are no untracked files, leaked
credential patterns, tracked local environments, or changed generated/spec
artifacts. Fresh-build `build/` and `*.egg-info` intermediates were removed with
the repository's focused packaging cleanup; user environments and caches were
left intact.

The GUI is therefore **not declared completed at its claimed support level**.
The remaining mandatory native gates are exactly: installed Windows WTS
lock/unlock plus power/media behavior, real Linux suspend/locked-session media
behavior, and a current full-GUI duplex rerun on the documented Razer route.
There is no registered production physical-device adapter, so appliance purge,
shutdown, or arbitrary-headset support is not claimed. No release, tag, upload,
remote push, certification, error-free claim, or completion percentage was made.

| Command / evidence                                                                                                                                       | Result                                                                                                                                           |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `npm run check`                                                                                                                                          | PASS; Markdown, Ruff, format, strict mypy, boundaries, reproducible generated references, and 804 tests in 649.606 s                             |
| `python tests/gui_stream_pressure.py --result /tmp/metor-a25-stream-pressure.json`                                                                       | PASS; 20 MiB input/output, 64 KiB reads, 640-byte frames, 16 MiB cache limit, 52-record sampled queue peak                                       |
| System-Python native SDL attempt                                                                                                                         | ENVIRONMENT ERROR before product execution; Kivy not installed                                                                                   |
| Project-venv `gui_native_capture.py --view root_refresh` and `--view setting_keyboard` with offscreen SDL at 360 × 640 / 150%                            | PASS; production renderer/widget execution and visual inspection; optional mtdev/clipboard diagnostics do not change the result                  |
| A24 fresh four-bundle installer and installed-artifact validation                                                                                        | PASS; exact SDK/Base/Terminal/GUI identities, offline installs, RECORD ownership/hashes, type consumers, coexistence, and both UI removal orders |
| `python scripts/versioning.py validate`; `python -m json.tool docs/contracts/gui/support.json`; generated-reference validation                           | PASS                                                                                                                                             |
| Approved-spec `sha256sum`                                                                                                                                | PASS; both owner-supplied hashes unchanged                                                                                                       |
| Active integration-map review against Lock/Continuation/Purge/Power, Text/Voice/LIVE, profiles, lost input, offline/recovery, accessibility, and layouts | PASS at implemented software/test scope; mandatory physical/native reruns remain explicitly pending                                              |
| Native installed Windows WTS/power/media, real Linux suspend/lock media, current full-GUI Razer duplex                                                   | BLOCKED by unavailable target OS/session/hardware on this WSL2 host; retained as mandatory acceptance gates, not reported as passes              |
| `git status`, ignored packaging-output inventory, tracked-file/secret-pattern checks, and `git diff --check`                                             | PASS after focused packaging cleanup; no unintended repository artifact or credential found                                                      |
