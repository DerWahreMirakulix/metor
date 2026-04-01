"""
Module providing systemic validation and integrity checks.
Isolates File-I/O validation from in-memory type coercion.
"""

import json
from pathlib import Path


def validate_json_file(file_path: Path) -> None:
    """
    Validates the JSON syntax of a given file.
    Implements Fail-Fast to avoid runtime crashes or data wiping.

    Args:
        file_path (Path): The path to the JSON file.

    Raises:
        ValueError: If the file exists but contains a syntax error.

    Returns:
        None
    """
    if file_path.exists():
        try:
            with file_path.open('r', encoding='utf-8') as f:
                json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"'{file_path.name}' is corrupted (Syntax Error). "
                f'Fix it manually or delete the file. Details: {e}'
            ) from e
