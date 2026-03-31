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
- **Import Architecture (Facade Pattern):** When importing from an _external_ or _parent_ domain, you MUST use the package's `__init__.py` Facade. When importing from a sibling module within the _same_ domain/directory (horizontal imports), you MUST explicitly bypass the Facade and import directly from the file to prevent circular dependencies.
- **Context Managers:** Always use `with` statements for file operations, databases, sockets, and locks to ensure proper resource cleanup.
- **Modern Path Handling:** Use Python's `pathlib.Path` strictly over the legacy `os.path` module for all filesystem operations.

## 5. Security & Network Protocols (CRITICAL)

- **TCP Stream Framing:** Never assume `socket.recv()` returns a complete protocol frame or message. Always implement line-buffering or length-prefixing to safely reconstruct stream fragments.
- **Cryptography:** Never use `os.urandom` or `random` for key generation; exclusively use a cryptographically secure module (like `secrets`).
- **Data-at-Rest (SQL Integrity):** Always use parameterized queries (`?`) for user data operations. Because SQL engines (like SQLite) do not support parameterization for structural commands (like `PRAGMA` or table names), f-strings may only be used there if the injected value is deeply sanitized, mathematically escaped, or a strict system constant. Under no circumstances may raw user input be formatted directly into an SQL string.

## 6. Code Formatting (Ruff)

- **Imports First:** All `import` statements MUST (unless a runtime import is absolutely necessary) be located at the very top of the file (immediately following the module docstring).
- **Import Delimiters:** Standard library and external domain imports MUST be separated from same-domain internal imports using exactly the `# Local Package Imports` comment. This comment MUST NOT be placed above imports from higher-level Metor domains.
- **Single Quotes:** Always use single quotes (`'`) for strings unless the string itself contains a single quote. Double quotes are strictly for docstrings (`"""`).
