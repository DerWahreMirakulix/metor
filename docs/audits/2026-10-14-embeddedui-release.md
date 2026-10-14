# Embedded UI release review — 2026-10-14

This record captures the final review of the `embeddedui` development state,
starting at `87724a1`, on the `codex/embeddedui-release-audit` branch. The release
target is **Desktop and Simulator**. Physical embedded products and their native
hardware acceptance belong to a later release and are not blockers for this
scope. The reusable checklist remains in [AUDIT.md](../governance/AUDIT.md);
this document is dated evidence, not a second source of product contracts.

The review covers ownership and packaging, daemon/IPC/SDK integration, GUI and
Terminal interaction, CLI interoperability, security boundaries, installation,
documentation and release gates. Implemented corrections are part of the review
candidate; an initial baseline result does not validate later edits.

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
| Dependencies           | Identified vulnerable pins are updated to `pip==26.2.1`, `setuptools==83.0.0` and `urllib3==2.8.0`; the dependency audit must be repeated against the final environment.                                                                                                                                                                                |
| Build cleanup          | Packaging removes only its own generated directories, preserving `build/test-report.txt`, audit evidence and earlier release variants. Destinations inside setuptools-owned directories fail before mutation.                                                                                                                                           |
| Release validation     | CI and release use one native GUI acceptance action, including compact/wide Core-backed windows, rendering, simulator configuration, stream pressure and an isolated native AT-SPI privacy gate. Redundant shell installer smoke blocks are removed; the checked native installer validator remains mandatory on both OS jobs.                          |
| Test strategy          | Behavioral regression, source-boundary and installed/native gates have distinct purposes. Contributor guidance rejects private-implementation mirrors as substitutes for observable behavior and keeps duplicate removal conditional on retained coverage.                                                                                              |

## Native Linux evidence observed during the review

The [Core-backed native fixture](../../tests/gui_native_core.py) passed on Linux
with CPython 3.12.14, Kivy SDL2 and X11 XTest input through the native event queue.
At font scale 1.5, the 360 × 640 run recorded 139 successful checks and 378 input
events; the 1180 × 760 run recorded 146 successful checks and 484 input events.
Each run retained 20 screen captures and confirmed that closing the GUI left an
independent client usable. The broader native visual review examined 42 screen
captures. These runs used actual Core IPC, SQLCipher and peer framing; bounded
loopback TCP replaced Tor to make transport outcomes deterministic.

The [native accessibility fixture](../../tests/gui_native_accessibility.py) also
passed through an external AT-SPI client with `NATIVE_ATSPI_PRIVACY_OK`. The exact
shared-action command was rerun using a private `dbus-run-session`, writable
isolated XDG configuration/runtime directories, runtime permissions `0700`,
Xvfb/SDL2, a 90-second deadline with a 5-second kill grace, and a 64 KiB log cap.
It exited successfully and produced a 5,639-byte log. The same fixture and
isolation now run in both CI and release through the
[shared GUI action](../../.github/actions/gui-acceptance/action.yml).

These observations establish the exercised Linux virtual-display interactions,
including accessibility privacy revocation; they do not establish physical
input/audio, native OS lock/suspend providers, public Tor bootstrap or native
Windows behavior. Final candidate reruns and artifact retention belong in the
verification record below.

## Verification record

Local acceptance uses the reviewed source candidate and fresh CPython 3.11.16
consumer environments. Open entries below are not implied passes; native CI
must validate the immutable pull-request candidate before merge.

| Check                                                | Result                                    | Evidence or scope                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Focused release/versioning tests                     | Pass                                      | `python -m unittest discover -s tests -p test_versioning_release.py`: 37 tests, including four source-wheel builds and atomic ref-push rejection; Linux CPython 3.12.                                                                                                                       |
| Changed release scripts and tests                    | Pass                                      | Ruff lint and formatting checks; five focused release-contract cases including cleanup preservation, unsafe output rejection, SDK/Terminal closures and the offline install guide.                                                                                                          |
| Static and generated-reference gates                 | Pass                                      | Ruff lint/format (695 files); Mypy (527 files) for Linux/Python 3.11 and Windows/Python 3.13; all four GUI Basedpyright targets; package boundaries; reproducible generated references; central version and first-release compatibility baseline; Markdown formatting and local links.      |
| Complete unit/integration suite                      | Running — final candidate                 | Linux CPython 3.11 supervised full inventory; native CI also runs Linux/Windows CPython 3.11 and 3.13.                                                                                                                                                                                      |
| Dependency vulnerability audit                       | Pass                                      | `pip-audit` on all 32 resolved third-party distributions: no known vulnerabilities after the pinned updates. `npm audit`: no known vulnerabilities in the three resolved tooling packages. This is an advisory-database result, not proof that dependencies contain no defects.             |
| Installed namespace and offline bundle acceptance    | Pass — native Linux CPython 3.11          | All four fresh offline bundles built at version 0.2.0. Wheel version, ownership and canonical license checks passed; isolated SDK typing/imports, dynamic frontend IPC, managed daemon startup, native GUI start, uninstall/reinstall isolation, and all four actual ZIP installers passed. |
| Native Linux GUI and simulator                       | Open — root audit                         | Record final compact/wide, text scaling, input, privacy and Core interaction evidence.                                                                                                                                                                                                      |
| Native Windows acceptance                            | Open — release owner                      | Native Windows CI is required for a Windows release claim; Linux/WSL tests do not establish it.                                                                                                                                                                                             |
| Physical embedded appliance                          | Not applicable                            | Explicitly outside Desktop/Simulator release scope.                                                                                                                                                                                                                                         |
| Public Tor bootstrap and physical media/OS lifecycle | Not established by deterministic fixtures | Record separately on a named host when making these runtime claims.                                                                                                                                                                                                                         |

## Release decision

Final acceptance is pending the root audit's completed verification record and
the native release workflow. This review does not claim formal third-party
security certification, verified physical erasure, universal audio routing,
acoustic echo cancellation, complete screen-reader certification or physical
device support. Publishing remains the explicit, candidate-bound process in
[RELEASING.md](../RELEASING.md).
