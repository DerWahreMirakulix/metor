# Releasing Metor

This is the canonical release and compatibility-version policy for Metor. The
only authoritative version values are in `src/metor/versioning.py`. Application
releases and compatibility generations are independent.

## Version axes

| Axis                   | Meaning                                                         | Bump when                                                                  |
| ---------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Application            | Version of the Metor product and all three Python distributions | An explicit product release is prepared                                    |
| IPC protocol           | Typed client-daemon NDJSON wire contract                        | A breaking command, event, field, type, or wire-semantics change is made   |
| Peer protocol          | Daemon-to-daemon Tor wire and handshake contract                | A breaking peer-wire or peer-semantics change is made                      |
| DB schema              | Durable SQL tables, columns, constraints, and indexes           | Any persistent SQL schema changes, including additive changes              |
| Keyslot format         | Persisted password-protected PMK document                       | Its serialized contract becomes incompatible                               |
| Blob format            | Authenticated encrypted-blob framing                            | Its persisted framing or authenticated interpretation becomes incompatible |
| Profile-key derivation | PMK-to-database, identity-secret, and blob-root domains         | Those domain labels or derivation behavior become incompatible             |
| Blob-object derivation | Per-object key domain                                           | That domain label or derivation behavior becomes incompatible              |

`*_MIN_SUPPORTED` is the oldest generation the current implementation can
actually read or negotiate. It is independent of the current writer/protocol
generation and must increase only when old support is intentionally removed.
Keyslot and blob readers currently accept exactly their current generation, so
their minimum and current values remain equal until multi-generation readers
exist.

Cryptographic derivation bumps are security and persistence changes: they
produce different keys. They require an explicit migration/support design and
release acknowledgement; changing a label is never cosmetic.

## Application Semantic Versioning

Application versions use SemVer and change only during an explicit release.
During initial development, normal feature releases increment `0.MINOR.0` and
bugfix releases increment `0.MINOR.PATCH`. `1.0.0` is an explicit stable
product/API milestone. After 1.0, incompatible public product/API contract
changes increment MAJOR.

Do not tie application SemVer to any protocol or storage generation. A release
may leave every compatibility generation unchanged, and an explicit format
bump does not prescribe the application version.

Metor has no public release yet. Existing internal generations are not reset.
For the first release, choose `current` to publish the registry's current
application version, or explicitly request another SemVer bump. With no prior
`v*` release tag, historical comparison is skipped and the generated
`docs/generated/compatibility.json` becomes the baseline. No migration from arbitrary
pre-release development data is promised.

The supported release types are `current`, `patch`, `minor`, and `major`.
Prerelease channels are intentionally unsupported until an explicit
release-sequencing design introduces them.

## Database lifecycle

`DB_SCHEMA_VERSION` is stored with SQLite/SQLCipher `PRAGMA user_version` and is
not the application version. The SQLCipher key is applied and the database is
probed before its version is read.

- An empty database at version 0 is created transactionally and stamped only
  after all schema DDL succeeds.
- A populated version-0 development database is rejected and must be recreated
  before the first public release; it is never silently relabeled.
- Current versions open without schema mutation.
- Supported older versions follow the adjacent, ordered registry in
  `src/metor/data/sql/migrations.py`.
- Newer and older-than-minimum versions raise typed schema errors.
- Each migration and its `PRAGMA user_version` update share one transaction, so
  a failed step cannot claim the target generation.

When introducing schema generation N, add every adjacent migration required by
the advertised support range and tests for success and rollback. Any persistent
schema change requires a DB generation bump, even when additive.

## Developer commands

Inspect and validate all values:

```console
python scripts/versioning.py status
python scripts/versioning.py validate
```

Make an explicit compatibility decision in the single registry:

```console
python scripts/versioning.py bump ipc
python scripts/versioning.py bump peer
python scripts/versioning.py bump db-schema
python scripts/versioning.py bump keyslot
python scripts/versioning.py bump blob
python scripts/versioning.py set-min ipc 2
```

The CLI edits only `src/metor/versioning.py`. Review the implementation and
migration implications before invoking it. `set-app` is reserved for release
automation.

Regenerate the machine-readable baseline after generating the IPC schema:

```console
python scripts/generate_api_docs.py
python scripts/generate_settings_docs.py
python scripts/generate_compatibility_manifest.py
python scripts/check_release_compatibility.py --current docs/generated/compatibility.json
```

## Automated release process

Start **Release Metor** manually in GitHub Actions and select:

- application bump (`current` for the first release, otherwise patch/minor/major);
- dry-run or publish.

Peer-wire and cryptographic derivation changes remain fail-closed under the
compatibility checker defaults. They require an explicit future release design
before they can be published.

The workflow discovers every non-draft GitHub Release and selects the highest
valid stable `vMAJOR.MINOR.PATCH` tag through parsed SemVer ordering. Prerelease
tags do not establish the normal stable release baseline. It calculates and
writes `APP_VERSION`, then runs Ruff, Ruff format, Mypy, the complete test
suite, all generated-document producers twice for reproducibility, compatibility
gates, Linux and Windows jobs, all three package builds, and wheel-metadata
validation. The canonical generated outputs are `API.md`, `SETTINGS.md`,
`api.schema.json`, and `compatibility.json`. Only a non-dry-run request from
`main` can commit those release changes, create the application release tag,
and publish a GitHub Release containing the generated compatibility matrix. A
dry run performs the same gates from any branch without repository or release
writes. When a first `current` release already has the correct registry and
generated outputs, no release commit is created; the validated checked-out
commit is tagged directly.

The tag convention is `v0.2.0`, `v0.3.0`, or `v1.0.0`. Protocol and format
generations are metadata in each product release, not separate tags.

## Compatibility gates and human decisions

The release manifest is generated from the registry and implementation
descriptors. The checker:

- accepts additive IPC schema evolution and detects removed routes/fields,
  newly required fields, type narrowing, and detectable enum restriction;
- rejects detected breaking IPC changes unless IPC current increased;
- rejects any normalized persistent SQL schema change unless DB current
  increased, then checks the advertised migration path;
- records peer framing and command descriptors and requires an explicit peer
  classification when the descriptor changes;
- rejects keyslot/blob descriptor changes without an explicit format bump and
  checks that current reader support matches the advertised minimum; and
- rejects derivation-context drift without its own bump and explicit migration
  review.

Automation cannot reliably identify every semantic restriction, peer behavior
change, cryptographic migration property, or safe backwards-reader claim.
Developers and agents must classify those architectural changes, update the
central generation only when warranted, implement migration/support, and add
fixtures or golden vectors. The release workflow verifies that decision; it
never blindly increments protocol, schema, storage, or derivation versions.

Generated release references live under `docs/generated/` and are first-class
human documentation as well as machine baselines. Their ownership is the source
definitions and generators: do not edit them manually. Release comparison uses
[compatibility.json](./generated/compatibility.json), whose embedded IPC contract
comes from [api.schema.json](./generated/api.schema.json).
