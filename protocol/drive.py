from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from protocol.rational import read_rational
from protocol.units import DriveUnit, check_drive_units


@dataclass(frozen=True)
class Drive:
    beat_ids: tuple[int, ...]
    units: tuple[DriveUnit, ...]
    rows: tuple[tuple[Fraction, ...], ...]

    @property
    def vector(self):
        return tuple(value for row in self.rows for value in row)


def validate_drive(schedule, samples, drive_units):
    check_drive_units(schedule.drive_units, drive_units)
    if not isinstance(samples, Mapping) or any(type(beat) is not int for beat in samples):
        raise ValueError('drive must be indexed by integer beat ID')
    if set(samples) != set(schedule.beat_ids):
        raise ValueError('drive must cover exactly the scheduled beats')
    channels = tuple(unit.channel for unit in schedule.drive_units)
    expected = set(channels)
    rows = []
    for beat in schedule.beat_ids:
        row = samples[beat]
        if not isinstance(row, Mapping) or set(row) != expected:
            raise ValueError(f'drive channels do not match at beat {beat}')
        rows.append(tuple(read_rational(row[channel]) for channel in channels))
    return Drive(schedule.beat_ids, schedule.drive_units, tuple(rows))
