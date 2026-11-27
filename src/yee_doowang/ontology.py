from pyrewire import EasySession

from yee_doowang.catalog import Catalog

_PROGRAM = """
.decl primary_muscle(exercise: symbol, muscle: symbol)
.decl secondary_muscle(exercise: symbol, muscle: symbol)
.decl requested_exercise(exercise: symbol)
.decl direct_muscle(exercise: symbol, muscle: symbol)
.decl indirect_muscle(exercise: symbol, muscle: symbol)

direct_muscle(Exercise, Muscle) :-
    requested_exercise(Exercise),
    primary_muscle(Exercise, Muscle).
indirect_muscle(Exercise, Muscle) :-
    requested_exercise(Exercise),
    secondary_muscle(Exercise, Muscle).
"""


class MuscleRoles:
    def __init__(self, direct: list[str], indirect: list[str]) -> None:
        self.direct = direct
        self.indirect = indirect


class ExerciseOntology:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def muscle_roles(self, exercise_ids: list[str]) -> dict[str, MuscleRoles]:
        requested = list(dict.fromkeys(exercise_ids))
        for source_id in requested:
            self._catalog.exercise(source_id)

        with EasySession(_PROGRAM) as session:
            for exercise in self._catalog.exercises():
                session.insert(
                    "primary_muscle",
                    [exercise.source_id, exercise.primary_muscle_id],
                )
                for muscle_id in exercise.secondary_muscle_ids:
                    session.insert(
                        "secondary_muscle",
                        [exercise.source_id, muscle_id],
                    )
            for source_id in requested:
                session.insert("requested_exercise", [source_id])

            direct_rows = session.snapshot("direct_muscle")
            indirect_rows = session.snapshot("indirect_muscle")

        direct: dict[str, list[str]] = {source_id: [] for source_id in requested}
        indirect: dict[str, list[str]] = {source_id: [] for source_id in requested}
        for exercise_id, muscle_id in direct_rows:
            direct.setdefault(exercise_id, []).append(muscle_id)
        for exercise_id, muscle_id in indirect_rows:
            indirect.setdefault(exercise_id, []).append(muscle_id)

        order = {muscle_id: index for index, muscle_id in enumerate(self._catalog.muscle_ids())}
        return {
            source_id: MuscleRoles(
                direct=sorted(direct[source_id], key=order.get),
                indirect=sorted(indirect[source_id], key=order.get),
            )
            for source_id in requested
        }
