from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationSource:
    reference: str
    rows: tuple[tuple[str, ...], ...] = ()


def validate_calibration_source(source):
    if isinstance(source, CalibrationSource):
        reference, rows = source.reference, source.rows
    elif isinstance(source, dict) and set(source) == {'reference', 'rows'}:
        reference, rows = source['reference'], source['rows']
    else:
        raise ValueError('expected a calibration reference and rows')
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError('calibration reference must be nonblank text')
    if not isinstance(rows, (tuple, list)):
        raise ValueError('calibration rows must be a sequence')
    copied_rows = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or any(not isinstance(cell, str) for cell in row):
            raise ValueError('calibration row cells must be text')
        copied_rows.append(tuple(row))
    return CalibrationSource(reference, tuple(copied_rows))


def encode_calibration_source(source):
    return {'reference': source.reference, 'rows': [list(row) for row in source.rows]}


def decode_calibration_source(payload):
    return validate_calibration_source(payload)
