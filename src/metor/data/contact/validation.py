"""Contact alias validation for address-book mutations in the Core domain."""

import unicodedata

from metor.shared.constants import Constants


def is_valid_contact_alias(alias: str) -> bool:
    """Accepts nonempty single-line Unicode labels without control characters.

    Spaces, letters and joined emoji remain valid. Surrogates cannot be stored
    as UTF-8; control and line-separator characters cannot form usable labels.
    Apply this to new labels only so existing aliases can still be recovered.
    """
    return (
        0 < len(alias) <= Constants.CONTACT_ALIAS_MAX_BYTES
        and all(
            unicodedata.category(character) not in {'Cc', 'Cs', 'Zl', 'Zp'}
            for character in alias
        )
        and len(alias.encode('utf-8')) <= Constants.CONTACT_ALIAS_MAX_BYTES
    )
