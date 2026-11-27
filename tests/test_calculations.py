import unittest

from yee_doowang.calculations import calculate_macros, estimate_1rm


class CalculationTests(unittest.TestCase):
    def test_1rm_formulas_and_reliability(self) -> None:
        result = estimate_1rm(100, 5)

        self.assertAlmostEqual(result.epley_kg, 116.7)
        self.assertAlmostEqual(result.brzycki_kg, 112.5)
        self.assertAlmostEqual(result.lombardi_kg, 117.5)
        self.assertAlmostEqual(result.average_kg, 115.5)
        self.assertTrue(result.reliable)

        high_reps = estimate_1rm(100, 15)
        self.assertFalse(high_reps.reliable)
        self.assertIn("13회", high_reps.note)

    def test_1rm_rejects_invalid_input(self) -> None:
        with self.assertRaises(ValueError):
            estimate_1rm(0, 5)
        with self.assertRaises(ValueError):
            estimate_1rm(100, 31)

    def test_macros_with_full_body_data(self) -> None:
        result = calculate_macros(
            80,
            "maintain",
            age=30,
            sex="male",
            height_cm=180,
            activity_level="moderate",
        )

        self.assertAlmostEqual(result.bmr_kcal or 0, 1780.0)
        self.assertEqual(result.protein_g_min, 128.0)
        self.assertEqual(result.protein_g_max, 176.0)
        self.assertEqual(result.calories_kcal_min, 2680.0)
        self.assertEqual(result.calories_kcal_max, 2840.0)
        self.assertIn("Mifflin-St Jeor", result.formula)

    def test_macros_fallback_without_body_data(self) -> None:
        result = calculate_macros(80, "cut")

        self.assertIsNone(result.bmr_kcal)
        self.assertEqual(result.calories_kcal_min, 1790.0)
        self.assertEqual(result.calories_kcal_max, 2380.0)
        self.assertIn("체중 기반", result.formula)
        self.assertTrue(result.assumptions)
