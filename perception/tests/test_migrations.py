import unittest

from perception.src import migrations
from perception.src.common import SCHEMA_VERSION


class TestMigrations(unittest.TestCase):
    def test_current_version_is_a_no_op(self):
        obj = {"schema_version": SCHEMA_VERSION, "id": "X-1"}
        self.assertEqual(migrations.migrate("VisualObservation", obj), obj)

    def test_unknown_version_raises(self):
        obj = {"schema_version": "0.1", "id": "X-1"}
        with self.assertRaises(ValueError):
            migrations.migrate("VisualObservation", obj)

    def test_registered_migration_is_applied_and_chains(self):
        @migrations.register("TestType", "0.1")
        def _upgrade_0_1(obj):
            obj = dict(obj)
            obj["schema_version"] = "0.2"
            obj["migrated_from_0_1"] = True
            return obj

        @migrations.register("TestType", "0.2")
        def _upgrade_0_2(obj):
            obj = dict(obj)
            obj["schema_version"] = SCHEMA_VERSION
            obj["migrated_from_0_2"] = True
            return obj

        result = migrations.migrate("TestType", {"schema_version": "0.1"})
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertTrue(result["migrated_from_0_1"])
        self.assertTrue(result["migrated_from_0_2"])


if __name__ == "__main__":
    unittest.main()
