from fractions import Fraction

from issuer.waveform import WaveformEvidence
from protocol.linear import span_basis


def compile_waveform(schedule, model):
    """Unroll the private dynamics into public drive and initial-state responses."""
    channels = tuple(unit.channel for unit in schedule.drive_units)
    beat_count = len(schedule.beat_ids)
    zero = Fraction(0)
    observed = model.C[0]
    state_rows = [observed]
    delayed_drive = []
    for _ in range(1, beat_count):
        # At delay j + 1 a drive pulse contributes C A**j B.
        delayed_drive.append(tuple(sum((weight * row[channel]
                                        for weight, row in zip(observed, model.B)), zero)
                                   for channel in range(len(channels))))
        observed = tuple(sum((weight * entry for weight, entry in zip(observed, column)), zero)
                         for column in zip(*model.A))
        state_rows.append(observed)

    drive_rows = []
    future = (zero,) * len(channels)
    for beat in range(beat_count):
        blocks = list(reversed(delayed_drive[:beat]))
        blocks.append(model.D[0])
        blocks.extend([future] * (beat_count - beat - 1))
        drive_rows.append(tuple(value for block in blocks for value in block))

    # The basis lives in public beat coordinates and carries no state-coordinate labels.
    basis = span_basis(zip(*state_rows))
    initial_rows = tuple(tuple(vector[beat] for vector in basis) for beat in range(beat_count))
    return WaveformEvidence(schedule.beat_ids, channels, tuple(drive_rows), initial_rows)
