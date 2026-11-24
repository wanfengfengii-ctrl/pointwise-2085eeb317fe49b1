from dataclasses import dataclass
from fractions import Fraction

from protocol.linear import has_rational_solution


@dataclass(frozen=True)
class FixedResponse:
    offsets: tuple[Fraction, ...]
    initial_rows: tuple[tuple[Fraction, ...], ...]


def fix_drive(evidence, drive):
    channels = tuple(unit.channel for unit in drive.units)
    if drive.beat_ids != evidence.beat_ids or channels != evidence.channels:
        raise ValueError('drive and waveform use different coordinates')
    vector = drive.vector
    offsets = tuple(sum((coefficient * value for coefficient, value in zip(row, vector, strict=True)),
                        Fraction(0)) for row in evidence.drive_rows)
    return FixedResponse(offsets, evidence.initial_rows)


def can_share_waveform(left, right, positions):
    coefficients = []
    right_hand_side = []
    for position in positions:
        # Each side retains its own unknowns across all selected positions.
        coefficients.append(left.initial_rows[position] +
                            tuple(-entry for entry in right.initial_rows[position]))
        right_hand_side.append(right.offsets[position] - left.offsets[position])
    return has_rational_solution(coefficients, right_hand_side)
