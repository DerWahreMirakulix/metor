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

- **Google Style:** Use Google-style docstrings for every class and method.
- **Meaningful Descriptions:** Explain _what_ the function does and _why_.
- **Input/Output (STRICT):** Every method docstring MUST have an `Args:` and `Returns:` block. If a function takes no arguments, write `Args:\n    None`. If it returns nothing, write `Returns:\n    None`.
- **Comments:** Keep comments strictly objective. No conversational filler, no changelog notes. Write comments for a production codebase.

## 4. Architecture & Design Principles

- **Domain-Driven Design (DDD):** Respect the domain boundaries (`core`, `data`, `ui`, `utils`). Extract repeated logic into helper functions or base classes.
- **Context Managers:** Always use `with` statements for file operations, databases, sockets, and locks to ensure proper resource cleanup.
- **Modern Path Handling:** Use Python's `pathlib.Path` strictly over the legacy `os.path` module for all filesystem operations.

## 5. Security & Network Protocols (CRITICAL)

- **TCP Stream Framing:** Never assume `socket.recv()` returns a complete protocol frame or message. Always implement line-buffering or length-prefixing to safely reconstruct stream fragments.
- **Cryptography:** Never use `os.urandom` or `random` for key generation; exclusively use `secrets.token_bytes()`.
- **Data-at-Rest:** Never use string formatting (f-strings) to inject variables directly into SQL queries or PRAGMAs. Always use parameterized queries.

## 6. Code Formatting (Ruff)

- **Imports First:** All `import` statements MUST be located at the very top of the file.
- **Single Quotes:** Always use single quotes (`'`) for strings unless the string itself contains a single quote. Double quotes are strictly for docstrings (`"""`).
