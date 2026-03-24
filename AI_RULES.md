# Metor AI Agent Instructions

You are acting as a senior Python software engineer working on the "Metor" project.
Metor is a secure, Tor-based terminal messenger using a Client-Daemon architecture.

When writing or modifying code for this repository, you MUST strictly adhere to the following rules:

## 1. Language & Naming

- **English Only:** All code, variables, comments, commit messages, and docstrings MUST be written in English.
- **Naming Conventions:** Use `snake_case` for variables/functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- **Private Methods:** Prefix internal class methods and properties with an underscore (e.g., `def _load(self):`).

## 2. Typing & Signatures

- **Strict & Explicit Typing:** Every function, method, and variable MUST have strict Python type hints. Never use bare types like `List` or `Tuple` -> always define their generic payload (e.g., `List[Tuple[str, int, bool]]`).
- **Return Types:** Every function MUST declare a return type (use `-> None` if it returns nothing).

## 3. Documentation (Docstrings)

- **Google Style:** Use Google-style docstrings for every class and method.
- **Meaningful Descriptions:** Do not just repeat the function name. Explain _what_ it does and _why_.
- **Input/Output (STRICT):** Every method docstring MUST have an `Args:` and `Returns:` block. If a function takes no arguments, write `Args:\n    None`. If it returns nothing, write `Returns:\n    None`.
- **Comments:** Keep comments strictly objective. No conversational filler, no changelog notes (e.g., absolutely no "NEW:", "As requested:"). Write comments for a production codebase.

## 4. Architecture, Network & Design Principles

- **DRY & DDD:** Respect the domain boundaries (`core`, `data`, `ui`, `utils`). Extract repeated logic into helper functions or base classes.
- **Context Managers:** Always use `with` statements for file operations, databases, sockets, and locks to ensure proper resource cleanup.
- **Modern Path Handling:** Use Python's `pathlib.Path` strictly over the legacy `os.path` module for all filesystem operations.
- **TCP Stream Framing (CRITICAL):** Never assume `socket.recv()` returns a complete protocol frame or message. Always implement line-buffering or length-prefixing to safely reconstruct stream fragments.
- **Cryptography & Security:** - Never use string formatting (f-strings) to inject variables directly into SQL queries or PRAGMAs. Always use parameterized queries.
  - Use `secrets` instead of `os` or `random` for cryptographic token/seed generation.

## 5. Code Formatting (Ruff)

- **Imports First:** All `import` statements MUST be located at the very top of the file, immediately following the module-level docstring.
- **Single Quotes:** Always use single quotes (`'`) for strings unless the string itself contains a single quote. Double quotes are strictly for docstrings (`"""`).

## 6. Proactive Refactoring (The Boy Scout Rule)

- **Auto-Correction:** Whenever you analyze or modify a file, proactively and silently fix existing code in that file that violates these rules (e.g., replacing `os.path` with `pathlib`, fixing generic type hints, or wrapping raw sockets in buffers).
- **Exceptions:** Do this alongside your requested task UNLESS the user explicitly instructs you to "do not refactor".
