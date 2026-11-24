from uuid import uuid4

from catalog.revisions import get_revision
from issuer.behavior import compile_waveform
from issuer.disclosure import make_disclosure
from issuer.envelope import seal_piece
from issuer.waveform import encode_waveform
from protocol.schedule import get_schedule


def init_issue_storage(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS issues (
        piece_id TEXT PRIMARY KEY,
        revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
        sealed_text TEXT NOT NULL
    )''')


def issue(conn, revision_id):
    revision = get_revision(conn, revision_id)
    schedule = get_schedule(conn, revision.schedule_id)
    waveform = compile_waveform(schedule, revision.model)
    body = {
        'schedule': schedule.to_payload(),
        'provenance': make_disclosure(revision),
        'waveform': encode_waveform(waveform),
    }
    piece_id = uuid4().hex
    text = seal_piece(piece_id, body)
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        conn.execute('INSERT INTO issues VALUES (?, ?, ?)', (piece_id, revision_id, text))
    return text
