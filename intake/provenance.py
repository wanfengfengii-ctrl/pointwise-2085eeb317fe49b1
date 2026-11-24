from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReceiptProvenance:
    receipt_id: int
    piece_id: str
    checksum: str
    instrument_id: str
    revision_id: int
    schedule_id: str
    calibration_reference: str


def record_provenance(receipt_id, piece_id, checksum, source):
    return ReceiptProvenance(receipt_id, piece_id, checksum, source['instrument_id'],
                             source['revision_id'], source['schedule_id'],
                             source['calibration_reference'])


def encode_provenance(provenance):
    return asdict(provenance)


def decode_provenance(payload):
    return ReceiptProvenance(**payload)
