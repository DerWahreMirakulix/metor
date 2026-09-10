"""Semantic Version calculation for explicit Metor releases."""

import re
from dataclasses import dataclass


SEMVER_RE: re.Pattern[str] = re.compile(
    r'^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
    r'(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?$'
)


@dataclass(frozen=True, order=True)
class SemVer:
    """Represents the Metor subset of Semantic Versioning.

    Args:
        major (int): Major product-contract generation.
        minor (int): Feature-release generation.
        patch (int): Bugfix-release generation.
        prerelease (str | None): Optional alpha, beta, or rc label.
        prerelease_number (int | None): Numeric prerelease sequence.

    Returns:
        None
    """

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    prerelease_number: int | None = None

    @classmethod
    def parse(cls, value: str) -> 'SemVer':
        """Parses a Metor release version or tag.

        Args:
            value (str): Semantic Version, optionally prefixed with ``v``.

        Raises:
            ValueError: If the value is outside the supported SemVer subset.

        Returns:
            SemVer: Parsed immutable version.
        """
        match = SEMVER_RE.fullmatch(value)
        if match is None:
            raise ValueError(f'Invalid Metor release version: {value}')
        prerelease_number: int | None = (
            int(match.group(5)) if match.group(5) is not None else None
        )
        return cls(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            match.group(4),
            prerelease_number,
        )

    def __str__(self) -> str:
        """Formats the canonical version without a tag prefix.

        Args:
            None

        Returns:
            str: Canonical Semantic Version.
        """
        value: str = f'{self.major}.{self.minor}.{self.patch}'
        if self.prerelease is not None:
            value += f'-{self.prerelease}.{self.prerelease_number}'
        return value


def calculate_next_version(
    current_version: str,
    release_type: str,
    prerelease: str = 'none',
    previous_release: str | None = None,
) -> str:
    """Calculates the next application version for one explicit release.

    Args:
        current_version (str): Version currently stored in the registry.
        release_type (str): ``current``, ``patch``, ``minor``, or ``major``.
        prerelease (str): ``none``, ``alpha``, ``beta``, or ``rc``.
        previous_release (str | None): Latest public tag, if one exists.

    Raises:
        ValueError: If the release request is invalid.

    Returns:
        str: Calculated application Semantic Version.
    """
    current: SemVer = SemVer.parse(current_version)
    baseline: SemVer = current
    if release_type == 'current':
        if previous_release is not None:
            raise ValueError(
                'The current-version option is only valid for the first release.'
            )
        base = SemVer(current.major, current.minor, current.patch)
    else:
        if release_type not in {'patch', 'minor', 'major'}:
            raise ValueError(f'Unsupported release type: {release_type}')
        baseline = (
            SemVer.parse(previous_release) if previous_release is not None else current
        )
        if baseline.prerelease is not None:
            base = SemVer(baseline.major, baseline.minor, baseline.patch)
        elif release_type == 'patch':
            base = SemVer(baseline.major, baseline.minor, baseline.patch + 1)
        elif release_type == 'minor':
            base = SemVer(baseline.major, baseline.minor + 1, 0)
        else:
            base = SemVer(baseline.major + 1, 0, 0)

    if prerelease == 'none':
        return str(base)
    if prerelease not in {'alpha', 'beta', 'rc'}:
        raise ValueError(f'Unsupported prerelease type: {prerelease}')
    prerelease_number: int = 1
    if (
        previous_release is not None
        and baseline.prerelease == prerelease
        and baseline.major == base.major
        and baseline.minor == base.minor
        and baseline.patch == base.patch
        and baseline.prerelease_number is not None
    ):
        prerelease_number = baseline.prerelease_number + 1
    return str(
        SemVer(base.major, base.minor, base.patch, prerelease, prerelease_number)
    )
