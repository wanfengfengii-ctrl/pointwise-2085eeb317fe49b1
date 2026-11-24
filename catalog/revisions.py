import json
from dataclasses import dataclass

from catalog.calibration import (
    CalibrationSource, decode_calibration_source, encode_calibration_source,
    validate_calibration_source,
)
from catalog.lineage import validate_parent
from catalog.model import LinearModel, decode_model, encode_model, validate_model
from protocol.schedule import get_schedule


@dataclass(frozen=True)
class Revision:
    revision_id: int
    instrument_id: str
    schedule_id: str
    model: LinearModel
    calibration: CalibrationSource
    parent_id: int | None


def init_revision_storage(conn):
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('''CREATE TABLE IF NOT EXISTS revisions (
        revision_id INTEGER PRIMARY KEY,
        instrument_id TEXT NOT NULL,
        schedule_id TEXT NOT NULL REFERENCES schedules(schedule_id),
        model TEXT NOT NULL,
        calibration TEXT NOT NULL,
        parent_id INTEGER REFERENCES revisions(revision_id)
    )''')


def get_revision(conn, revision_id):
    if type(revision_id) is not int or revision_id <= 0:
        raise ValueError('revision ID must be a positive integer')
    row = conn.execute('''SELECT instrument_id, schedule_id, model, calibration, parent_id
                          FROM revisions WHERE revision_id = ?''', (revision_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown revision: {revision_id}')
    instrument_id, schedule_id, model, calibration, parent_id = row
    schedule = get_schedule(conn, schedule_id)
    return Revision(revision_id, instrument_id, schedule_id,
                    decode_model(schedule, json.loads(model)),
                    decode_calibration_source(json.loads(calibration)), parent_id)


def register_revision(conn, instrument_id, schedule_id, model, calibration, *, parent_id=None):
    if not isinstance(instrument_id, str) or not instrument_id.strip():
        raise ValueError('instrument ID must be nonblank text')
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        schedule = get_schedule(conn, schedule_id)
        model = validate_model(schedule, model)
        calibration = validate_calibration_source(calibration)
        parent_instrument = None
        if type(parent_id) is int and 0 < parent_id <= 2**63 - 1:
            parent = conn.execute('SELECT instrument_id FROM revisions WHERE revision_id = ?',
                                  (parent_id,)).fetchone()
            if parent is not None:
                parent_instrument = parent[0]
        validate_parent(parent_id, instrument_id, parent_instrument)
        cursor = conn.execute('''INSERT INTO revisions
            (instrument_id, schedule_id, model, calibration, parent_id) VALUES (?, ?, ?, ?, ?)''',
            (instrument_id, schedule_id, json.dumps(encode_model(model)),
             json.dumps(encode_calibration_source(calibration)), parent_id))
        result = Revision(cursor.lastrowid, instrument_id, schedule_id, model, calibration, parent_id)
    return result
