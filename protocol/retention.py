from dataclasses import dataclass


@dataclass(frozen=True)
class Retention:
    beat_ids: tuple[int, ...]
    positions: tuple[int, ...]


def normalize_retention(schedule, retained_beats):
    if not isinstance(retained_beats, (list, tuple, set, frozenset)):
        raise ValueError('retained beats must be a list, tuple or set')
    requested = set()
    for beat in retained_beats:
        if type(beat) is not int or beat not in schedule.beat_ids:
            raise ValueError(f'unknown retained beat: {beat!r}')
        requested.add(beat)
    positions = tuple(index for index, beat in enumerate(schedule.beat_ids) if beat in requested)
    return Retention(tuple(schedule.beat_ids[index] for index in positions), positions)
