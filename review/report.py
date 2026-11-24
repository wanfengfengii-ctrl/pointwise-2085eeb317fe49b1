import json
from dataclasses import dataclass
from fractions import Fraction
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


@dataclass(frozen=True)
class GuardRule:
    weights: tuple[Fraction, ...]
    left_max: Fraction
    right_min: Fraction
    threshold: Fraction


@dataclass(frozen=True)
class GuardReport:
    report_id: str
    drive: Drive
    retained_beats: tuple[int, ...]
    evidence: tuple[ReceiptProvenance, ReceiptProvenance]
    minimum_margin: Fraction
    margin: Fraction
    waveforms: tuple[tuple[Fraction, ...], tuple[Fraction, ...]]
    rule: GuardRule | None
    claimable: bool
    success_receipt: SuccessReceipt

    @property
    def receipt_ids(self):
        return tuple(source.receipt_id for source in self.evidence)


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


def build_guard_report(drive, retention, evidence, minimum_margin, result):
    report_id = uuid4().hex
    success = SuccessReceipt(uuid4().hex, report_id)
    if result.margin == 0:
        rule = None
    else:
        rule = GuardRule(result.weights, result.left_max, result.right_min, result.threshold)
    claimable = result.margin >= minimum_margin
    return GuardReport(report_id, drive, retention.beat_ids, evidence, minimum_margin,
                       result.margin, (result.left_waveform, result.right_waveform), rule,
                       claimable, success)


def encode_guard_report(report):
    drive = report.drive
    payload = {
        'report_kind': 'guard',
        'drive': {
            'beat_ids': list(drive.beat_ids),
            'units': [[declaration.channel, declaration.unit] for declaration in drive.units],
            'rows': encode_matrix(drive.rows),
        },
        'retained_beats': list(report.retained_beats),
        'evidence': [encode_provenance(source) for source in report.evidence],
        'minimum_margin': str(report.minimum_margin),
        'margin': str(report.margin),
        'waveforms': [[str(value) for value in vector] for vector in report.waveforms],
        'rule': None,
        'claimable': report.claimable,
    }
    if report.rule is not None:
        payload['rule'] = {
            'weights': [str(value) for value in report.rule.weights],
            'left_max': str(report.rule.left_max),
            'right_min': str(report.rule.right_min),
            'threshold': str(report.rule.threshold),
        }
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def _read_fraction_vector(values, field, expected_length):
    from protocol.rational import read_rational
    if not isinstance(values, (list, tuple)) or len(values) != expected_length:
        raise ValueError(f'archived guard {field} has the wrong length')
    return tuple(read_rational(value) for value in values)


def decode_guard_report(report_id, body, success_id):
    payload = json.loads(body)
    stored_drive = payload['drive']
    beats = tuple(stored_drive['beat_ids'])
    units = validate_drive_units(stored_drive['units'])
    rows = read_matrix(stored_drive['rows'], len(beats), len(units), 'archived drive')
    left, right = (decode_provenance(source) for source in payload['evidence'])
    retained = tuple(payload['retained_beats'])
    minimum_margin = _read_fraction_vector([payload['minimum_margin']], 'minimum_margin', 1)[0]
    margin = _read_fraction_vector([payload['margin']], 'margin', 1)[0]
    if len(payload['waveforms']) != 2:
        raise ValueError('archived guard report must hold two waveforms')
    waveforms = tuple(_read_fraction_vector(vector, 'waveforms', len(retained))
                      for vector in payload['waveforms'])
    rule = None
    if payload['rule'] is not None:
        rule_payload = payload['rule']
        rule = GuardRule(
            _read_fraction_vector(rule_payload['weights'], 'weights', len(retained)),
            _read_fraction_vector([rule_payload['left_max']], 'left_max', 1)[0],
            _read_fraction_vector([rule_payload['right_min']], 'right_min', 1)[0],
            _read_fraction_vector([rule_payload['threshold']], 'threshold', 1)[0],
        )
    return GuardReport(report_id, Drive(beats, units, rows), retained, (left, right),
                       minimum_margin, margin, waveforms, rule, bool(payload['claimable']),
                       SuccessReceipt(success_id, report_id))


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
    conn.execute('''CREATE TABLE IF NOT EXISTS guard_reports (
        report_id TEXT PRIMARY KEY,
        body TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS guard_success_receipts (
        receipt_id TEXT PRIMARY KEY,
        report_id TEXT NOT NULL UNIQUE REFERENCES guard_reports(report_id)
    )''')
