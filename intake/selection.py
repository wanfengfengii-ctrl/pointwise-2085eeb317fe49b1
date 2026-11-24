from dataclasses import dataclass

from intake.provenance import ReceiptProvenance
from intake.receipts import get_receipt
from issuer.envelope import read_envelope, read_guard_envelope
from issuer.waveform import GuardWaveformEvidence, WaveformEvidence
from protocol.schedule import Schedule, timebase_key


@dataclass(frozen=True)
class SelectedReceipts:
    schedule: Schedule
    waveforms: tuple[WaveformEvidence, WaveformEvidence]
    provenance: tuple[ReceiptProvenance, ReceiptProvenance]


@dataclass(frozen=True)
class SelectedGuardReceipts:
    schedule: Schedule
    waveforms: tuple[GuardWaveformEvidence, GuardWaveformEvidence]
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


def select_guard_receipts(conn, receipt_ids):
    """Select an ordered pair of V2 guard receipts; V1 pieces cannot enter guard review."""
    if not isinstance(receipt_ids, (tuple, list)) or len(receipt_ids) != 2:
        raise ValueError('guard review requires an ordered pair of receipt IDs')
    left = get_receipt(conn, receipt_ids[0])
    right = get_receipt(conn, receipt_ids[1])
    left_piece = read_guard_envelope(left.sealed_text)
    right_piece = read_guard_envelope(right.sealed_text)
    if timebase_key(left_piece.schedule) != timebase_key(right_piece.schedule):
        raise ValueError('receipt timebases or drive declarations differ')
    return SelectedGuardReceipts(
        left_piece.schedule, (left_piece.waveform, right_piece.waveform),
        (left.provenance, right.provenance))
