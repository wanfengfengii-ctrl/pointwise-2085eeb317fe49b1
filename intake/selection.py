from dataclasses import dataclass

from intake.provenance import ReceiptProvenance
from intake.receipts import get_receipt
from issuer.envelope import read_envelope
from issuer.waveform import WaveformEvidence
from protocol.schedule import Schedule, timebase_key


@dataclass(frozen=True)
class SelectedReceipts:
    schedule: Schedule
    waveforms: tuple[WaveformEvidence, WaveformEvidence]
    provenance: tuple[ReceiptProvenance, ReceiptProvenance]


def select_receipts(conn, receipt_ids):
    if not isinstance(receipt_ids, (tuple, list)) or len(receipt_ids) != 2:
        raise ValueError('review requires an ordered pair of receipt IDs')
    left = get_receipt(conn, receipt_ids[0])
    right = get_receipt(conn, receipt_ids[1])
    left_piece = read_envelope(left.sealed_text)
    right_piece = read_envelope(right.sealed_text)
    if timebase_key(left_piece.schedule) != timebase_key(right_piece.schedule):
        raise ValueError('receipt timebases or drive declarations differ')
    return SelectedReceipts(left_piece.schedule, (left_piece.waveform, right_piece.waveform),
                            (left.provenance, right.provenance))
