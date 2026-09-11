"""Typed outcomes for authenticated peer application-frame admission."""

from enum import IntEnum


class FrameAdmission(IntEnum):
    """Classifies a peer frame without disclosing sensitive policy details.

    ``ACCEPTED`` deliberately has value zero so existing boolean-style callers
    remain safe while the typed result is propagated through the receive loop.
    """

    ACCEPTED = 0
    RESOURCE_LIMIT = 1
    MALFORMED = 2
    POLICY_REJECTED = 3
    PURGING = 4
