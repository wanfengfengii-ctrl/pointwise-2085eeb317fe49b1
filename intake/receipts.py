import json
from dataclasses import dataclass

from intake.provenance import ReceiptProvenance, record_provenance


@dataclass(frozen=True)
class Receipt:
    sealed_text: str
    provenance: ReceiptProvenance

    @property
    def receipt_id(self):
        return self.provenance.receipt_id


def init_receipt_storage(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS receipts (
        receipt_id INTEGER PRIMARY KEY,
        piece_id TEXT NOT NULL UNIQUE,
        checksum TEXT NOT NULL,
        sealed_text TEXT NOT NULL,
        source TEXT NOT NULL
    )''')


def _decode_row(row):
    receipt_id, piece_id, checksum, text, source = row
    provenance = record_provenance(receipt_id, piece_id, checksum, json.loads(source))
    return Receipt(text, provenance)


def get_receipt(conn, receipt_id):
    if type(receipt_id) is not int or receipt_id <= 0:
        raise ValueError('receipt ID must be a positive integer')
    if receipt_id > 2**63 - 1:
        raise KeyError(f'unknown receipt: {receipt_id}')
    row = conn.execute('''SELECT receipt_id, piece_id, checksum, sealed_text, source
                          FROM receipts WHERE receipt_id = ?''', (receipt_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown receipt: {receipt_id}')
    return _decode_row(row)


def find_by_piece_id(conn, piece_id):
    row = conn.execute('''SELECT receipt_id, piece_id, checksum, sealed_text, source
                          FROM receipts WHERE piece_id = ?''', (piece_id,)).fetchone()
    return None if row is None else _decode_row(row)


def store_receipt(conn, envelope):
    """Store a validated first delivery in the admission transaction."""
    source = envelope.body['provenance']
    cursor = conn.execute('''INSERT INTO receipts (piece_id, checksum, sealed_text, source)
                             VALUES (?, ?, ?, ?)''',
                          (envelope.piece_id, envelope.checksum, envelope.canonical_text,
                           json.dumps(source, sort_keys=True)))
    provenance = record_provenance(cursor.lastrowid, envelope.piece_id, envelope.checksum, source)
    return Receipt(envelope.canonical_text, provenance)
