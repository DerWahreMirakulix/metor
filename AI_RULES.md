# Metor AI Agent Instructions

You are acting as a senior Python software engineer working on the "Metor" project.
Metor is a secure, Tor-based terminal messenger using a Client-Daemon architecture.

When writing or modifying code for this repository, you MUST strictly adhere to the following rules:

## 1. Language & Naming

- **English Only:** All code, variables, comments, commit messages, and docstrings MUST be written in English.
- **Naming Conventions:** Use `snake_case` for variables/functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- **Private Methods:** Prefix internal class methods and properties with an underscore (e.g., `def _load(self):`).

## 2. Typing & Signatures

- **Strict Typing:** Every function, method, and variable MUST have strict Python type hints (using the `typing` module where necessary, e.g., `List`, `Dict`, `Optional`, `Tuple`).
- **Return Types:** Every function MUST declare a return type (use `-> None` if it returns nothing).

## 3. Documentation (Docstrings)

- **Google Style:** Use Google-style docstrings for every class and method.
- **Meaningful Descriptions:** Do not just repeat the function name. Explain _what_ it does and _why_.
- **Input/Output:** Every docstring MUST include an `Args:` block (with types and descriptions) and a `Returns:` block (with types and descriptions). Exceptions must be documented under `Raises:`.
- **Comments:** Keep comments strictly objective and architecturally useful. Do not include conversational filler, changelog notes, or self-referential remarks in the code (e.g., absolutely no "NEW:", "As requested:", or "I changed this part"). Write comments for a production codebase, not a tutorial.

## 4. Architecture & Design Principles

- **DRY (Don't Repeat Yourself):** Extract repeated logic into helper functions, base classes, or context managers (e.g., use `metor.utils.lock.FileLock` instead of writing custom OS locking logic).
- **Domain-Driven Design:** Respect the folder structure:
  - `metor/core/`: Heavy lifting, Tor daemon, IPC API (DTOs).
  - `metor/data/`: State management, SQLite, JSON storage, Profiles.
  - `metor/ui/`: Frontend, Chat interface, CLI rendering.
  - `metor/utils/`: Generic helpers and constants.
- **Context Managers:** Always use `with` statements for file operations, sockets, and locks to ensure proper resource cleanup.

## 5. Code Formatting (Ruff)

- **Imports First:** All `import` statements MUST be located at the very top of the file, immediately following the module-level docstring (if present) and before any code or constants.
- **Single Quotes:** Always use single quotes (`'`) for strings unless the string itself contains a single quote. (Double quotes are only for docstrings `"""`).
- **Clean Code:** Keep functions small and focused on a single responsibility.

## 6. Proactive Refactoring (The Boy Scout Rule)

- **Auto-Correction:** Whenever you analyze, modify, or rewrite a file, you MUST automatically fix any existing code in that file that violates the rules defined in this document (e.g., missing type hints, wrong quote styles, missing docstrings, or DRY violations).
- **Exceptions:** Do this proactively and silently alongside your requested task, UNLESS the user explicitly instructs you with "do not refactor" or "only modify the specified lines".
