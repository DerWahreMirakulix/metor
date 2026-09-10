"""Semantic Version calculation and baseline selection for Metor releases."""

import re
from dataclasses import dataclass
from typing import Iterable


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


def select_latest_stable_release(tags: Iterable[str]) -> str | None:
    """Selects the highest valid stable release tag independent of source order.

    Prerelease tags do not establish the baseline for the normal stable release
    train. Invalid or unrelated tags are ignored.

    Args:
        tags (Iterable[str]): Candidate release tags from a repository or API.

    Returns:
        str | None: Canonical stable release tag, or ``None`` when absent.
    """
    stable_versions: list[SemVer] = []
    for tag in tags:
        try:
            version: SemVer = SemVer.parse(tag)
        except ValueError:
            continue
        if version.prerelease is None:
            stable_versions.append(version)
    if not stable_versions:
        return None
    return f'v{max(stable_versions)}'


def calculate_next_version(
    current_version: str,
    release_type: str,
    previous_release: str | None = None,
) -> str:
    """Calculates the next application version for one explicit release.

    Args:
        current_version (str): Version currently stored in the registry.
        release_type (str): ``current``, ``patch``, ``minor``, or ``major``.
        previous_release (str | None): Latest public tag, if one exists.

    Raises:
        ValueError: If the release request is invalid.

    Returns:
        str: Calculated application Semantic Version.
    """
    current: SemVer = SemVer.parse(current_version)
    if current.prerelease is not None:
        raise ValueError('Application release versions must be stable.')
    if release_type == 'current':
        if previous_release is not None:
            raise ValueError(
                'The current-version option is only valid for the first release.'
            )
        return str(current)
    else:
        if release_type not in {'patch', 'minor', 'major'}:
            raise ValueError(f'Unsupported release type: {release_type}')
        baseline: SemVer = (
            SemVer.parse(previous_release) if previous_release is not None else current
        )
        if baseline.prerelease is not None:
            raise ValueError('Release baselines must be stable Semantic Versions.')
        if release_type == 'patch':
            base = SemVer(baseline.major, baseline.minor, baseline.patch + 1)
        elif release_type == 'minor':
            base = SemVer(baseline.major, baseline.minor + 1, 0)
        else:
            base = SemVer(baseline.major + 1, 0, 0)
    return str(base)
