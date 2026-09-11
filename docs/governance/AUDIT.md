# Metor Security & Architecture Audit Checklist

This document outlines the strict audit criteria and architectural guardrails for the Metor project. Because Metor handles anonymous communication via the Tor network, any vulnerability or architectural leak can lead to de-anonymization, data leaks, or remote code execution.

**⚠️ INSTRUCTIONS FOR AI AGENTS AND HUMAN CONTRIBUTORS:**
Every Pull Request, AI code generation, or architectural change MUST be audited against the following vectors before being merged.

## 1. Domain-Driven Design (DDD) & Architecture

- [ ] **Strict Domain Isolation:** Does the UI (Client) access data layers or cryptographic keys directly? _(It NEVER should. The UI must exclusively communicate via IPC DTOs. If offline, the UI must spin up an ephemeral headless background process to perform data operations)._
- [ ] **Zero-Text Policy:** Does the Daemon send pre-formatted UI strings? _(It shouldn't. The Daemon must only emit raw Domain Codes and data. The UI layer is solely responsible for rendering text)._
- [ ] **Configuration Routing:** Are client-side settings (`ui.*`) kept strictly local? Are server-side settings (`daemon.*`) correctly forwarded to the Daemon via IPC to prevent polluting remote instances?
- [ ] **Centralized Logic:** Are common operations (like type coercion, path resolution, or formatting) handled by centralized utility classes rather than duplicating logic across domains?

## 2. Cryptography & OPSEC

- [ ] **PRNG Verification:** Are all cryptographic seeds, UUIDs, tokens, and nonces generated using a cryptographically secure module (e.g., `secrets`)? _(Reject any use of standard `random`)._
- [ ] **Handshake Security:** Are cryptographic signatures and challenge-response mechanisms validated securely without susceptibility to timing attacks?
- [ ] **Key Storage & Permissions:** Does Argon2id derive only the KEK that wraps a random PMK with authenticated encryption? Are keyslot files and directories strictly minimized (e.g., `0o600` or `0o700`)?
- [ ] **Zero-Trace Policies:** Are volatile runtime keys or sensitive ephemeral data securely shredded from disk immediately upon daemon shutdown or read-receipt?

## 3. Network, IPC & Anti-DoS

- [ ] **TCP Fragmentation & Streaming:** Does the code handle partial TCP packets? Verify that all socket reads (`recv`) use a buffer and a clear delimiter before parsing the payload. **Never assume 1 recv = 1 message.**
- [ ] **Resource Exhaustion:** Are incoming streams capped at maximum byte limits? Are limits on concurrent network connections strictly enforced to prevent OOM or FD exhaustion?
- [ ] **No Magic Numbers:** Are raw numeric literals avoided in favor of defined constants or configurations? _(This applies globally to buffer sizes, retry limits, array bounds, and timeouts)._
- [ ] **Socket Timeouts:** Do all network and IPC sockets implement strict, configurable timeouts to prevent hanging threads and Denial of Service (DoS) attacks?

## 4. Thread-Safety & Concurrency

- [ ] **Resource Locking:** Are shared resources (e.g., dictionaries, connection pools) safely locked using `threading.Lock` before iteration or mutation?
- [ ] **Cross-Process Sync:** Does the cross-process file locking mechanism protect critical configurations across concurrent CLI/Daemon invocations? Does it handle crashed states gracefully?
- [ ] **Zombie Processes:** Are spawned sub-processes (like the Tor binary) properly tracked and forcefully killed if the main process shuts down unexpectedly?
- [ ] **Silent Thread Failures:** Do all background workers contain broad `try/except` blocks to prevent a single malformed packet or unexpected state from crashing the entire Daemon?

## 5. Data-at-Rest & Database Integrity

- [ ] **SQL Injection Prevention:** Are user inputs and payload data strictly passed via parameterized queries (e.g., `?`)?
- [ ] **Safe Structural SQL:** In cases where the SQL engine requires f-strings/concatenation (e.g., `PRAGMA` statements or dynamic `IN` clause placeholders), are the injected variables strictly hardcoded system constants, length-validated lists, or mathematically sanitized? _(Raw user input MUST NEVER be directly formatted into a query string)._
- [ ] **Memory Leaks:** Are sensitive variables (passwords, decrypted keys) minimized in scope? Are exceptions stripped of sensitive payloads before being logged?
- [ ] **Profile Key Hierarchy:** Does encrypted profile creation generate one random PMK, with only independently domain-separated DB, secret, and blob keys exposed at runtime?
- [ ] **Protector Boundary:** Is the password used only to unwrap the PMK, and can a future hardware-backed `KeyProtector` replace the software keyslot without changing consumers?
- [ ] **Key-First Destruction:** Do purge and self-destruct stop runtime access, clear runtime keys, and destroy protected PMK access before filesystem cleanup begins?
- [ ] **External Blobs:** Are blob IDs path-independent, formats versioned, writes authenticated, plaintext temporary files avoided, and temporary versus persistent ownership explicit?

## 6. Code Quality & Standards

- [ ] **Import Architecture:** Do vertical cross-domain imports strictly use the package Facade (`__init__.py`), while horizontal sibling imports explicitly bypass it to prevent circular dependencies?
- [ ] **Modern Python Standards:** Are modern standard libraries used appropriately? (e.g., `pathlib.Path` MUST be used over legacy `os.path`).
- [ ] **Strict Typing:** Are all variables, arguments, and return types explicitly typed with their inner payloads? (e.g., `Dict[str, JsonValue]`, not just `Dict`).
- [ ] **Docstrings:** Does every class and method have a complete Google-style docstring containing descriptions, `Args:`, and `Returns:` blocks?
- [ ] **Module Cohesion:** Does each production module have one cohesive primary responsibility, rather than mixing unrelated domain behavior into a God Module?
- [ ] **Oversized Module Review:** If a production module exceeds approximately 500 logical lines and receives substantial functionality, was a real domain-boundary extraction evaluated? Are modules above approximately 800 lines limited to justified generated or declarative exceptions?
- [ ] **Thin Facades:** Do package facades only expose the intended API, without gaining implementation behavior or cross-domain orchestration?
- [ ] **Subsystem Packaging:** When several modified modules belong to one cohesive subsystem, are they grouped in a meaningful subpackage rather than represented as prefixed siblings in a flat package?
- [ ] **Naming & Ownership:** Do paths and module names express ownership without redundant prefixes, generic helper files, or artificial underscore aliases for normal cross-module APIs?
- [ ] **Package Promotion:** If several `<concept>_*.py` modules exist, was package promotion explicitly evaluated?
- [ ] **Structural Refactor Quality:** Did a God-File refactor improve subsystem ownership rather than merely redistribute implementation across flat files?

## 7. Versioning and Release Integrity

- [ ] **Central Authority:** Do all application and compatibility version values come from `src/metor/versioning.py`?
- [ ] **Persistent Schema:** Did every SQL schema change explicitly bump `DB_SCHEMA_VERSION` and provide every advertised migration step?
- [ ] **Wire Compatibility:** Did breaking IPC or peer-wire behavior explicitly bump its protocol generation?
- [ ] **Storage Compatibility:** Did incompatible keyslot, blob, or cryptographic derivation changes explicitly bump their own generation and address migration?
- [ ] **Minimum Support:** Did `MIN_SUPPORTED` change only with actual reader/negotiation support, and does implementation coverage prove every claimed generation?
- [ ] **Release SemVer:** Did `APP_VERSION` change only through the explicit release process, independently of compatibility generations?
- [ ] **Generated Baseline:** Are `docs/generated/api.schema.json` and `docs/generated/compatibility.json` regenerated and consistent with authoritative code?

## Related acceptance evidence

- [Refactor 2 final remediation evidence](./REFACTOR_2_FINAL_REMEDIATION.md)
