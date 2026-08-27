"""Schema-version migration path for Perception Gateway objects.

Only one version (1.0) exists as of this mission. This module exists so a
future schema_version bump has a defined, tested landing spot instead of an
ad hoc conversion written under pressure later -- matching
governance/db.js's "CREATE TABLE IF NOT EXISTS, no migration risk" posture
from the Pocket Cortex mission: known-version records read cleanly, and an
unknown version fails loudly rather than being silently coerced.
"""
from .common import SCHEMA_VERSION

# object_type -> {from_version: migrate_fn(obj) -> obj}
_MIGRATIONS = {}


def register(object_type: str, from_version: str):
    def decorator(fn):
        _MIGRATIONS.setdefault(object_type, {})[from_version] = fn
        return fn
    return decorator


def migrate(object_type: str, obj: dict) -> dict:
    """Bring `obj` up to SCHEMA_VERSION, or raise if there is no known path."""
    version = obj.get("schema_version")
    if version == SCHEMA_VERSION:
        return obj
    path = _MIGRATIONS.get(object_type, {})
    if version not in path:
        raise ValueError(
            f"no migration registered for {object_type} from schema_version "
            f"{version!r} to {SCHEMA_VERSION!r} -- refusing to guess at a conversion"
        )
    migrated = path[version](obj)
    return migrate(object_type, migrated)  # chain, in case of multi-step upgrades later
