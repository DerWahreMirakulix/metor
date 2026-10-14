# Local agent handoff: embeddedui native release acceptance

Give this entire document to the local agent after pulling `embeddedui`. It is
the continuation prompt, including the remaining work and evidence requirements.
The associated [test report](./2026-10-14-embeddedui-release.md) records the
completed audit. Communicate with the owner in German; keep repository prose,
code and commit messages in English.

## Your task and authority

Continue Metor's final audit and repair work on the native desktop. The owner
wants a production-ready Tor messaging framework with independent GUI, Terminal
and CLI clients, a portable documented IPC/SDK boundary, and security as the
highest priority. Native GUI usability is the main product priority. Supported
scope for this acceptance is **desktop and simulator**; physical embedded
devices are deferred. Discover the available OS and tools yourself.

Perform the tests below, fix reproducible defects, add meaningful regressions,
and update the test report with observed results. Do not stop after listing
fixable problems. Preserve unrelated user work and private profiles. Keep
`main`, release tags and publication unchanged: prepare a reviewable final
candidate, then leave the owner's final main merge and release decision pending.
Do not automatically bump application or compatibility versions. The handed-off
application version is `0.2.0`.

Read these existing owners before making changes:

- [Root agent entry point](../../AGENTS.md), [agent routing](../AGENTS.md) and
  [contribution rules](../CONTRIBUTE.md).
- [Audit report](./2026-10-14-embeddedui-release.md),
  [README installation](../../README.md) and [GUI contract](../contracts/GUI.md).
- [Architecture](../ARCHITECTURE.md) and
  [frontend contract](../contracts/FRONTENDS.md) for ownership questions;
  [generated API](../generated/API.md) and
  [wire schema](../generated/api.schema.json) for IPC questions.
- [Release policy](../RELEASING.md) before any packaging, compatibility or
  release-related change. Generated documents must be regenerated from their
  owners, never edited by hand.

The daemon owns authorization, crypto, transport and durable state. Frontends
own presentation and interaction only, using typed SDK/IPC and the documented
host/settings/device boundaries. Do not solve a GUI issue by reading SQL,
Tor keys or private profile runtime files from the frontend. Prefer cohesive
domain fixes over cosmetic restructuring or a second implementation of an
existing contract.

## Establish the exact candidate

Inspect the repository root, `git status`, branch, remote and full HEAD. Preserve
local changes; update `embeddedui` only by a safe fast-forward. Create a separate
branch or worktree for any further fixes. Do not reset or clean user work.

The cloud audit is
[PR #11](https://github.com/DerWahreMirakulix/metor/pull/11), targeted at
`embeddedui`. Verify that its final candidate is merged into the local branch
and that its final **Required CI result** passed. Record the actual merged HEAD,
CI run URL and tested commit. The source/test evidence anchor is
`f9ba1ae64c749f90b70582f105ae234bc9e2bc51`; documentation and merge commits may
follow it. Do not silently substitute that anchor for your actual checkout or
reapply its already-integrated fixes. If remote status is unavailable, record
the limitation and continue independent native checks without claiming the CI
gate has been verified.

The cloud work already covers repository boundaries, portable IPC/SDK contracts,
security fixes, all four distributions and ZIP installers, static checks, the
Linux/Windows CPython 3.11/3.13 runtime matrix, native GUI fixtures and simulator
configuration. Consult the report and final CI for precise results and skips.
Do not rerun every completed investigation without a new failure or change.
The remaining environmental gap is **real public-Tor messaging, physical audio,
actual OS lock/suspend, and inspection on the available native desktop**.
The cloud's loopback peer transport and injected lifecycle events do not close
that gap; bootstrap success alone does not prove message delivery.

## Isolated native setup

Record date, OS/build, architecture, desktop/session, Python and Tor versions,
GUI backend, display scaling, audio endpoints/drivers, installation method and
whether operation is local or remote. Prefer CPython 3.11 x86-64 for matching the
accepted offline bundles. CPython 3.11 through 3.13 is supported by metadata;
the automated platform matrix covers 3.11 and 3.13 on Linux and Windows x86-64.

Use a new virtual environment or the matching installed CI bundle. Do not mix
artifacts from different commits or upgrade global Python. For a source install,
create `.venv` with `python3.11 -m venv .venv` on Linux or
`py -3.11 -m venv .venv` on Windows. Use that environment's Python and programs
explicitly; activation is optional. From the repository root:

```text
python -m pip install -r requirements/gui.lock -r requirements/terminal.lock ./packaging/sdk . ./packaging/terminal ./packaging/gui
python -m pip check
python -m metor chat --list-uis
```

Here and below, `python` and `metor` mean the selected environment's executables:
`.venv/bin/python` and `.venv/bin/metor`, or `.venv\Scripts\python.exe` and
`.venv\Scripts\metor.exe`. When developing fixes, use the checkout installation
in `CONTRIBUTE.md` (`python -m pip install -r requirements/dev.txt`) and verify
installed artifacts again when the changed boundary requires it. Editable
imports alone do not prove wheel correctness.

Create a fresh private test-data parent. Set `METOR_DATA_DIR_PARENT` to its
absolute path **before every Metor process**, including additional terminals.
Metor creates `.metor` beneath it. Never use the owner's normal profile directory
for acceptance, destructive actions or cleanup. Do not inspect personal `.env`
files or profiles. Use synthetic messages and contacts only.

Linux example, inside a real graphical login:

```sh
umask 077
METOR_ACCEPTANCE_PARENT="$(mktemp -d "$HOME/metor-acceptance.XXXXXXXX")"
export METOR_DATA_DIR_PARENT="$METOR_ACCEPTANCE_PARENT"
export METOR_TOR_PATH="$(command -v tor)"
"$METOR_TOR_PATH" --version
```

Windows PowerShell example, as the ordinary logged-in user:

```powershell
$MetorAcceptanceParent = Join-Path $env:LOCALAPPDATA ('Metor-Acceptance-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $MetorAcceptanceParent | Out-Null
$env:METOR_DATA_DIR_PARENT = $MetorAcceptanceParent
$env:METOR_TOR_PATH = 'C:\actual\Tor Expert Bundle\tor\tor.exe'
& $env:METOR_TOR_PATH --version
```

Resolve the actual Tor installation first; the Windows path is a placeholder.
Reuse the same absolute test parent in every test terminal. Enter test passwords
only through the intended masked prompts, never command arguments, shell
history or reports. Use different passwords for the two encrypted profiles.

Linux production GUI and simulator require SDL/OpenGL, system D-Bus and a
registered logind session resolvable through `GetSessionByPID`. An SSH shell,
WSL or Xvfb display alone does not establish that environment. Windows needs a
native desktop and working graphics; the documented optional VM backend is
`$env:KIVY_GL_BACKEND = 'angle_sdl2'`. Record any override. Physical audio needs
working native input/output devices and PortAudio. Report missing capabilities;
never disable security observers or insert test lifecycle/transport adapters to
claim a native pass.

## Public-Tor messaging and frontend interoperability

Create two profiles, retaining the default encrypted mode:

```text
metor profiles add acceptance-alice
metor profiles add acceptance-bob
```

Use **Use profile password** as the GUI's local unlock method for the lock
tests. **No screen lock** would produce a different expectation. In separate
terminals, start and authenticate:

```text
metor -p acceptance-alice chat --ui gui --start-daemon
metor -p acceptance-bob chat --ui terminal --start-daemon
```

Wait for actual Tor readiness. From a third test terminal, obtain both onion
addresses and create contacts, replacing the uppercase placeholders:

```text
metor -p acceptance-alice address show
metor -p acceptance-bob address show
metor -p acceptance-alice contacts add Bob BOB_ACTUAL_ONION
metor -p acceptance-bob contacts add Alice ALICE_ACTUAL_ONION
metor -p acceptance-bob send Alice "acceptance-cli-to-gui-UNIQUE_RUN_ID"
```

1. Observe that exact CLI DROP in Alice's GUI. Queue admission or exit code 0
   is insufficient. Send a distinct DROP from Alice's GUI to Bob and inspect it
   in Bob's Terminal with `/inbox Alice`; optionally also use
   `metor -p acceptance-bob messages show Alice`. Opening a peer inbox consumes
   unread text; account for that intentional action.
2. In Bob's Terminal, run `/connect Alice`, explicitly accept the LIVE text
   invitation in Alice's GUI, and use `/switch Alice` if needed. Send distinct
   LIVE texts in both directions, observe the actual received content and
   state, then `/end Alice`. Navigation must not silently connect or accept.
3. Attach a second Terminal to Alice using
   `metor -p acceptance-alice chat --ui terminal --start-daemon`. Check CLI
   sends, contact changes and visible text state across her clients. Rename a
   synthetic contact through a supported interface and verify current aliases
   update consistently. Exercise a quoted alias containing spaces, Unicode
   editing, multiline output, resize and asynchronous redraw in the Terminal.
4. Close Alice's GUI while her Terminal remains attached. Verify the other
   client stays usable, reopen the GUI and authenticate independently. Check
   durable DROP history and delivery state without duplicates. Delivered LIVE
   transcripts are intentionally volatile; do not require them to survive a
   GUI restart. Core-owned pending/unseen content must remain reachable.
5. On Windows, also reopen using the actual installed windowed launcher:
   `.venv\Scripts\metor-gui.exe -p acceptance-alice --start-daemon`. Check that
   the existing terminal stays visible and no extra console appears.

Use real Tor onion routing throughout. Two independent profiles on one host can
establish a public-Tor roundtrip; direct loopback peers or a test SOCKS bridge
cannot. The optional installer validator's `--with-public-tor` checks bootstrap
and IPC, not these received messages. CLI output is human-readable UTF-8;
automated typed assertions should use the documented SDK/IPC contract.

## Physical Voice and calls

Keep Bob's Terminal open and attach his GUI as well. Under
**Settings → Device → Audio settings**, choose actual input and output endpoints
for both GUIs. Selection alone must not start recording. Use separate headsets,
devices or another host if the driver cannot share an endpoint; do not infer
acoustic success from a transport status or successfully opened stream.

1. In Alice's DROP conversation, use **Record → Stop → Preview** with a short
   recognizable spoken sentence. No Voice content may reach Bob before explicit
   **Send**, and preview must require Play. Send, then manually play it in Bob's
   GUI and verify intelligible sound. His Terminal may show a Voice notice but
   must not consume the media merely by displaying that notice.
2. Repeat in the opposite direction. Discard another recording and verify no
   recipient content appears. Exercise LIVE Voice with explicit recording,
   stop and send; accepting LIVE text must not start audio capture or a call.
3. Test a real missing/disconnected audio endpoint, when safe for other host
   applications. A deliberate record/play action must offer intelligible
   recovery while text remains usable. Reconnection or reselection must not
   automatically record, play or send.
4. Start a separate telephone call and explicitly accept it at the peer. Verify
   audible communication in both directions, Mute/Unmute and Hang up. Do not
   claim echo cancellation or support for untested devices.

Null audio, generated PCM, simulated waveforms and stream creation are not
physical recording/playback evidence. If tools cannot perform a physical action
or hear output, ask the owner only for the necessary action or observation and
identify it as a human observation in the report. Continue independent work.

## Actual OS lock and suspend

Save a small local checkpoint before suspend; remote control may disconnect.
Use the real OS function: Windows `Win+L` and Sleep, or the desktop's actual
screen lock and Suspend on Linux. Do not substitute injected lifecycle events,
hibernate or power-off. Preserve the separate expectations below:

- **Voice recording and playback:** lock during each in separate trials. Both
  stop. After OS unlock, Metor remains protected until its configured unlock
  succeeds, with no flash of private pixels, tooltips or accessible content.
  Retained recording prefixes stay unsent. Unlock never resumes capture,
  playback or send. Focus loss may stop capture before the lock; record that
  separately. A held PTT must require release and a fresh press.
- **Already accepted call:** screen lock preserves the call and mute state.
  Private chats stay covered. After OS unlock, the protected call bar provides
  Mute/Hang up with identity filtered by notification privacy. Actually observe
  continued audio; text LIVE acceptance alone is not an accepted call.
- **Suspend/resume:** repeat with an accepted call, and separately with Voice
  capture/playback. Suspend ends real-time audio. Resume must not restart the
  call/media, replay a backlog or automatically accept another call.
- **Other revocation:** hard profile lock, profile switch and client loss end
  the affected call and clear private presentation. Ordinary GUI window close
  detaches that frontend without shutting down another client's daemon work.
  If testing monitor failure safely is possible, the failed GUI must retain
  its permanent Restart Metor cover and Close action. Do not stop system
  security services globally to manufacture this test.

A single shared audio endpoint may be insufficient for a credible two-way call
test. Mark the specific missing physical check BLOCKED and use a second audio
chain or host if available. A Linux-only observation does not prove Windows
physical behavior, or vice versa.

## Native GUI and simulator inspection

Inspect the actual window, not only source or screenshots. Make an inventory
of screens and controls encountered and record uncovered paths. Review every
visible button, overflow/ellipsis menu, icon action and dialog in those paths
for clear purpose, correct result, disabled/pending behavior and recovery.
Use the GUI contract for exact semantics, with particular attention to:

| Path                                  | Required review                                                                                                                                                             |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Entry, authentication, lock, profiles | Password/PIN purpose and confirmation names; safe cancel/back; failed authentication; profile switching; no stale private content.                                          |
| DROP overview and conversation        | Empty/loading/error states; New Drop; composer; send/pending/delivered distinctions; message and conversation menus; delete scope and confirmation; Voice controls.         |
| LIVE overview and conversation        | Invitations and explicit accept/reject; Start/Cancel/End/Retry; Open Drop; ended contexts; pending fallback/removal; Call and More reachable beside the header.             |
| Contacts and own contact              | Add/rename/remove; long Unicode names; dynamic labels; public address and permitted Copy; camera/QR capability errors without automatic camera or communication.            |
| Notifications and settings            | Correct action destinations; privacy modes; Live/Privacy/Device/Profiles/Advanced sections; truthful saving/errors; readable footer controls and supported device settings. |
| Overlays and destructive controls     | Focus and Escape/Back ordering; dismissible sheets; no invisible input interception; explicit consequences; interrupted holds cannot complete later.                        |

Review compact **360 × 640 logical units**, wide layout, the **960-unit**
breakpoint, **1.5 text scale**, long content and actual OS scaling. Required
controls must remain readable and reachable; crossing layouts preserves route,
draft and focus without sending a communication command. Check keyboard-only
navigation, visible focus, icon names/tooltips, wheel bounds, touch scrolling
where available, and software keyboard insets. Enter sends; Shift+Enter inserts
a newline. No color-only status, clipped mandatory action, accidental double
send or unauthorized clipboard/media action is acceptable. Use the available
native accessibility tool and mixed-DPI displays where present; document what
was actually tested rather than certifying every screen reader or display.

Use only disposable profiles for destructive confirmations. Do not invoke
system-wide process termination or purge the owner's profiles. Test reversible
cancel/hold interruption paths before any accepted synthetic-profile deletion.

Run the documented audio-free simulator:

```text
metor -p acceptance-alice chat --ui gui --simulator --device-config docs/examples/gui-simulator.toml --start-daemon
```

Check the reference configuration, local touch keyboard and declared capability
limits. Make a temporary copy of that configuration to check valid scale and
rotation, including scale 2 and rotation 90. Confirm the resulting geometry and
input agree and no undeclared desktop audio appears. A valid rotated scale-2
example uses `width_px = 1600`, `height_px = 960`, `rotation_deg = 90` and
`scale = 2`, yielding 480 × 800 logical units; merely changing scale on the
original dimensions would violate the minimum usable size. Do not alter the example
merely for a test or claim physical embedded support. Production audio evidence
must come from the ordinary desktop launch, without `--simulator`.

## Fixes, final checks and deliverables

For each failure, record the tested commit, exact steps, expected contract,
observed behavior and bounded relevant evidence. Distinguish product, fixture
and environment causes. Fix the owning module and add a regression only when it
detects meaningful behavior at that boundary. Recheck the failing real scenario.
Do not weaken assertions, silently lengthen deadlines or bypass security to
obtain a pass. In concurrency fixtures, an owned barrier needs explicit release
and failure cleanup; retain framed readers so already-buffered bytes cannot be
lost from assertions.

Run appropriate targeted tests during fixes, then the required static and full
suite for the final code candidate as described in `CONTRIBUTE.md`. The final
required CI matrix must pass on that exact candidate. Revalidate changed package
or native boundaries. For fresh native bundles, the established commands are:

```text
python scripts/build_release_wheelhouse.py --variant all --skip-pip-upgrade --output-dir closure-bundles
python scripts/validate_installed_artifacts.py closure-bundles --gui-smoke
python scripts/validate_release_installers.py closure-bundles
```

On Windows add `--windows-launch` to the installed-artifact validator. Run source
wheel builds sequentially. These deterministic fixtures complement the physical
checks; they do not replace them. A proposed release still needs the canonical
release workflow and its candidate archives; ordinary PR CI is not publication
acceptance.

Update the existing audit report with a clearly dated native follow-up. Include
a table using **Check | PASS/FAIL/BLOCKED | observed evidence | host | commit**.
At minimum distinguish Tor DROP, Tor LIVE, GUI/Terminal/CLI interoperability,
independent frontend lifetime, both Voice directions, device recovery, lock
during recording, lock during playback, accepted call under lock, suspend,
native GUI inspection and simulator configuration. Record test skips as skips,
not passes. Preserve immutable CI/run links and useful synthetic captures; do
not publish passwords, keys, complete profile directories or unreviewed logs.

At completion, close only frontends started for this acceptance (`/exit` in the
Terminal) and verify their autostarted daemon/Tor processes exit after the last
participant. Keep synthetic evidence private while diagnosing failures; do not
delete unrelated processes or data. Supply the final commit/branch or PR,
changes made, concrete results and any remaining blocker. Do not declare a
blanket release-ready result while required native checks or final CI remain
failed or unverified. Main merge, release version selection and publication
remain separate owner actions.
