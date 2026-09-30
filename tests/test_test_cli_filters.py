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

    def test_fix_only_filter(self):
        tests = [
            {"test_id": "T4", "type": "validate"},
            {"test_id": "T39", "type": "fix"},
        ]

        filtered = test_module._filter_tests_by_type(tests, "fix")

        self.assertEqual([t["test_id"] for t in filtered], ["T39"])

    def test_fix_falls_back_to_validate_sampling(self):
        mut_cfg = {"validate": {"system_prompt": "V", "top_p": 0.8, "top_k": 20}}
        test = {"system_prompt": "S", "temperature": 0.05}

        prompt, temperature, top_p, top_k, _ = test_module._resolve_mut_overrides(mut_cfg, "fix", test)

        self.assertEqual((prompt, temperature, top_p, top_k), ("V", 0.05, 0.8, 20))

    def test_fix_section_overrides_validate(self):
        mut_cfg = {"validate": {"top_p": 0.8}, "fix": {"top_p": 0.5}}
        test = {"system_prompt": "S"}

        _, _, top_p, _, _ = test_module._resolve_mut_overrides(mut_cfg, "fix", test)

        self.assertEqual(top_p, 0.5)


if __name__ == "__main__":
    unittest.main()
