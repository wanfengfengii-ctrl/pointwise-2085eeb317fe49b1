import json
from dataclasses import dataclass
from uuid import uuid4

from intake.provenance import ReceiptProvenance, decode_provenance, encode_provenance
from protocol.drive import Drive
from protocol.rational import encode_matrix, read_matrix
from protocol.units import validate_drive_units


@dataclass(frozen=True)
class SuccessReceipt:
    receipt_id: str
    report_id: str


@dataclass(frozen=True)
class Report:
    report_id: str
    drive: Drive
    retained_beats: tuple[int, ...]
    evidence: tuple[ReceiptProvenance, ReceiptProvenance]
    earliest_beat: int | None
    success_receipt: SuccessReceipt

    @property
    def receipt_ids(self):
        return tuple(source.receipt_id for source in self.evidence)

    @property
    def outcome(self):
        return 'indistinguishable' if self.earliest_beat is None else 'distinguishable'


def build_report(drive, retention, evidence, earliest_beat):
    report_id = uuid4().hex
    success = SuccessReceipt(uuid4().hex, report_id)
    return Report(report_id, drive, retention.beat_ids, evidence, earliest_beat, success)


def encode_report(report):
    drive = report.drive
    return json.dumps({
        'drive': {
            'beat_ids': drive.beat_ids,
            'units': [[declaration.channel, declaration.unit] for declaration in drive.units],
            'rows': encode_matrix(drive.rows),
        },
        'retained_beats': report.retained_beats,
        'evidence': [encode_provenance(source) for source in report.evidence],
        'earliest_beat': report.earliest_beat,
    }, sort_keys=True, separators=(',', ':'))


def decode_report(report_id, body, success_id):
    payload = json.loads(body)
    stored_drive = payload['drive']
    beats = tuple(stored_drive['beat_ids'])
    units = validate_drive_units(stored_drive['units'])
    rows = read_matrix(stored_drive['rows'], len(beats), len(units), 'archived drive')
    left, right = (decode_provenance(source) for source in payload['evidence'])
    return Report(report_id, Drive(beats, units, rows), tuple(payload['retained_beats']),
                  (left, right), payload['earliest_beat'], SuccessReceipt(success_id, report_id))


def init_report_storage(conn):
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('''CREATE TABLE IF NOT EXISTS reports (
        report_id TEXT PRIMARY KEY,
        body TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS success_receipts (
        receipt_id TEXT PRIMARY KEY,
        report_id TEXT NOT NULL UNIQUE REFERENCES reports(report_id)
    )''')
