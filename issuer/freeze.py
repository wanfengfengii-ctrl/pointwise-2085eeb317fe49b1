from uuid import uuid4

from catalog.revisions import get_revision
from issuer.behavior import compile_guard_waveform, compile_waveform
from issuer.disclosure import make_disclosure
from issuer.envelope import seal_guard_piece, seal_piece
from issuer.permission import read_guard_permission
from issuer.waveform import encode_guard_waveform, encode_waveform
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


def issue_guard(conn, revision_id, origin, directions):
    """Issue a self-contained V2 station piece with a frozen initial-state permit.

    ``origin`` is a rational vector with the revision's state dimension and ``directions``
    is a list of zero to two vectors of the same dimension.  Coefficients on the
    directions are independently chosen from [0, 1] and are shared across every beat.
    The private model, calibration rows and state coordinates remain on the bench.
    """
    revision = get_revision(conn, revision_id)
    schedule = get_schedule(conn, revision.schedule_id)
    state_dim = len(revision.model.A)
    permission = read_guard_permission(state_dim, origin, directions)
    waveform = compile_guard_waveform(schedule, revision.model, permission)
    body = {
        'schedule': schedule.to_payload(),
        'provenance': make_disclosure(revision),
        'waveform': encode_guard_waveform(waveform),
    }
    piece_id = uuid4().hex
    text = seal_guard_piece(piece_id, body)
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        conn.execute('INSERT INTO issues VALUES (?, ?, ?)', (piece_id, revision_id, text))
    return text
