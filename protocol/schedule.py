import json
from dataclasses import dataclass
from fractions import Fraction

from protocol.rational import encode_rational, read_rational
from protocol.units import DriveUnit, validate_drive_units


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    beat_ids: tuple[int, ...]
    times: tuple[Fraction, ...]
    drive_units: tuple[DriveUnit, ...]

    def to_payload(self):
        return {
            'schedule_id': self.schedule_id,
            'beats': [[beat, encode_rational(time)]
                      for beat, time in zip(self.beat_ids, self.times)],
            'drive_units': [[entry.channel, entry.unit] for entry in self.drive_units],
        }


def decode_schedule(payload):
    if not isinstance(payload, dict) or set(payload) != {'schedule_id', 'beats', 'drive_units'}:
        raise ValueError('invalid schedule fields')
    schedule_id = payload['schedule_id']
    if not isinstance(schedule_id, str) or not schedule_id.strip():
        raise ValueError('schedule ID must be nonblank text')
    beats = payload['beats']
    if not isinstance(beats, (tuple, list)) or not 2 <= len(beats) <= 6:
        raise ValueError('a schedule must contain 2 to 6 beats')
    beat_ids = []
    times = []
    for entry in beats:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError('expected a beat ID and time pair')
        beat, raw_time = entry
        if type(beat) is not int or beat <= 0 or beat in beat_ids:
            raise ValueError('beat IDs must be unique positive integers')
        time = read_rational(raw_time)
        if times and time <= times[-1]:
            raise ValueError('beat times must be strictly increasing')
        beat_ids.append(beat)
        times.append(time)
    units = validate_drive_units(payload['drive_units'])
    return Schedule(schedule_id, tuple(beat_ids), tuple(times), units)


def timebase_key(schedule):
    return schedule.beat_ids, schedule.times, schedule.drive_units


def init_schedule_storage(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS schedules (
        schedule_id TEXT PRIMARY KEY, payload TEXT NOT NULL
    )''')


def get_schedule(conn, schedule_id):
    if not isinstance(schedule_id, str) or not schedule_id.strip():
        raise ValueError('schedule ID must be nonblank text')
    row = conn.execute('SELECT payload FROM schedules WHERE schedule_id = ?',
                       (schedule_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown schedule: {schedule_id}')
    return decode_schedule(json.loads(row[0]))


def register_schedule(conn, schedule_id, beats, drive_units):
    candidate = decode_schedule({
        'schedule_id': schedule_id, 'beats': beats, 'drive_units': drive_units,
    })
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        try:
            existing = get_schedule(conn, schedule_id)
        except KeyError:
            conn.execute('INSERT INTO schedules VALUES (?, ?)',
                         (schedule_id, json.dumps(candidate.to_payload())))
            result = candidate
        else:
            if existing != candidate:
                raise ValueError(f'schedule identity conflict: {schedule_id}')
            result = existing
    return result
