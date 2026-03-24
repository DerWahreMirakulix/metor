# Metor Security & Architecture Audit Checklist

This document outlines the strict audit criteria for the Metor project. Because Metor handles anonymous communication via the Tor network, any vulnerability can lead to de-anonymization, data leaks, or remote code execution.

Every Pull Request, AI code generation, or architectural change MUST be audited against the following vectors:

## 1. Cryptography & OPSEC

- [ ] **PRNG Verification:** Are all cryptographic seeds, tokens, and nonces generated using the `secrets` module? (Reject any use of `random` or `os.urandom`).
- [ ] **Ed25519 Handshakes:** Are signatures validated securely without susceptibility to timing attacks?
- [ ] **Key Storage:** Are master keys (Tor and Metor) correctly encrypted using `Argon2i` and `SecretBox` before being written to disk? Are file permissions strictly set to `0o700` or `0o600`?

## 2. Network & IPC Resilience

- [ ] **TCP Fragmentation:** Does the code handle partial TCP packets? Verify that all socket reads (`recv`) use a buffer and a clear delimiter (like `\n`) before parsing the payload. **Never assume 1 recv = 1 message.**
- [ ] **Socket Timeouts:** Do all network sockets implement strict timeouts to prevent hanging threads and Denial of Service (DoS) attacks?
- [ ] **IPC Authentication:** Is the local IPC server correctly bound to `127.0.0.1`? Does it properly handle malformed JSON payloads without crashing the daemon?

## 3. Thread-Safety & Concurrency

- [ ] **Dictionary Mutations:** Are shared resources (like `_connections` or `_pending_connections`) safely copied or locked before iteration? (e.g., `list(dict.keys())` under lock).
- [ ] **Ghost Locks:** Does the file locking mechanism (`FileLock`) handle crashed states and stale locks gracefully using timestamps?
- [ ] **Zombie Processes:** Are spawned Tor processes properly tracked and forcefully killed (`SIGKILL`/`terminate`) if the daemon shuts down?

## 4. Data-at-Rest & Database Integrity

- [ ] **SQL Injections:** Are all SQLite inputs strictly parameterized? (e.g., `execute('... WHERE alias = ?', (alias,))`). Reject any PRAGMA or SQL query built with f-strings or string concatenation.
- [ ] **Wear-Leveling Awareness:** If data destruction (Nuke/Purge) is implemented, is the user warned that file shredding is ineffective on modern SSDs? Is reliance placed on cryptographic erasure instead?
- [ ] **Data Leaks in Memory:** Are sensitive variables (passwords, decrypted keys) minimized in scope and not accidentally logged or printed to the terminal?

## 5. Code Quality & Standards (DDD)

- [ ] **Domain Isolation:** Does the UI directly access the database? (It shouldn't. UI must go through the IPC API).
- [ ] **Legacy Modules:** Are there any remnants of `os.path`? (Must be `pathlib.Path`).
- [ ] **Typing:** Are all generic types explicitly defined? (e.g., `Dict[str, Any]`, not just `Dict`).
- [ ] **Docstrings:** Does every method have a complete Google-style docstring with `Args:` and `Returns:` blocks?
