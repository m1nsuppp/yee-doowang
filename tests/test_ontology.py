import unittest

from yee_doowang.catalog import Catalog
from yee_doowang.ontology import ExerciseOntology


class ExerciseOntologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = Catalog.load()
        cls.ontology = ExerciseOntology(cls.catalog)

    def test_squat_roles(self) -> None:
        roles = self.ontology.muscle_roles(["0043"])

        self.assertEqual(roles["0043"].direct, ["glutes"])
        self.assertIn("quads", roles["0043"].indirect)

    def test_press_roles(self) -> None:
        roles = self.ontology.muscle_roles(["0289"])

        self.assertEqual(roles["0289"].direct, ["chest"])
        self.assertIn("triceps", roles["0289"].indirect)
        self.assertIn("deltoids", roles["0289"].indirect)

    def test_unknown_exercise_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.ontology.muscle_roles(["9999"])
