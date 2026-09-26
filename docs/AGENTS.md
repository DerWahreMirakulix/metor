# Metor agent routing

Read [CONTRIBUTE.md](./CONTRIBUTE.md) before modifying the repository. Metor is a
security-critical Tor messenger: typed client-daemon boundaries, authorization,
anonymity, persistence integrity, and compatibility are non-negotiable.

Load only the references needed for the task:

- architecture or ownership: [ARCHITECTURE.md](./ARCHITECTURE.md);
- security or architecture review: [AUDIT.md](./governance/AUDIT.md), using
  [CONTRIBUTE.md](./CONTRIBUTE.md) as the authoritative rules;
- IPC/API: the IPC sections of `ARCHITECTURE.md`,
  [API.md](./generated/API.md), and [api.schema.json](./generated/api.schema.json);
- settings or terminology: [SETTINGS.md](./generated/SETTINGS.md) and
  [GLOSSARY.md](./GLOSSARY.md);
- release/versioning: [RELEASING.md](./RELEASING.md),
  `src/metor/versioning/__init__.py`, and
  [compatibility.json](./generated/compatibility.json);
- frontend integration: [FRONTENDS.md](contracts/FRONTENDS.md);
- GUI operation, device configuration, behavior, or presentation:
  [GUI.md](./contracts/GUI.md).

Frontends own presentation and interaction state only. They never access SQL,
Tor keys, host profile files, transport internals, or authorization truth. Use
typed IPC and the narrow public frontend host/settings/platform boundaries.

Do not hardcode timeouts, buffers, retries, or other system limits. Follow the
module-cohesion and package-structure rules in `CONTRIBUTE.md`; substantial work
in an oversized module requires a real ownership-boundary review.

Never edit `docs/generated/*` manually. Update its code or generator and
regenerate. Before creating documentation, identify its owner and extend an
existing canonical document where possible. Do not create `docs/README.md`,
temporary reports at `docs/` root, or another support-status document.

For release automation, packaging, wire contracts, database schemas, keyslot or
blob formats, cryptographic derivation, or compatibility, inspect the versioning
source and `RELEASING.md`. Never bump a compatibility generation automatically.
