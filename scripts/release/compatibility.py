"""Compatibility comparison gates for Metor release manifests."""

from dataclasses import dataclass
from typing import Any, cast

from metor.data.sql.migrations import migration_path


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class CompatibilityReport:
    """Collects release-blocking errors and review notes.

    Args:
        errors (tuple[str, ...]): Conditions that must block a release.
        notes (tuple[str, ...]): Non-blocking compatibility classifications.

    Returns:
        None
    """

    errors: tuple[str, ...]
    notes: tuple[str, ...]


def _resolved_routes(schema: JsonObject, route_group: str) -> dict[str, JsonObject]:
    """Resolves route references in one generated IPC schema.

    Args:
        schema (JsonObject): Generated IPC schema document.
        route_group (str): ``commands`` or ``events``.

    Returns:
        dict[str, JsonObject]: Wire route to DTO schema mapping.
    """
    definitions = cast(dict[str, JsonObject], schema.get('definitions', {}))
    routes = cast(dict[str, JsonObject], schema.get(route_group, {}))
    resolved: dict[str, JsonObject] = {}
    for route, reference in routes.items():
        ref: str = cast(str, reference.get('$ref', ''))
        name: str = ref.rsplit('/', maxsplit=1)[-1]
        if name in definitions:
            resolved[route] = definitions[name]
    return resolved


def _accepts_previous_schema(previous: Any, current: Any) -> bool:
    """Reports whether a current JSON Schema fragment accepts the old value set.

    Args:
        previous (Any): Schema fragment from the previous public release.
        current (Any): Schema fragment from the candidate release.

    Returns:
        bool: True when no detectable narrowing occurred.
    """
    if previous == current:
        return True
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False
    previous_object = cast(JsonObject, previous)
    current_object = cast(JsonObject, current)

    previous_any = previous_object.get('anyOf')
    current_any = current_object.get('anyOf')
    if isinstance(previous_any, list) and isinstance(current_any, list):
        return all(
            any(
                _accepts_previous_schema(old_member, new_member)
                for new_member in current_any
            )
            for old_member in previous_any
        )
    if isinstance(current_any, list):
        return any(
            _accepts_previous_schema(previous_object, new_member)
            for new_member in current_any
        )
    if isinstance(previous_any, list):
        return False

    previous_enum = previous_object.get('enum')
    current_enum = current_object.get('enum')
    if isinstance(previous_enum, list):
        if not isinstance(current_enum, list):
            return previous_object.get('type') == current_object.get('type')
        return set(previous_enum).issubset(set(current_enum))
    if isinstance(current_enum, list):
        return False

    if previous_object.get('type') != current_object.get('type'):
        return False
    if previous_object.get('type') == 'array':
        return _accepts_previous_schema(
            previous_object.get('items', {}), current_object.get('items', {})
        )

    return True


def ipc_breaking_changes(previous: JsonObject, current: JsonObject) -> tuple[str, ...]:
    """Finds detectable removals, required additions, and type narrowings.

    Args:
        previous (JsonObject): Previous generated IPC schema.
        current (JsonObject): Candidate generated IPC schema.

    Returns:
        tuple[str, ...]: Human-readable breaking changes.
    """
    changes: list[str] = []
    for group in ('commands', 'events'):
        old_routes: dict[str, JsonObject] = _resolved_routes(previous, group)
        new_routes: dict[str, JsonObject] = _resolved_routes(current, group)
        for route in sorted(old_routes.keys() - new_routes.keys()):
            changes.append(f'IPC {group[:-1]} removed: {route}')
        for route in sorted(old_routes.keys() & new_routes.keys()):
            old_dto: JsonObject = old_routes[route]
            new_dto: JsonObject = new_routes[route]
            old_properties = cast(dict[str, Any], old_dto.get('properties', {}))
            new_properties = cast(dict[str, Any], new_dto.get('properties', {}))
            for field in sorted(old_properties.keys() - new_properties.keys()):
                changes.append(f'IPC field removed: {route}.{field}')
            old_required: set[str] = set(cast(list[str], old_dto.get('required', [])))
            new_required: set[str] = set(cast(list[str], new_dto.get('required', [])))
            for field in sorted(new_required - old_required):
                changes.append(f'IPC required field added: {route}.{field}')
            for field in sorted(old_properties.keys() & new_properties.keys()):
                if not _accepts_previous_schema(
                    old_properties[field], new_properties[field]
                ):
                    changes.append(f'IPC field type narrowed: {route}.{field}')
    return tuple(changes)


def _axis_errors(name: str, axis: JsonObject) -> list[str]:
    """Validates current/minimum invariants for one manifest axis.

    Args:
        name (str): Axis label for diagnostics.
        axis (JsonObject): Manifest axis containing current and minimum values.

    Returns:
        list[str]: Invariant failures.
    """
    current: int = cast(int, axis['current'])
    minimum: int = cast(int, axis['minimum_supported'])
    errors: list[str] = []
    if current < 1 or minimum < 1:
        errors.append(f'{name} versions must be at least 1.')
    if minimum > current:
        errors.append(f'{name} minimum supported exceeds current.')
    return errors


def compare_manifests(
    previous: JsonObject | None,
    current: JsonObject,
    peer_classification: str = 'unchanged',
    crypto_migration_reviewed: bool = False,
) -> CompatibilityReport:
    """Runs every deterministic release compatibility gate.

    Args:
        previous (JsonObject | None): Latest public release manifest, if any.
        current (JsonObject): Candidate release manifest.
        peer_classification (str): Explicit ``unchanged``, ``additive``, or
            ``breaking`` peer-contract review decision.
        crypto_migration_reviewed (bool): Explicit approval that derivation
            migration/support was architecturally addressed.

    Returns:
        CompatibilityReport: Blocking errors and classification notes.
    """
    errors: list[str] = []
    notes: list[str] = []
    for name in ('ipc', 'peer', 'database', 'keyslot', 'blob'):
        errors.extend(_axis_errors(name, cast(JsonObject, current[name])))

    for name in ('keyslot', 'blob'):
        axis = cast(JsonObject, current[name])
        if axis['minimum_supported'] != axis['current']:
            errors.append(
                f'{name} reader currently supports only its exact current format; '
                'minimum supported must match current.'
            )

    if previous is None:
        notes.append('No previous public release; current manifest is the baseline.')
        return CompatibilityReport(tuple(errors), tuple(notes))

    previous_ipc = cast(JsonObject, cast(JsonObject, previous['ipc'])['schema'])
    current_ipc = cast(JsonObject, cast(JsonObject, current['ipc'])['schema'])
    ipc_breaks: tuple[str, ...] = ipc_breaking_changes(previous_ipc, current_ipc)
    previous_ipc_version: int = cast(int, cast(JsonObject, previous['ipc'])['current'])
    current_ipc_version: int = cast(int, cast(JsonObject, current['ipc'])['current'])
    if ipc_breaks and current_ipc_version <= previous_ipc_version:
        errors.extend(
            (*ipc_breaks, 'Breaking IPC changes require an explicit IPC bump.')
        )
    elif ipc_breaks:
        notes.append('Breaking IPC changes are covered by an explicit IPC bump.')
    else:
        notes.append('IPC schema is additive or unchanged.')

    old_peer = cast(JsonObject, previous['peer'])
    new_peer = cast(JsonObject, current['peer'])
    peer_contract_changed: bool = old_peer['contract'] != new_peer['contract']
    if peer_classification not in {'unchanged', 'additive', 'breaking'}:
        errors.append('Peer compatibility classification is invalid.')
    elif peer_contract_changed and peer_classification == 'unchanged':
        errors.append('Peer descriptor changed; classify it as additive or breaking.')
    elif peer_classification == 'breaking' and cast(int, new_peer['current']) <= cast(
        int, old_peer['current']
    ):
        errors.append('Breaking peer changes require an explicit peer protocol bump.')
    else:
        notes.append(f'Peer compatibility was classified as {peer_classification}.')

    old_database = cast(JsonObject, previous['database'])
    new_database = cast(JsonObject, current['database'])
    database_changed: bool = old_database['schema'] != new_database['schema']
    old_db_version: int = cast(int, old_database['current'])
    new_db_version: int = cast(int, new_database['current'])
    if database_changed and new_db_version <= old_db_version:
        errors.append('Persistent SQL schema changed without a DB schema bump.')
    if new_db_version > old_db_version:
        current_min: int = cast(int, new_database['minimum_supported'])
        for supported_version in range(current_min, new_db_version):
            try:
                migration_path(supported_version)
            except Exception as exc:
                errors.append(str(exc))

    for name in ('keyslot', 'blob'):
        old_axis = cast(JsonObject, previous[name])
        new_axis = cast(JsonObject, current[name])
        if old_axis['contract'] != new_axis['contract'] and cast(
            int, new_axis['current']
        ) <= cast(int, old_axis['current']):
            errors.append(f'{name} contract changed without an explicit format bump.')

    old_derivation = cast(JsonObject, previous['derivation'])
    new_derivation = cast(JsonObject, current['derivation'])
    for name in ('profile_key', 'blob_object'):
        old_axis = cast(JsonObject, old_derivation[name])
        new_axis = cast(JsonObject, new_derivation[name])
        context_changed: bool = old_axis != new_axis
        if context_changed and cast(int, new_axis['current']) <= cast(
            int, old_axis['current']
        ):
            errors.append(f'{name} derivation context changed without a version bump.')
        elif context_changed and not crypto_migration_reviewed:
            errors.append(
                f'{name} derivation changed without explicit migration/support review.'
            )

    for name in ('ipc', 'peer', 'database', 'keyslot', 'blob'):
        old_axis = cast(JsonObject, previous[name])
        new_axis = cast(JsonObject, current[name])
        if cast(int, new_axis['current']) < cast(int, old_axis['current']):
            errors.append(f'{name} current version went backwards.')
    for name in ('profile_key', 'blob_object'):
        old_axis = cast(JsonObject, old_derivation[name])
        new_axis = cast(JsonObject, new_derivation[name])
        if cast(int, new_axis['current']) < cast(int, old_axis['current']):
            errors.append(f'{name} derivation version went backwards.')
    return CompatibilityReport(tuple(dict.fromkeys(errors)), tuple(notes))
