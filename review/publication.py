from intake.selection import select_receipts
from protocol.drive import validate_drive
from protocol.retention import normalize_retention
from review.observable import fix_drive
from review.prefix import earliest_distinguishing_beat
from review.report import build_report, encode_report


def publish_report(conn, report):
    body = encode_report(report)
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        conn.execute('INSERT INTO reports VALUES (?, ?)', (report.report_id, body))
        conn.execute('INSERT INTO success_receipts VALUES (?, ?)',
                     (report.success_receipt.receipt_id, report.report_id))
    return report


def review(conn, receipt_ids, drive, retained_beats, *, drive_units):
    selected = select_receipts(conn, receipt_ids)
    actual_drive = validate_drive(selected.schedule, drive, drive_units)
    retention = normalize_retention(selected.schedule, retained_beats)
    left, right = (fix_drive(evidence, actual_drive) for evidence in selected.waveforms)
    earliest = earliest_distinguishing_beat(left, right, retention)
    report = build_report(actual_drive, retention, selected.provenance, earliest)
    return publish_report(conn, report)
