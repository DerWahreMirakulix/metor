# Production Module Cohesion Inventory

This is the pre-refactor inventory for the architectural-sanitization pass.
Logical LOC excludes blank lines and comment-only lines. A module is listed when
it is approximately 400 logical LOC or has a concentrated set of responsibilities
that merits review; the listing is not a defect finding based on size alone.

## Prioritization

1. `data/profile/lifecycle.py` — genuine security-sensitive migration and
   lifecycle God File; refactored in this pass.
2. `core/daemon/managed/engine.py` — genuine daemon lifecycle, IPC dispatch,
   authentication, and runtime-ownership God File; requires a separately scoped
   daemon-lifecycle extraction because it coordinates the running process.
3. `data/settings.py` — genuine schema, validation, persistence, and snapshot
   adaptation God File; split its registry/schema from persistence before adding
   settings behavior.
4. `core/daemon/managed/network/router.py` — transport routing candidate; first
   establish whether live and drop routing can be independently owned without
   changing delivery semantics.

## Inventory

| Path                                                          |        Logical LOC | Classes / major top-level functions                                          | Responsibilities and role                                                                                        | Finding / recommended action                                                                                                                                                                    |
| ------------------------------------------------------------- | -----------------: | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `core/api/__init__.py`                                        |                408 | facade exports                                                               | Public API facade                                                                                                | Long declarative export surface, not a God File. Keep thin; do not move behavior into it.                                                                                                       |
| `core/daemon/managed/engine.py`                               |              1,005 | `DaemonLifecycle`, `Daemon`                                                  | Daemon lifecycle, runtime ownership, IPC dispatch, local authentication, session consumers, shutdown/destruction | Genuine God File: independent state machines and resource owners coexist. Extract lifecycle/runtime ownership and IPC/auth dispatch behind the existing managed facade.                         |
| `core/daemon/managed/handlers/network.py`                     |                581 | `NetworkCommandHandler`                                                      | Network command adaptation to managed runtime                                                                    | Long command handler with a single adapter role. Keep under review; split only by stable command subdomain.                                                                                     |
| `core/daemon/managed/network/controller/session/terminate.py` |                619 | `reject`, `disconnect`, recovery helpers                                     | Session termination and deferred fallback recovery                                                               | Cohesive session-termination implementation despite several helpers. Keep together unless recovery policy becomes independently reusable.                                                       |
| `core/daemon/managed/network/listener.py`                     |                690 | `InboundListener`                                                            | Inbound accept, handshake, policy, connection registration                                                       | Long but cohesive inbound transport boundary. Review when new protocol phases are added.                                                                                                        |
| `core/daemon/managed/network/receiver.py`                     |                428 | `StreamReceiver`                                                             | Receive framing, decode, and dispatch                                                                            | Cohesive stream receiver. No action.                                                                                                                                                            |
| `core/daemon/managed/network/router.py`                       |                828 | `MessageRouter`                                                              | Live/drop routing, delivery persistence, receipt and fallback decisions                                          | High-risk candidate: separate delivery mechanisms and persistence decisions share one router. Evaluate live/drop strategy extraction before further growth.                                     |
| `core/daemon/managed/network/state/connections.py`            |                602 | `PendingConnectionSnapshot`, `StateTrackerConnectionsMixin`, `_close_socket` | Connection-state mutation and socket cleanup                                                                     | Cohesive state subdomain, but the mixin has many state concerns. Split snapshots or cleanup only if a real ownership boundary emerges.                                                          |
| `core/daemon/managed/outbox.py`                               |                682 | `OutboxWorker`                                                               | Queued outbound delivery worker                                                                                  | Cohesive worker lifecycle and retry behavior. Keep together while it owns one queue worker.                                                                                                     |
| `core/profile_keys.py`                                        |                460 | key protector protocol, keyset, password protector                           | PMK derivation and password keyslot protection                                                                   | Security-sensitive but cohesive key-protection boundary. No split.                                                                                                                              |
| `core/tor.py`                                                 |                512 | `TorManager`                                                                 | Tor process lifecycle and control                                                                                | Cohesive external-process owner. No split.                                                                                                                                                      |
| `data/blob/store.py`                                          |                589 | blob protocol, encrypted/plaintext stores and errors                         | Versioned encrypted/blob storage implementations                                                                 | Cohesive storage domain; two implementation classes share one protocol. No split.                                                                                                               |
| `data/contact/manager.py`                                     |                419 | `ContactManager`                                                             | Contact persistence operations                                                                                   | Cohesive repository/manager. No action.                                                                                                                                                         |
| `data/profile/config.py`                                      |                670 | `Config`                                                                     | Profile config IO, overrides, integrity, validation                                                              | Long profile-configuration boundary. Consider separating file persistence from effective-value resolution only when changing either substantially.                                              |
| `data/profile/lifecycle.py`                                   | 852 (pre-refactor) | lifecycle API, migration/recovery/blob/journal helpers                       | Creation, removal, renaming, DB clear, purge plus staged security migration                                      | Genuine God File: user lifecycle API mixed with migration state machine, durable recovery, filesystem sync, DB conversion, keyslot transformation, blob conversion, and validation. Refactored. |
| `data/profile/manager.py`                                     |                412 | `ProfileManager`                                                             | Profile runtime metadata, paths, integrity and lifecycle facade methods                                          | Mostly cohesive profile aggregate facade. Keep facade methods delegating only.                                                                                                                  |
| `data/settings.py`                                            |              1,054 | settings DTO/types, enum, schema, `Settings`                                 | Setting registry, validation, JSON persistence, namespace handling, UI snapshots                                 | Genuine God File: declarative schema and independent persistence/presentation responsibilities are mixed. Extract a schema/registry module before further settings work.                        |
| `data/sql/message.py`                                         |                648 | `MessageReceiptRow`, `MessageRepository`                                     | Message persistence, queries, receipts, cleanup                                                                  | Cohesive repository. Split by established storage aggregate only if query/write concerns diverge.                                                                                               |
| `ui/embedded/fakes.py`                                        |                460 | ten fake platform ports                                                      | Test/demonstration platform implementations                                                                      | Declarative fake adapter collection, not a production God File. Retain as a grouped fake platform.                                                                                              |
| `ui/terminal/chat/engine.py`                                  |                590 | `Chat`                                                                       | Terminal chat orchestration                                                                                      | Large UI orchestrator. Defer until terminal UX work; extract event/session presentation only along current package boundaries.                                                                  |
| `ui/terminal/chat/event/transport.py`                         |                531 | transport event handler and focused helpers                                  | Terminal transport event rendering and buffered-send behavior                                                    | Cohesive event-domain module. Keep together unless buffering is reused independently.                                                                                                           |
| `ui/terminal/chat/renderer/engine.py`                         |                547 | `Renderer`                                                                   | Terminal rendering lifecycle and widgets                                                                         | Cohesive renderer. No action.                                                                                                                                                                   |
| `ui/terminal/cli/handlers.py`                                 |                526 | `CommandHandlers`, prompt helpers                                            | CLI command decisions and credential prompts                                                                     | Candidate only: command adaptation is a single role. Split by command family only when independent behavior grows.                                                                              |
| `ui/terminal/cli/proxy/core.py`                               |                611 | `CliProxy`                                                                   | CLI-to-IPC request facade                                                                                        | Long facade, but public proxy role is cohesive. Keep it behavior-free beyond request adaptation; move domain-specific formatting to existing proxy modules.                                     |
| `ui/terminal/cli/proxy/settings.py`                           |                471 | `CliProxySettingsActions`                                                    | Settings request adaptation and snapshot formatting                                                              | Cohesive settings proxy. No action.                                                                                                                                                             |
| `ui/terminal/help.py`                                         |                470 | command definitions, `Help`                                                  | Declarative command help registry and rendering                                                                  | Primarily declarative registry; not a God File.                                                                                                                                                 |
| `ui/terminal/translations.py`                                 |                645 | `Translator`                                                                 | Terminal translation catalog and lookup                                                                          | Declarative localization catalog. Not a God File.                                                                                                                                               |
| `utils/release_bundle.py`                                     |                434 | bundle build functions, CLI `main`                                           | Release bundle construction script                                                                               | Tooling, not production runtime. Keep task-oriented functions grouped.                                                                                                                          |

## Refactor Result

`data/profile/lifecycle.py` is now a small public lifecycle facade. The migration
subsystem is organized by stable responsibility:

```text
data/profile/
├── lifecycle.py           public profile operations and compatibility seam
└── migration/             profile storage security migration subsystem
    ├── __init__.py        thin public subsystem facade
    ├── orchestrator.py    staged migration state-machine orchestration
    ├── blobs.py           blob conversion and DB-reference validation
    └── journal.py         durable journal, fsync, and crash recovery
```

The existing `ProfileManager` methods and lifecycle import boundary are unchanged.
The deterministic checkpoint is internal to `migration.orchestrator` and is
passed to collaborating migration modules, preserving test fault injection
without distorting the public lifecycle facade. Blob stores and temporary
database connections retain explicit `finally` cleanup; journal ownership remains
in the recovery service.

## Flat-Module Cluster Follow-Up

The profile migration cluster was the only clear flat-prefix violation created by
the prior sanitization pass, and is now a subsystem package. The remaining
clusters were reviewed without churn:

- `core/daemon/managed/network/controller/session/` already owns session
  connection responsibilities as a coherent subpackage.
- `core/daemon/managed/network/state/`, `ui/terminal/chat/event/`, and
  `ui/terminal/chat/renderer/` already express their subsystem ownership through
  shallow packages.
- `ui/terminal/cli/proxy/` is an existing CLI request-adaptation subsystem; its
  `core`, `profiles`, `settings`, `transport`, and rendering modules do not use
  redundant parent-level prefixes.
- `data/sql/` groups storage repositories by aggregate rather than accumulating
  `<concept>_*.py` siblings. No promotion is indicated.

No additional cluster met both the shared-ownership and likely-to-evolve-together
tests strongly enough to justify a structural move in this pass.

## Test Inventory

`tests/test_profile_storage_security.py` is a large scenario-style integration
module because it exercises encrypted/plaintext creation, migration, corruption,
fault injection, blob integrity, and recovery together. Its scenarios share the
profile-storage security boundary, so it was not split solely for line count.

## Automated Guardrail Decision

No size-check script was added in this pass. A hard 800-LOC check would fail on
the documented pre-existing candidates, while a warning-only script would not
provide stronger enforcement than the new canonical contributor and audit rules.
Introduce a check with an explicit reviewed baseline/allowlist after the daemon
engine and settings registry extractions; it should warn at approximately 400 and
fail at 800 only for modules outside that reviewed baseline.
