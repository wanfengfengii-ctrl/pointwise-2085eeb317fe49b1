from intake.receipts import find_by_piece_id, store_receipt
from issuer.envelope import read_envelope


def admit(conn, text):
    envelope = read_envelope(text)
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        existing = find_by_piece_id(conn, envelope.piece_id)
        if existing is None:
            receipt = store_receipt(conn, envelope)
        else:
            if existing.sealed_text != envelope.canonical_text:
                raise ValueError(f'piece identity conflict: {envelope.piece_id}')
            receipt = existing
    return receipt
