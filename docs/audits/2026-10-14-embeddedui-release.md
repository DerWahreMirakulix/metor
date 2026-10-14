# Embedded UI release review — 2026-10-14

This is the test report for the audit and repairs of `embeddedui`, starting at
`87724a1cdcd46a6099485061c9ea4c2e2e230faa`. The target is **Desktop and Simulator**
on the documented Linux/Windows platforms. Physical embedded hardware is deferred
by the owner. This dated record is evidence; the reusable checklist and product
contracts remain in [AUDIT.md](../governance/AUDIT.md),
[ARCHITECTURE.md](../ARCHITECTURE.md), [FRONTENDS.md](../contracts/FRONTENDS.md)
and [GUI.md](../contracts/GUI.md).

**Disposition:** the implemented review candidate is ready for native desktop
acceptance after its required CI passes. Final release approval remains open for
real public-Tor messaging, physical audio and actual OS lock/suspend evidence.
Automated or simulated success does not establish those results. The owner has
requested that a local agent complete them using the
[self-contained handoff prompt](./2026-10-14-embeddedui-handoff.md).

[PR #11](https://github.com/DerWahreMirakulix/metor/pull/11) records the final
candidate SHA, CI run, complete matrix results and merge into `embeddedui`.
That merge is gated on all required jobs succeeding. A local agent must record
the actual pulled HEAD and verify this evidence before continuing; this report
does not predeclare a still-running CI result. The final documentation-only
handoff commit follows source/test anchor
`f9ba1ae64c749f90b70582f105ae234bc9e2bc51` and receives the same full CI gates.
No `main` merge, application version bump, tag or release publication is part of
this handoff. The application remains `0.2.0`; compatibility generations are
unchanged.

## Architecture assessment

Metor implements the intended messaging-framework boundary. SDK, Base, Terminal
and GUI own disjoint namespace files. The daemon owns authorization, Tor,
durable delivery and cryptographic lifecycle; frontends retain presentation and
interaction state. Device ports cover local observation and control without
granting Core permission. The reference adapter and simulator exercise the same
public contracts used by platform integration.

The source tree groups state owners and cohesive subsystems. This is a layered
domain-oriented implementation, not a claim that every directory is a pure DDD
bounded context. The public facades, dependency checker, generated DTO schema
and installed consumer checks make its boundaries reviewable. The architecture
guide now includes a repository ownership map. No broad directory relocation
was needed to correct the release findings.

The Python SDK is independently installable. Another language can implement
the documented NDJSON protocol without importing Python runtime internals.
Portability depends on the exact framing, authentication derivation,
correlation, version and reconnect contracts; these are now explicit in the
generated API guide. An IPC generation handshake does not negotiate individual
additive fields with an older implementation.

## Corrections included in this review

| Area                   | Problem and resulting behavior                                                                                                                                                                                                                                                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Offline execution      | The short-lived local executor used a loopback TCP listener. Its connection is changed to a private non-inheritable socket pair, preventing unrelated local clients from entering that operation's unlocked runtime. Its gate remains held until sensitive storage cleanup succeeds.                                                                    |
| Profile lifecycle      | Catalog mutations, startup, live instances and migration use stable external gates in a defined order. Managed processes retain instance ownership from initialization through cleanup. Offline operations recheck eligibility while holding the same exclusion, and recovery cannot discard an in-progress prepared migration.                         |
| Authentication         | Challenge and proof handling is tightened; portable documentation specifies domain-separated inputs, Argon parameters, encodings and one-use challenge behavior. The architecture reference is corrected to IPC generation 4.                                                                                                                           |
| Device privacy         | Temporary Power/purge covers cannot suppress idle or native-lock restriction. Lost focus, suspend and input loss cancel held destructive controls; stale device state cannot reopen a replaced profile.                                                                                                                                                 |
| Notification exports   | File-sink writes enforce private regular-file ownership and reject link/device/FIFO targets. POSIX opening cannot block on an unread FIFO. Canonical docs explicitly identify plaintext metadata exports and direct, non-Tor webhook networking.                                                                                                        |
| Contact labels         | Core rejects empty, control-bearing, surrogate or multiline new aliases while preserving Unicode, spaces and joined emoji. Existing malformed labels remain recoverable by lookup, rename or removal; UI output escaping remains independently enforced.                                                                                                |
| GUI interaction        | Native acceptance exercises readable compact controls, profile/security forms, keyboard focus and call navigation. Simulator configuration applies real scale/rotation and prevents undeclared desktop-audio fallback.                                                                                                                                  |
| Terminal               | Untrusted output is escaped at presentation boundaries. Aliases refresh consistently and slash commands accept quoted labels with spaces. Unicode grapheme/cell editing, bounded draft/history storage, cursor-centered multiline viewports, Windows surrogate decoding and height/width resize handling replace inconsistent character-count geometry. |
| CLI outcomes           | Rejected arguments, cancelled or invalid migration credentials, transport/authentication failures and incomplete offline teardown produce nonzero status. Unconfirmed execution is reported as an unknown outcome without leaking exception details. Human-readable CLI output remains distinct from the typed SDK/IPC integration contract.            |
| Installation           | README instructions now create and select an environment, explain first-profile setup, distinguish GUI autostart from independent daemon lifetime, and accurately describe Windows wheels and unpublished package-index targets.                                                                                                                        |
| Distribution integrity | Every distribution includes the canonical GPL license text; installed-artifact validation checks the actual wheel bytes. Terminal dependency closure remains separate from Base and SDK.                                                                                                                                                                |
| Dependencies           | Identified vulnerable pins are updated to `pip==26.2.1`, `setuptools==83.0.0` and `urllib3==2.8.0`; the final strict advisory audit covers all 39 pinned Linux/Windows third-party distributions with none skipped.                                                                                                                                     |
| Build cleanup          | Packaging removes only its own generated directories, preserving `build/test-report.txt`, audit evidence and earlier release variants. Destinations inside setuptools-owned directories fail before mutation.                                                                                                                                           |
| Release validation     | CI and release use one native GUI acceptance action, including compact/wide Core-backed windows, rendering, simulator configuration, stream pressure and an isolated native AT-SPI privacy gate. Redundant shell installer smoke blocks are removed; the checked native installer validator remains mandatory on both OS jobs.                          |
| Test strategy          | Behavioral regression, source-boundary and installed/native gates have distinct purposes. Contributor guidance rejects private-implementation mirrors as substitutes for observable behavior and keeps duplicate removal conditional on retained coverage.                                                                                              |

## Additional security and frontend repairs

- **Protected files and migrations:** Windows PIN credentials and profile keys
  share one owner-only ACL policy. Migration staging validates private ownership,
  bounded regular files and source identity, rejects links/special files, and
  uses exclusive temporary files. POSIX PIN reads open with nonblocking,
  no-follow descriptors and validate the actual descriptor before reading;
  replacing a candidate with a FIFO cannot hang authentication.
- **IPC and SDK failures:** malformed proof text, non-object JSON, invalid
  endpoints and non-finite limits fail explicitly. Connection budgets include
  DROP/CALL paths. Secret DTO fields are excluded from representations. Invalid
  or unknown SDK events terminate the connection and wake pending requests;
  failed initialization releases its lease.
- **GUI privacy after monitor failure:** loss of the native security observer
  permanently closes that GUI session. Unlock, reconnect, profile activation or
  a stale callback cannot restore private content. Accepted purge may expose
  only sanitized progress. The final cover offers Close and exits with failure;
  independent daemon clients remain usable.
- **GUI scrolling and completion:** bounded scrolling keeps footer controls
  reachable at low frame rates. Outgoing optimistic message rows do not count
  as confirmed Core completion in native acceptance. Real scale/rotation,
  control readability, accessible names, LIVE connecting state and DROP opening
  are exercised through the native event loop.
- **CLI encoding:** redirected stdout/stderr use UTF-8 while normal terminal and
  absent-windowed streams retain their appropriate behavior. Piped credentials
  use strict bounded UTF-8. Windows interactive prompting retains the TTY path.
- **Native Windows evidence:** the fixture owns a visible console, follows the
  actual launcher/interpreter chain, and checks that both GUI launchers preserve
  the original console without creating an extra one. Windowed startup without
  standard streams, native error handling, autostart cancellation, PIN security
  and Tor-child console suppression are covered. Hosted validation explicitly
  selects the pinned ANGLE backend; the product's default backend is unchanged.

The security review covered authentication and replay, framing and resource
bounds, credential/PMK lifecycle, storage permissions and replacement races,
profile exclusion and migration recovery, process ownership, notification export
boundaries, untrusted presentation and privacy revocation. Corrections have
behavioral regressions at the relevant boundaries. This is a source and runtime
review with the recorded evidence, not a formal cryptographic proof or a claim
that undiscovered vulnerabilities cannot exist.

## Verification evidence

The table distinguishes reproducible automated coverage from physical acceptance.
Final CI status and exact per-platform totals belong to PR #11's immutable run;
previous successful jobs must not be substituted for a failed final candidate.

| Gate                                  | Recorded result and scope                                                                                                                                                                                                                                                                    |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Static analysis                       | Ruff and formatting pass over 703 Python files; Mypy passes over 529 files for Linux/Python 3.11 and Windows/Python 3.13. The focused GUI Basedpyright gate passes all four platform/version targets.                                                                                        |
| Repository contracts                  | Import boundaries, generated-reference reproducibility, version/compatibility checks, Markdown formatting and local links pass. Generated documents are produced from their owners.                                                                                                          |
| Full runtime suite                    | Required matrix: Linux and Windows x86-64, CPython 3.11 and 3.13, each discovering 1,452 tests. Skips are explicit capability decisions, not passes: the preceding completed runs recorded 14 Linux and 31 Windows skips. Consult the final run for actual totals and failures.              |
| Packages and installers               | Fresh CPython 3.11 offline bundles, all four independently owned packages, isolated installed consumers, SDK typing, dynamic frontend IPC, uninstall/reinstall isolation and all four actual ZIP installers pass on both native CI platforms at the source/test anchor.                      |
| Linux native GUI                      | Compact/wide real Core-backed interaction, keyboard/mouse dispatch, low-frame-rate scrolling, scale/reflow/readability, simulator configuration, stream pressure and permanent monitor-failure cover pass. Native AT-SPI privacy checks pass from a separate process.                        |
| Windows native GUI                    | Both installed launchers, console preservation, no-stream error dialog, encrypted autostart cancellation, PIN and Tor-child launch checks pass. These are native CI desktop checks, not physical audio or OS-state transitions.                                                              |
| Targeted security and CLI regressions | Six POSIX PIN special-file/replacement cases, 12 actual CLI process cases with forced cp1252, and 12 prompt/output/failure cases pass.                                                                                                                                                       |
| Writer/cancellation regressions       | 53 related Voice tests and 12 focused transport cases pass. Deliberate slow encrypted staging reproduces the former fixture failure; explicit release fixes ordering. Injected extra coalesced bytes are detected; early-failure cleanup releases blocked workers.                           |
| Dependency advisories                 | Strict audit of all 39 pinned Linux/Windows third-party Python distributions reports zero known vulnerabilities and zero skipped distributions; all three resolved npm tooling packages also report zero. This is the advisory database result on the review date, not a security guarantee. |
| Public Tor peer roundtrip             | **OPEN:** no public-Tor relay connectivity in this cloud environment. Loopback routing and bootstrap-only checks are insufficient.                                                                                                                                                           |
| Physical audio and OS transitions     | **OPEN:** real microphone/playback/call audio, actual screen lock and suspend/resume need named-host evidence.                                                                                                                                                                               |

### Native artifact at the source/test anchor

[Run 38629245682](https://github.com/DerWahreMirakulix/metor/actions/runs/38629245682)
checks `f9ba1ae64c749f90b70582f105ae234bc9e2bc51`. Its Linux installed/native job
`116076301823`, Windows installed/native job `116076301488`, and static job
`116076301100` succeeded. The Linux artifact ID is `11925147798`, with archive
SHA-256 `2e7cf8933d628e78df9db09b5e59e16a4cea9e36cc7a1061e14cd3c121f4a260`.
It contains 48 PNGs and structured acceptance results:

- Compact 360 × 640 at font scale 1.5: 139 entries, including 137 successful
  Boolean checks and two geometry records; 378 XTest events.
- Desktop 1180 × 760 at font scale 1.5: 146 entries, including 144 successful
  Boolean checks and two geometry records; 352 XTest events.
- Both Core-backed scenarios retain 20 captures each and confirm GUI detach,
  an independently usable client and cleanup of their temporary Core runtime.

These runs use real GUI/SDK/Core IPC, SQLCipher and signed peer framing.
Loopback replaces Tor/SOCKS, and lifecycle events are supplied by controlled
fixtures. Neither is counted as actual Tor-network or OS-provider acceptance.
Artifact retention is finite; archive the relevant evidence with the final
release record if it must outlive GitHub Actions retention. Final handoff CI
regenerates native artifacts; PR #11 identifies that final run as well.

### Why the test corrections improve evidence

The native send fixture previously advanced when an optimistic row appeared,
before its pending Core request completed. A controlled 3.2-second real reply
reproduced the failure. Waiting for the visible row **and** no matching pending
request passes at both window sizes without extending production deadlines.

A Voice cancellation fixture previously released a writer barrier after two
seconds even if encrypted staging had not finished. On a slower Windows runner,
voice frames could pass before the cancellation being tested. The replacement
barrier is explicitly released by test cleanup; real socket and observation
deadlines remain bounded. The reader is retained so bytes already buffered after
the expected frame cannot disappear from the assertion. Negative controls show
both the former false failure and the former false pass. Cleanup failure tests
confirm the correction cannot strand the fixture's workers.

These are concurrency and stream-boundary checks with observable failure modes.
The test policy now distinguishes narrow state tests, process/IPC regressions,
native interaction, package ownership and physical acceptance. Redundant shell
installer checks were removed only where the checked native validator preserves
failure propagation; a coverage percentage is not used as a quality claim.

## Native acceptance still required

The [handoff prompt](./2026-10-14-embeddedui-handoff.md) is intended to be given
in full to the local agent after pulling `embeddedui`. It covers:

1. Actual public-Tor DROP and LIVE messages across GUI, Terminal and CLI, with
   received content and independent frontend/daemon lifetime evidence.
2. Real Voice capture, explicit preview/send, receipt/playback in both directions,
   device failure recovery, and accepted telephone-call audio/mute/hangup.
3. Actual OS screen lock and suspend/resume: protected private content, stopped
   Voice recording/playback, continued accepted calls on screen lock, and ended
   real-time audio after suspend. Simulated events do not close this item.
4. Native GUI screen/control review, resizing, text scale, focus/navigation,
   menus, destructive holds, and simulator scale/rotation/input behavior.
5. Fixes and suitable regressions for any defect, followed by final-commit CI and
   a result table with PASS/FAIL/BLOCKED, host details and concrete observations.

Linux desktop and simulator require SDL/OpenGL, system D-Bus and a registered
logind login resolvable through `GetSessionByPID`. An SSH shell, WSL or an Xvfb
display alone does not establish that production environment. Do not disable the
security observer to obtain a pass. Native Windows mixed-DPI and a user's actual
accessibility tools should be checked on the available desktop; the AT-SPI and
UIA fixtures do not certify every screen reader or display configuration.

Only the tested host can receive a physical acceptance claim. A Linux-only local
run cannot establish Windows audio/OS behavior, or vice versa. Physical embedded
hardware, other operating systems/architectures and acoustic echo cancellation
are not established by this review. Remaining failures or unavailable required
capabilities must stay explicit release blockers, with no blanket "release ready"
claim.

After native acceptance, follow [RELEASING.md](../RELEASING.md). Its release
workflow must validate the actual proposed version and native archives; ordinary
PR CI is not a substitute. A release dry run and publication were not executed
by this audit. Final merge into `main` and publication are separate owner actions.
