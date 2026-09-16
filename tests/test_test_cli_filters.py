import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test as test_module


class TestTypeFiltering(unittest.TestCase):
    def test_generate_only_filter(self):
        tests = [
            {"test_id": "T1", "type": "generate"},
            {"test_id": "T4", "type": "validate"},
        ]

        filtered = test_module._filter_tests_by_type(tests, "generate")

        self.assertEqual([t["test_id"] for t in filtered], ["T1"])

    def test_validate_only_filter(self):
        tests = [
            {"test_id": "T1", "type": "generate"},
            {"test_id": "T4", "type": "validate"},
        ]

        filtered = test_module._filter_tests_by_type(tests, "validate")

        self.assertEqual([t["test_id"] for t in filtered], ["T4"])


if __name__ == "__main__":
    unittest.main()
