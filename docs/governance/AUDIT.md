# Security and Architecture Audit Checklist

Use this checklist for a change or release review. Select the checks that match
the affected risks and record their result and evidence in the PR or release
record. For each selected check, record **pass**, **not applicable** with a
reason, or **open** with an owner. Leave this reusable template unchecked.

Review record: revision, scope, platform/capability, results, evidence links,
and open risks. Follow the authoritative [contribution and review rules](../CONTRIBUTE.md);
use the [architecture guide](../ARCHITECTURE.md) and
[release policy](../RELEASING.md) for their respective decisions. Evidence must
describe what was actually exercised.

## 1. Ownership and architecture

See the [architecture guide](../ARCHITECTURE.md) and
[frontend contract](../contracts/FRONTENDS.md).

- [ ] Frontends use typed IPC and public host/settings/platform contracts; they
      never read SQL, Tor state, keys, or profile runtime files directly.
- [ ] Daemon DTOs carry domain codes and structured data instead of rendered UI
      text.
- [ ] `client.*` and `ui.*` settings stay local; `daemon.*` settings reach the
      daemon host, and shared behavior has one explicit owner.
- [ ] Platform observation, ordered input, and controlling actions remain
      separate; device success does not grant Core authorization.

## 2. Cryptography and retention

See [security and architecture review](../CONTRIBUTE.md#10-security-and-architecture-review).

- [ ] Seeds, UUIDs, nonces, and tokens use cryptographically secure generation.
- [ ] Signatures and challenge-response proofs resist timing leaks and replay.
- [ ] Passwords derive only the KEK for a random PMK; keyslots and sensitive
      directories have owner-only permissions where supported.
- [ ] Lock clears runtime key references; purge destroys protected PMK access
      before best-effort file cleanup, and retention claims avoid a physical
      erasure guarantee.

## 3. Network, IPC, and resource limits

See the [IPC architecture](../ARCHITECTURE.md) and
[review rules](../CONTRIBUTE.md#network-ipc-and-resource-safety).

- [ ] TCP and IPC readers reassemble declared frames across partial reads.
- [ ] Frames, queues, callbacks, connections, and buffers have enforced bounds;
      saturation or loss has an explicit outcome.
- [ ] Buffer sizes, retries, timeouts, and other system limits use owned
      constants or settings rather than unexplained literals.
- [ ] Socket and IPC operations have bounded timeouts and cleanup paths.

## 4. Concurrency and process lifecycle

See the [review rules](../CONTRIBUTE.md#concurrency-and-process-lifecycle).

- [ ] Shared iteration and mutation use the owning lock and documented lock
      order; physical I/O stays outside canonical state locks.
- [ ] Cross-process file locks handle crashed owners without leaving a false
      claim of exclusive ownership.
- [ ] Spawned Tor and managed children are tracked and terminated on failed
      startup and shutdown.
- [ ] Optional callbacks and malformed input are isolated while authorization,
      persistence, release, and cleanup failures remain observable.

## 5. Persistence and local data

See the [review rules](../CONTRIBUTE.md#persistence-and-local-data) and
[database lifecycle](../RELEASING.md#database-lifecycle).

- [ ] SQL data values are parameterized.
- [ ] Structural SQL interpolates only strict constants or mathematically
      constructed placeholders, never raw user input.
- [ ] Secrets have a short lifetime; exceptions and logs omit credentials,
      payloads, keys, and peer identities.
- [ ] Encrypted profiles use one random PMK and domain-separated DB, secret,
      and blob keys.
- [ ] Password protection is confined to the replaceable `KeyProtector`
      boundary; consumers do not depend on the software keyslot.
- [ ] Purge fences runtime access and destroys protected PMK access before
      filesystem cleanup; failures preserve any recoverable copy.
- [ ] Blob IDs are opaque and path-independent; formats are versioned and
      authenticated, ownership is explicit, and encrypted blobs use no
      plaintext temporary files.

## 6. Code quality and package structure

See the [contribution rules](../CONTRIBUTE.md#4-architecture--design-principles)
and [module cohesion rules](../CONTRIBUTE.md#6-module-cohesion--size).

- [ ] Cross-domain imports use the intended public facade; sibling imports
      follow the package's internal import boundary.
- [ ] Filesystem code uses `pathlib.Path` and resource operations use context
      managers where applicable.
- [ ] New and changed functions have explicit payload and return types.
- [ ] New and changed classes and methods have the required Google-style
      docstrings.
- [ ] Each changed module retains one cohesive primary responsibility.
- [ ] Substantial changes in modules above the size guardrails include a real
      ownership-boundary review and justified extraction decision.
- [ ] Package facades remain thin public interfaces without orchestration.
- [ ] Cohesive multi-module subsystems use meaningful package boundaries.
- [ ] Names express local ownership without generic helper buckets or false
      private aliases.
- [ ] Related `<concept>_*.py` siblings trigger an explicit package-promotion
      review when they are expected to evolve together.
- [ ] A structural refactor improves ownership instead of only moving lines
      among broad or flat modules.

## 7. Versioning and release integrity

See the [release policy](../RELEASING.md) and
[IPC contract rules](../CONTRIBUTE.md#8-ipc-contract-evolution--glossary).

- [ ] Application and compatibility values come from
      `src/metor/versioning/__init__.py`.
- [ ] Every persistent SQL schema change, including an additive one, receives
      a `DB_SCHEMA_VERSION` bump and the advertised adjacent migrations.
- [ ] Breaking IPC or peer-wire changes receive the appropriate protocol
      generation decision; additive defaulted IPC fields do not trigger an
      automatic bump.
- [ ] Incompatible keyslot, blob, or cryptographic derivation changes receive
      an explicit generation, migration, and support decision.
- [ ] Each `*_MIN_SUPPORTED` value matches implemented reader or negotiation
      coverage.
- [ ] `APP_VERSION` changes only in the explicit release process, independently
      of compatibility generations.
- [ ] Code-owned API, settings, schema, and compatibility references are
      regenerated and validated from their authoritative sources.
