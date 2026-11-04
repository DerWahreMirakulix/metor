"""Contact alias validation for address-book mutations in the Core domain."""

import unicodedata


def is_valid_contact_alias(alias: str) -> bool:
    """Accepts nonempty single-line Unicode labels without control characters.

    Spaces, letters and joined emoji remain valid. Surrogates cannot be stored
    as UTF-8; control and line-separator characters cannot form usable labels.
    Apply this to new labels only so existing aliases can still be recovered.
    """
    return bool(alias) and all(
        unicodedata.category(character) not in {'Cc', 'Cs', 'Zl', 'Zp'}
        for character in alias
    )
