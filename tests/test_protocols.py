from __future__ import annotations

import unittest

from app.main import safe_filename
from app.protocols.common import (
    TRIAL_DJ,
    TRIAL_SDJ_L,
    TRIAL_SDJ_R,
    TRIAL_SDJ30_L,
    TRIAL_SDJ30_R,
    active_sides_for_trial,
    classify_trial,
    contact_key_for_trial,
    platform_cm_for_trial,
)


class ProtocolClassificationTests(unittest.TestCase):
    def test_supported_trial_names(self) -> None:
        cases = {
            "DJ_1": TRIAL_DJ,
            "SDJ_L_1": TRIAL_SDJ_L,
            "SDJ_R_2": TRIAL_SDJ_R,
            "SDJ30_L_3": TRIAL_SDJ30_L,
            "SDJ30_R_4": TRIAL_SDJ30_R,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(classify_trial(name), expected)

    def test_unrelated_trial_is_ignored(self) -> None:
        self.assertIsNone(classify_trial("WALK_1"))

    def test_protocol_metadata(self) -> None:
        self.assertEqual(active_sides_for_trial(TRIAL_DJ), ["L", "R"])
        self.assertEqual(active_sides_for_trial(TRIAL_SDJ_L), ["L"])
        self.assertEqual(active_sides_for_trial(TRIAL_SDJ30_R), ["R"])
        self.assertEqual(platform_cm_for_trial(TRIAL_DJ), 30)
        self.assertEqual(platform_cm_for_trial(TRIAL_SDJ_L), 15)
        self.assertEqual(platform_cm_for_trial(TRIAL_SDJ30_R), 30)
        self.assertEqual(contact_key_for_trial(TRIAL_DJ), "combined")


class FilenameTests(unittest.TestCase):
    def test_windows_unsafe_characters_are_removed(self) -> None:
        self.assertEqual(safe_filename('Test: Person / 1'), "Test_Person_1")


if __name__ == "__main__":
    unittest.main()
