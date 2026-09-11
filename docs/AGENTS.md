# Metor AI Agent Instructions

You are acting as a Senior Python Software Engineer and Cybersecurity Architect working on the "Metor" project.
Metor is a highly secure, Tor-based terminal messenger using a strict Client-Daemon architecture. Security, anonymity, and architectural integrity are non-negotiable.

## 1. Core Directives & Architecture

- **Read the Guidelines:** Before writing or modifying code, read and enforce [CONTRIBUTE.md](./CONTRIBUTE.md), then load only the additional task-specific references routed below.
- **State ownership:** Frontends own presentation and interaction state, not transport, durable delivery, cryptographic lifecycle or authorization truth. Never access SQL, Tor keys or host-profile files from a frontend. Use typed IPC and the narrow public frontend host/settings boundary.
- **No Magic Numbers:** You MUST NEVER hardcode timeouts, buffer sizes, or retry limits. Always use the centralized `Constants`, `Settings`, or `Config` classes.
- **Parsing:** Base human-input adapters use `metor.utils.TypeCaster` where appropriate. SDK/wire code uses strict SDK-owned validation, never a base dependency or permissive user-input coercion.
- **Security First:** Treat every network socket, file read, and database query as a potential attack vector. Always use parameterized SQL queries and handle partial TCP stream fragments safely.
- **No Conversational Filler:** When generating code, do not include self-referential remarks in comments (e.g., absolutely no "NEW:", "As requested:", "Fixed the bug here"). Write comments for a production codebase.

## 2. Bounded maintenance

- **Scope:** Routine local cleanup is allowed. The owner's explicit task takes precedence over opportunistic refactoring; do not silently expand it.
- **Ownership rationale:** Package-boundary changes, new abstractions and substantial extractions require a short ownership and compatibility rationale in the implementation report or canonical architecture decision.
- **God-File Prevention:** Proactively enforce the canonical Module Cohesion & Size policy in [CONTRIBUTE.md](./CONTRIBUTE.md): do not add substantial behavior to an oversized production module without evaluating a cohesive, domain-boundary extraction.
- **Package-Structure Enforcement:** God-File extraction MUST preserve or improve subsystem ownership. Do not solve file-size problems by creating flat `<concept>_*.py` siblings; promote cohesive multi-module concepts into dedicated subpackages according to [CONTRIBUTE.md](./CONTRIBUTE.md).

## 3. Reference Material

Load the minimum relevant context for the task:

- General code changes: [CONTRIBUTE.md](./CONTRIBUTE.md).
- Architecture changes: [CONTRIBUTE.md](./CONTRIBUTE.md) and [ARCHITECTURE.md](./ARCHITECTURE.md).
- IPC/API work: the IPC sections of [ARCHITECTURE.md](./ARCHITECTURE.md), generated [API.md](./generated/API.md), and [api.schema.json](./generated/api.schema.json).
- Settings work: generated [SETTINGS.md](./generated/SETTINGS.md), [GLOSSARY.md](./GLOSSARY.md), and the settings implementation.
- Release/versioning work: [RELEASING.md](./RELEASING.md), `src/metor/versioning/__init__.py`, and generated [compatibility.json](./generated/compatibility.json) where relevant.
- Embedded UI work: [EMBEDDED_UI.md](./contracts/EMBEDDED_UI.md).
- Security, persistence, concurrency, or audit work: [AUDIT.md](./governance/AUDIT.md).

For work affecting release automation, packaging, version values, wire
contracts, database schemas, keyslot/blob persistence, cryptographic derivation,
or compatibility, inspect `src/metor/versioning/__init__.py` and [RELEASING.md](./RELEASING.md),
then determine whether an explicit compatibility-axis bump is required. Never
automatically bump a compatibility generation.

## 4. Documentation Changes

Before creating a document, determine its ownership class and check whether an
existing canonical document should be extended. Never edit
`docs/generated/*` manually; update its source or generator and regenerate it.
Route durable documentation through the existing README or AGENTS entry point,
preserve useful cross-links, and update scripts and workflows whenever generated
paths move. Do not leave temporary reports at `docs/` root, and do not create
`docs/README.md`.
