"""Schema-version migration path for FW-CAP-DISPATCH-004 objects.

Thin reuse of perception.src.migrations' register()/migrate() mechanism --
not reimplemented. Only one version (1.0) exists as of this mission; this
module exists so a future schema_version bump has a defined, tested
landing spot, exactly like perception/src/migrations.py did for Proof 001.
"""
from perception.src import migrations as perception_migrations

register = perception_migrations.register
migrate = perception_migrations.migrate
