from intake.selection import select_guard_receipts, select_receipts
from protocol.drive import validate_drive
from protocol.rational import read_rational
from protocol.retention import normalize_retention
from review.guard_observable import compute_margin, fix_guard_drive
from review.observable import fix_drive
from review.prefix import earliest_distinguishing_beat
from review.report import (
    build_guard_report, build_report, encode_guard_report, encode_report,
)


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


def publish_guard_report(conn, report):
    body = encode_guard_report(report)
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        conn.execute('INSERT INTO guard_reports VALUES (?, ?)', (report.report_id, body))
        conn.execute('INSERT INTO guard_success_receipts VALUES (?, ?)',
                     (report.success_receipt.receipt_id, report.report_id))
    return report


def review_guard(conn, receipt_ids, drive, retained_beats, minimum_margin, *, drive_units):
    """Sign the discriminator-margin report for an ordered pair of V2 guard pieces."""
    threshold = read_rational(minimum_margin)
    if threshold <= 0:
        raise ValueError('guard minimum margin must be a positive rational')
    selected = select_guard_receipts(conn, receipt_ids)
    actual_drive = validate_drive(selected.schedule, drive, drive_units)
    retention = normalize_retention(selected.schedule, retained_beats)
    if not retention.positions:
        raise ValueError('guard review requires at least one retained beat')
    left, right = (fix_guard_drive(evidence, actual_drive).project(retention.positions)
                   for evidence in selected.waveforms)
    result = compute_margin(left, right)
    report = build_guard_report(actual_drive, retention, selected.provenance, threshold, result)
    return publish_guard_report(conn, report)
