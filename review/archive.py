from review.report import decode_report


def get_report(conn, report_id):
    if not isinstance(report_id, str) or not report_id.strip():
        raise ValueError('report ID must be nonblank text')
    row = conn.execute('''SELECT reports.body, success_receipts.receipt_id
                          FROM reports JOIN success_receipts USING (report_id)
                          WHERE reports.report_id = ?''', (report_id,)).fetchone()
    if row is None:
        return None
    return decode_report(report_id, row[0], row[1])
