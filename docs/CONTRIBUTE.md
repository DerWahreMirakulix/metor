# Contributing to Metor

Metor is a highly critical, secure, Tor-based terminal messenger. Code quality, OPSEC, and cryptographic integrity are absolute priorities. There is zero tolerance for bad practices.

When contributing to this repository, you MUST strictly adhere to the following rules:

## Checkout installation

From the repository root, in the Python environment selected for development,
run `python -m pip install -r requirements/dev.txt`, then `python -m pip check`
and `python -m metor chat --list-uis`. This manifest installs SDK, Base, Terminal
and GUI from local editable projects while reusing the pinned third-party
requirements. A plain `pip install .` selects only Base. For Base and SDK without
GUI or Terminal, use the applicable `requirements/base.lock` pins and install
`./packaging/sdk` and `.` together. Independent wheel and installed-consumer
tests remain necessary: editable source imports do not prove wheel ownership.

## Running tests

From the repository root, use the selected development Python after the checkout
installation above (do not install dependencies again for each suite):

```sh
python scripts/run_tests.py --list
python scripts/run_tests.py --suite fast
python scripts/run_tests.py --suite integration
python scripts/run_tests.py --suite all
python scripts/run_tests.py --suite all --match test_profile_storage_security --failfast
python scripts/run_tests.py --suite integration --module test_startup_selection --match test_selection_metadata
python scripts/run_tests.py --suite all --durations 20
```

The runner loads `tests/test_*.py` through the single declarative per-module
manifest in `scripts/test_inventory.py`. The checkout-only CI planner reads the
same inventory without importing test execution or project dependencies.
Classify each new module as fast or integration; missing,
unclassified or multiply classified files fail _before any test module imports_.
Fast imports only fast modules (and their own dependencies); keep fast test
imports independent of integration fixtures. `all` includes every classified
module and is the CI/release gate. `--list` prints **every full unittest ID** in
the selected suite, without executing cases; `--match` filters full IDs by
substring. `--module` selects exact manifest modules before importing tests and
may be repeated; direct `python -m unittest` remains available for one-case
diagnosis. Empty selections, import failures, duplicate IDs and unexpected
case modules fail closed. For failures, the console and ignored
`build/test-report.txt` contain bounded IDs, phase, known-safe error category
and source-verified relative locations. A known SDK rejection includes only its
verified `EventType` outcome; unknown exception names remain generic. Failure
and skip diagnostics have separate budgets, with omitted counts shown. Exception
values, subtest parameters, locals and captured output are never printed. The
report lists each executed case's status and setup-to-cleanup runtime; fixture
skips count as skipped coverage, while failed fixtures and interrupted runs leave
untested cases incomplete. XFAIL and XPASS appear separately, and XPASS fails the run. The
script supervises its test worker with a one-hour whole-worker guard, bounded
stdout and stderr pipes, and a fresh completion record tied to the bounded
report. On Linux, the serialized runner owns a subreaper scope and refuses to
start beside an existing child; on Windows, it assigns the suspended worker to
a Job Object before resuming it. Live test children or unconfirmed cleanup fail
the run, as do timeout, excess output, unexpected stderr, report failure and
abrupt exit. The runner process must not start unrelated children concurrently
with its supervised worker. A verified running test ID is retained for an
aborted worker when available. Raw stderr is withheld; test and child-process
output during test execution is discarded.
The console shows only the requested number of slow cases. Class/module fixture
costs remain in overall elapsed time, not attributed to an individual case.

Optional coverage requires `coverage.py` already installed in the same Python
environment; the pinned development manifest does not install it. Run
`python scripts/run_tests.py --suite all --coverage` to emit a terminal summary
for `metor` and save detailed data in ignored `build/.coverage`. CI does
not install coverage or claim a coverage threshold. PR merge refs, `main`
pushes, and manually dispatched CI runs execute the full Linux/Windows ×
Python 3.11/3.13 software matrix. A push to `embeddedui` uses `scripts/ci_impact.py`
to run Fast and explicitly selected integration modules on Linux 3.11 only for
known isolated edits. Fast selection requires a verified two-commit diff with
only regular-file content modifications on recognized paths. Renames, additions,
deletions, type changes, missing refs, shared, security-sensitive, packaging,
workflow, unknown or unresolvable diffs fall back to the full matrix. The
glossary is treated as text-only; README installation examples, profile
lifecycle views, executable examples and packaged resources use the full path.
The final `acceptance` job requires all planned matrix jobs to pass.
Run the CI workflow manually on the desired branch/ref for full branch
acceptance without a PR; a Fast branch push is not a full release gate. The
release quality gate still runs all tests. CI cancels superseded runs per
branch/PR; branch commits and PR merge refs are separate candidates. Explicit
native GUI and stream fixtures remain separate from unittest discovery; the
runner does not replace installed-consumer, Tor, or physical-device acceptance.

## 1. Language & Naming

- **English Only:** All code, variables, comments, commit messages, and docstrings MUST be written in English.
- **Naming Conventions:** Use `snake_case` for variables/functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- **Private Methods:** Prefix internal class methods and properties with an underscore (e.g., `def _load(self):`).

## 2. Typing & Signatures

- **Strict & Explicit Typing:** Every function, method, and variable MUST have strict Python type hints. Never use bare types like `List` or `Tuple` -> always define their generic payload (e.g., `List[Tuple[str, int, bool]]`).
- **Return Types:** Every function MUST declare a return type (use `-> None` if it returns nothing).

## 3. Documentation (Docstrings)

- **Module Headers:** Every Python file MUST start with a top-level module docstring (triple double quotes `"""`) explaining the purpose of the file.
- **Google Style:** Use Google-style docstrings for every class and method.
- **Meaningful Descriptions:** Explain _what_ the function does and _why_.
- **Input/Output (STRICT):** Every method docstring MUST have an `Args:` and `Returns:` block. If a function takes no arguments, write `Args:\n    None`. If it returns nothing, write `Returns:\n    None`.
- **Comments:** Keep comments strictly objective. No conversational filler, no changelog notes. Write comments for a production codebase. Don't remove comments which fulfill a purpose (e.g. guiding auto completion models or agents).

## 4. Architecture & Design Principles

- **State ownership & IPC:** Frontends may retain interaction/presentation state. Transport, durable delivery, cryptographic lifecycle and authorization truth belong to the daemon. Frontends MUST NOT access databases, Tor, keys or profile runtime files; use typed DTOs and the public narrow host/settings services.
- **Configuration Cascade:** Metor uses a strict configuration hierarchy. Global settings apply to all profiles. Profile-specific overrides apply only locally. Maintain the boundary between client-side configs (`ui.*`) and server-side configs (`daemon.*`).
- **No Magic Numbers:** Do not use raw numeric or string literals for system parameters (e.g., `10.0`, `4096`). Define them as constants in a centralized utility file or as user-configurable settings. This applies globally to timeouts, buffer limits, retry counts, etc.
- **Import Architecture (Facade Pattern & PEP 420 Namespaces):** Metor uses PEP 420 namespace packages at the root (`metor`) and core (`metor.core`) levels so `metor-sdk`, `metor`, and `metor-ui-terminal` can own disjoint files in one namespace. Namespace directories do not have an `__init__.py`. The SDK owns `metor.client`, `metor.core.api`, proof helpers, and lightweight shared helpers; base owns `metor.cli`, application/daemon/storage/Tor code; Terminal owns only `metor.ui.terminal`. Base and SDK MUST NOT import a frontend implementation. Frontends launch only through the versioned `metor.client` contract and MUST NOT access storage or transport internals. When importing from an _external_ or _parent_ functional domain, use that package's public `__init__.py` Facade. Core transport and key modules are imported directly from their respective domain modules (`metor.core.key`, `metor.core.tor`). Use `metor.core.daemon` only for daemon-shared bootstrap helpers, `metor.core.daemon.managed` for the full managed runtime facade plus managed-only subpackages, and `metor.core.daemon.headless` for the ephemeral offline runtime facade. The shared handler facade `metor.core.daemon.handlers` is limited to config/system/db handlers, while managed-only transport handlers belong under `metor.core.daemon.managed.handlers`. Importing implementation files such as `metor.core.daemon.managed.engine`, `metor.core.daemon.managed.bootstrap`, `metor.core.daemon.managed.factory`, `metor.core.daemon.managed.local_auth`, or `metor.core.daemon.headless.manager` from outside the package boundary is forbidden. When importing from a sibling module within the _same_ domain/directory (horizontal imports), explicitly bypass the Facade and import directly from the file to prevent circular dependencies.
- **Context Managers:** Always use `with` statements for file operations, databases, sockets, and locks to ensure proper resource cleanup.
- **Modern Path Handling:** Use Python's `pathlib.Path` strictly over the legacy `os.path` module for all filesystem operations.

## 5. Security & Network Protocols (CRITICAL)

- **TCP Stream Framing:** Never assume `socket.recv()` returns a complete protocol frame or message. Always implement line-buffering or length-prefixing to safely reconstruct stream fragments.
- **Cryptography:** Never use `os.urandom` or `random` for key generation; exclusively use a cryptographically secure module (like `secrets`).
- **Data-at-Rest (SQL Integrity):** Always use parameterized queries (`?`) for user data operations. Because SQL engines (like SQLite) do not support parameterization for structural commands (like `PRAGMA` or table names), f-strings may only be used there if the injected value is deeply sanitized, mathematically escaped, or a strict system constant. Under no circumstances may raw user input be formatted directly into an SQL string.

## 6. Module Cohesion & Size

- **One Primary Responsibility:** Every production module MUST have one cohesive primary responsibility. God Modules that mix unrelated orchestration, persistence, crypto, validation, migration, recovery, or filesystem concerns are prohibited.
- **Size as a Guardrail:** Prefer modules below approximately 400 logical lines. Line count alone is never a reason for artificial splitting: extraction boundaries MUST represent real architectural or domain boundaries.
- **Mandatory Review:** When substantial functionality is added to a production module already above approximately 500 logical lines, contributors MUST proactively evaluate and document a cohesive extraction. Modules above approximately 800 logical lines are unacceptable except for clearly justified generated or declarative exceptional files.
- **Thin Facades:** Package facades expose intended public symbols only; they MUST remain thin and MUST NOT accumulate implementation behavior.
- **Oversized Modules:** Substantially modifying an already oversized module requires proactive decomposition review, even when the requested feature itself is small.

### Package Structure & Subsystem Boundaries

- **Packages Represent Subsystems:** When a cohesive feature or domain grows into multiple implementation modules, group those modules in a dedicated subpackage instead of adding prefixed siblings to a broad parent package.
- **Package Promotion:** If two or more closely related modules share one domain concept and are expected to evolve together, contributors MUST evaluate promoting that concept to a subpackage. Three or more `<concept>_*.py` siblings are a strong signal for promotion, not an automatic rule.
- **Avoid Flat Module Sprawl:** For one migration subsystem, `migration.py`, `migration_journal.py`, `migration_validation.py`, and `migration_blobs.py` should normally become `migration/orchestrator.py`, `migration/journal.py`, `migration/validation.py`, and `migration/blobs.py`.
- **Name by Local Ownership:** Inside a focused package, avoid repeating package context: prefer `migration/journal.py` over `migration/migration_journal.py` unless repetition is genuinely needed for clarity.
- **Thin Package Facades:** A package `__init__.py` may expose the intentional subsystem API, but MUST remain free of implementation and orchestration behavior.
- **Private Names Have Meaning:** A leading underscore denotes genuine implementation privacy. Do not alias ordinary cross-module or facade imports to underscore-prefixed names merely to make them appear internal.
- **No Generic Extraction Buckets:** Do not use vague modules such as `helpers.py`, `misc.py`, or `common.py` to satisfy size rules. Each extraction must name a stable, concrete responsibility.
- **Meaningful Depth:** One additional meaningful subsystem directory is preferable to a broad flat directory of prefixed sibling modules. Do not introduce arbitrary nesting.

## 7. Code Formatting (Ruff)

- **Imports First:** All `import` statements MUST (unless a runtime import is absolutely necessary) be located at the very top of the file (immediately following the module docstring).
- **Import Delimiters:** Standard library and external domain imports MUST be separated from same-domain internal imports using exactly the `# Local Package Imports` comment. This comment MUST NOT be placed above imports from higher-level Metor domains.
- **Single Quotes:** Always use single quotes (`'`) for strings unless the string itself contains a single quote. Double quotes are strictly for docstrings (`"""`).

## 8. IPC Contract Evolution & Glossary

The IPC contract is versioned and additive-only within one IPC protocol generation. Follow these rules whenever the wire contract changes:

- **Additive-Only Within an IPC Generation:** New commands, events, and payload fields are allowed, but every new field MUST have a default so writers from older versions stay valid. Removing or renaming a field, event, or command requires an incompatible IPC protocol generation bump.
- **No Aliases:** Renamed symbols are never kept as aliases or compatibility shims; every caller migrates in the same release.
- **Independent Versions:** Application releases and compatibility generations are independent. Version values come only from `src/metor/versioning/__init__.py`; application SemVer changes during releases, while compatibility-breaking changes require an explicit, semantically reviewed axis bump. Keep each `*_MIN_SUPPORTED` claim honest and never reuse or automatically bump a retired wire or storage value. Follow [RELEASING.md](./RELEASING.md).
- **Unknown Fields Stay Strict:** Payloads with unknown fields are rejected, never silently ignored. Drift is surfaced as the typed `ProtocolMismatchEvent` via the `InitCommand`/`InitEvent` handshake.
- **Generated References:** Every command/event DTO must be registered through `register_command` / `register_event` so `scripts/generate_api_docs.py` picks it up. Never hand-edit the generated [API.md](./generated/API.md) or [api.schema.json](./generated/api.schema.json).
- **Glossary Obligation:** New or renamed symbols (settings keys, events, enums, fields, IPC payloads) MUST follow the canonical terminology in [GLOSSARY.md](./GLOSSARY.md). When in doubt, extend that file instead of inventing a parallel term. Settings keys MUST use one of the three namespaces (`client.*`, `daemon.*`, `ui.<frontend>.*`) documented there.

## 9. Documentation Ownership

The root `README.md` is the human entry point and root `AGENTS.md` routes coding
agents to the canonical `docs/AGENTS.md`; do not create `docs/README.md`. Global canonical docs
stay at `docs/` root, while governance, contracts, generated references, and
lasting historical audits belong to their named ownership directories. Every
new document must have one of those ownership classes; temporary agent reports
do not automatically become canonical documentation.

Files under `docs/generated/` are valuable, first-class references whose source
ownership is code and generators. Never edit them manually: update the source
definition or generator, regenerate, and commit the result. Authored documents
should link readers to deeper generated references instead of duplicating them,
and relevant links must remain reachable from the existing human or agent entry
point.

## 10. Security and Architecture Review

Every change is reviewed against the risks it can actually affect. Record the
relevant checks and evidence; do not claim a platform, hardware, or destructive
path that was not exercised. Use the reusable
[audit checklist](./governance/AUDIT.md) to select relevant checks and record
their results with the PR or release evidence.

### Ownership and isolation

- Frontends access Core through typed IPC and the narrow public host/settings and
  platform contracts. They never read SQL, Tor state, keys, or profile runtime
  files directly.
- Daemon DTOs carry domain codes and structured data, not preformatted UI text.
- Client and `ui.*` settings remain local; `daemon.*` settings are routed to the
  daemon host. Genuinely shared behavior has one explicit owner.
- New platform adapters keep observation, ordered input, and controlling actions
  separate. Hardware input or actuator success never grants Core authorization.

### Cryptography, credentials, and retention

- Generate seeds, UUIDs, nonces, and tokens with cryptographically secure
  primitives; never use `random` for security material.
- Validate signatures and challenge-response proofs without timing-sensitive
  comparisons or replayable authorization.
- Passwords derive only the KEK that unwraps a random PMK. Keyslot permissions
  and sensitive directories remain owner-only where supported.
- Lock clears runtime key references; purge destroys protected PMK access before
  best-effort file cleanup. Never describe software overwrite as guaranteed
  physical erasure.
- Apply explicit read/release and retention rules. A placeholder, download,
  delivery ACK, or UI observation is not proof that content was read or safely
  consumed.

### Network, IPC, and resource safety

- Reassemble TCP/IPC streams with their declared framing. One `recv()` is never
  assumed to contain one complete frame.
- Bound frames, queues, callbacks, connections, buffers, retries, and timeouts.
  Saturation and loss are explicit outcomes rather than silent drops or
  unbounded growth.
- Serialize socket writers, keep physical I/O outside canonical state locks, and
  ensure stale callbacks cannot tear down a replacement generation.
- Treat request correlation as routing, not authorization. Revalidate exact
  identity, generation, scope, and eligibility at mutation time.

### Concurrency and process lifecycle

- Protect shared iteration and mutation with the owning lock and preserve the
  documented lock order across domain, state, store, and writer boundaries.
- Cross-process file locks must survive crashed owners safely. Spawned Tor and
  managed child processes must be tracked and terminated on failed startup or
  shutdown.
- Isolate optional callback and malformed-input failures while keeping release,
  authorization, persistence, and cleanup failures observable.
- Test races at enclosing production boundaries: reconnect replacement, unknown
  operation outcome, owner loss, finalization, restriction, profile switch, and
  purge fencing.

### Persistence and local data

- Parameterize all SQL data values. Structural SQL may interpolate only strict
  constants or mathematically constructed placeholders, never raw user input.
- Keep secrets short-lived and remove payloads, credentials, keys, and peer
  identities from exceptions and logs.
- Preserve the random PMK and domain-separated DB, secret, and blob keys. A
  future `KeyProtector` must remain replaceable without changing consumers.
- Blob IDs remain opaque and path-independent; formats are versioned and
  authenticated; temporary and persistent ownership is explicit.
- Test partial transactions, staged migration recovery, commit uncertainty, and
  cleanup failure without deleting the only recoverable copy.

### Versioning and release integrity

- All application and compatibility values come from
  `src/metor/versioning/__init__.py`.
- SQL, IPC, peer, keyslot, blob, and derivation changes receive the semantic
  review and version treatment described in [RELEASING.md](./RELEASING.md).
  Additive defaulted fields do not justify an automatic generation bump;
  incompatible changes do.
- `*_MIN_SUPPORTED` claims require actual reader/negotiation coverage. Application
  SemVer changes only in the explicit release process.
- Regenerate and validate code-owned API, settings, schema, and compatibility
  references through their generators. Never edit `docs/generated/*` manually.

### Documentation and evidence

- Update the one owning document for each rule and repair every path consumer.
  Put GUI operation, behavior, device configuration, and visual rules in
  `docs/contracts/GUI.md`; shared frontend contracts belong in
  `docs/contracts/FRONTENDS.md`. Record dated acceptance results with the
  relevant release evidence, not in a maintained project-status database.
- Preserve stable requirement/test identifiers when they remain useful. Remove
  implementation diaries and copied run counts from maintained explanations.
- Verify local links and anchors, JSON/schema consumers, generated-reference
  determinism, and any packaging/resource relocation. Build installed consumers
  outside the checkout when package contents change.
- Evidence must state revision, platform/capability, scope, result, and durable
  reference. Mock, offscreen, or typed-adapter evidence is never promoted to
  native, acoustic, accessibility-product, or appliance acceptance.

## 11. Native GUI Acceptance Gates

Native media and OS-lifecycle acceptance is capability-selected and separately
authorized. Never encode a headset brand, GPU, board model, or developer-machine
path as a requirement.
Use a fresh installed GUI outside the checkout for an installed gate, record the
exact source/artifact revision, and keep microphone bytes and temporary profiles
out of durable artifacts.

After building the current wheelhouse, run the installed consumer validator to
exercise the independent SDK, Base, Terminal and GUI consumers. It also creates
a fresh SDK + Base + Terminal environment without GUI or audio frontend packages
and checks Terminal discovery and a Voice metadata path:

```sh
python scripts/validate_installed_artifacts.py dist/release
```

The optional installed GUI start-and-close smoke uses the same validator with
`--gui-smoke` and requires a working native display provider. On Linux CI, run
it with the generic X11/SDL2 software display used by the workflow; an EGL/GLX
failure leaves this native gate open.

Enumerate audio endpoints without opening a stream:

```sh
python tests/gui_native_voice.py --mode source --list-devices
```

After an operator explicitly selects compatible input/output endpoints and
confirms a headset route, run the full GUI/Core duplex gate:

```sh
python tests/gui_native_voice.py \
  --mode source \
  --input-device INPUT_INDEX \
  --output-device OUTPUT_INDEX \
  --headset-confirmed \
  --revision COMMIT_OR_TREE \
  --result native-gui-voice.json
```

For installed acceptance, invoke the script from outside the checkout with the
wheel-installed interpreter and `--mode installed`; the harness rejects a GUI
loaded from the checkout. `tests/gui_native_audio.py` is the narrower PortAudio
diagnostic and does not replace the full GUI/Core gate.

On a supported installed Linux desktop, observe real provider events while an
operator performs only the authorized actions:

```sh
python tests/gui_native_lifecycle.py --expect lock,suspend,resume
```

The acceptance run must also verify the enclosing GUI privacy/media behavior:
private accessibility/tooltips are revoked before cover, capture and playback
stop safely, held input requires release, resume stays covered, and no input,
microphone, playback, or unlock is reconstructed. Windows acceptance exercises
the corresponding installed WTS Lock/Unlock and power suspend/resume path on an
actual native session. Structural/unit message tests are necessary but do not
replace either native run.

A release dry run is a separate owner-authorized procedure under
[RELEASING.md](./RELEASING.md). Preserve genuine revision-qualified evidence
with the release record; update the GUI contract only when supported behavior
or capability changes.
