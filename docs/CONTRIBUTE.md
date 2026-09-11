# Contributing to Metor

Metor is a highly critical, secure, Tor-based terminal messenger. Code quality, OPSEC, and cryptographic integrity are absolute priorities. There is zero tolerance for bad practices.

When contributing to this repository, you MUST strictly adhere to the following rules:

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

- **Domain-Driven Design (DDD) & IPC:** The UI (Client) is strictly stateless. It MUST NEVER access the database, Tor network, or cryptographic keys directly. All communication with the Core (Daemon) MUST happen via strictly typed Data Transfer Objects (DTOs).
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
- **Independent Versions:** Application releases and compatibility generations are independent. Version values come only from `src/metor/versioning.py`; application SemVer changes during releases, while compatibility-breaking changes require an explicit, semantically reviewed axis bump. Keep each `*_MIN_SUPPORTED` claim honest and never reuse or automatically bump a retired wire or storage value. Follow [RELEASING.md](./RELEASING.md).
- **Unknown Fields Stay Strict:** Payloads with unknown fields are rejected, never silently ignored. Drift is surfaced as the typed `ProtocolMismatchEvent` via the `InitCommand`/`InitEvent` handshake.
- **Generated References:** Every command/event DTO must be registered through `register_command` / `register_event` so `scripts/generate_api_docs.py` picks it up. Never hand-edit the generated [API.md](./generated/API.md) or [api.schema.json](./generated/api.schema.json).
- **Glossary Obligation:** New or renamed symbols (settings keys, events, enums, fields, IPC payloads) MUST follow the canonical terminology in [GLOSSARY.md](./GLOSSARY.md). When in doubt, extend that file instead of inventing a parallel term. Settings keys MUST use one of the three namespaces (`client.*`, `daemon.*`, `ui.<frontend>.*`) documented there.

## 9. Documentation Ownership

The root `README.md` is the human entry point and `docs/AGENTS.md` is the
coding-agent entry point; do not create `docs/README.md`. Global canonical docs
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
