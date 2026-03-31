"""
Module providing centralized type coercion and parsing utilities.
Ensures strict type compliance across configurations and CLI inputs.
"""

from typing import Union, Any


class TypeCaster:
    """Utility class for safe runtime type casting and inference."""

    @staticmethod
    def to_str(val: Any, default: str = '') -> str:
        """
        Safely casts a value to a string.

        Args:
            val (Any): The raw value.
            default (str): Fallback if None.

        Returns:
            str: The stringified value.
        """
        if val is None:
            return default
        return str(val)

    @staticmethod
    def to_int(val: Any, default: int = 0) -> int:
        """
        Safely casts a value to an integer.

        Args:
            val (Any): The raw value.
            default (int): Fallback if casting fails.

        Returns:
            int: The coerced integer.
        """
        if val is None:
            return default
        try:
            return int(float(str(val)))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def to_float(val: Any, default: float = 0.0) -> float:
        """
        Safely casts a value to a float.

        Args:
            val (Any): The raw value.
            default (float): Fallback if casting fails.

        Returns:
            float: The coerced float.
        """
        if val is None:
            return default
        try:
            return float(str(val))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def to_bool(val: Any, default: bool = False) -> bool:
        """
        Safely casts a value to a boolean.

        Args:
            val (Any): The raw value.
            default (bool): Fallback if casting fails.

        Returns:
            bool: The coerced boolean.
        """
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() == 'true'
        try:
            return bool(int(float(str(val))))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def infer_from_string(val: str) -> Union[str, int, float, bool]:
        """
        Infers the native Python type from a raw CLI string.

        Args:
            val (str): The string value from sys.argv.

        Returns:
            Union[str, int, float, bool]: The correctly typed value.
        """
        val_lower: str = val.lower()
        if val_lower == 'true':
            return True
        if val_lower == 'false':
            return False

        if val.isdigit() or (val.startswith('-') and val[1:].isdigit()):
            return int(val)

        try:
            return float(val)
        except ValueError:
            return val
