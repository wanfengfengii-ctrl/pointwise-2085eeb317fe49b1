from fractions import Fraction

from issuer.permission import GuardReadingPermission
from issuer.waveform import GuardWaveformEvidence, WaveformEvidence
from protocol.linear import span_basis


def _state_observation_rows(model, beat_count, channel_count):
    """Return C, C A, ..., C A**(beat_count-1) as public state-weight rows."""
    observed = model.C[0]
    state_rows = [observed]
    delayed_drive = []
    zero = Fraction(0)
    for _ in range(1, beat_count):
        # At delay j + 1 a drive pulse contributes C A**j B.  A zero-state model
        # has no B rows at all, so every delayed response is then an empty block.
        if model.B:
            delayed_drive.append(tuple(sum((weight * row[channel]
                                            for weight, row in zip(observed, model.B)), zero)
                                       for channel in range(channel_count)))
        else:
            delayed_drive.append(tuple(zero for _ in range(channel_count)))
        if model.A:
            observed = tuple(sum((weight * entry for weight, entry in zip(observed, column)), zero)
                             for column in zip(*model.A))
        state_rows.append(observed)
    return tuple(state_rows), tuple(delayed_drive)


def _drive_rows(model, beat_count, channels, delayed_drive):
    drive_rows = []
    future = (Fraction(0),) * channels
    for beat in range(beat_count):
        blocks = list(reversed(delayed_drive[:beat]))
        blocks.append(model.D[0])
        blocks.extend([future] * (beat_count - beat - 1))
        drive_rows.append(tuple(value for block in blocks for value in block))
    return tuple(drive_rows)


def compile_waveform(schedule, model):
    """Unroll the private dynamics into public drive and initial-state responses."""
    channels = tuple(unit.channel for unit in schedule.drive_units)
    beat_count = len(schedule.beat_ids)
    state_rows, delayed_drive = _state_observation_rows(model, beat_count, len(channels))
    drive_rows = _drive_rows(model, beat_count, len(channels), delayed_drive)

    # The basis lives in public beat coordinates and carries no state-coordinate labels.
    basis = span_basis(zip(*state_rows))
    initial_rows = tuple(tuple(vector[beat] for vector in basis) for beat in range(beat_count))
    return WaveformEvidence(schedule.beat_ids, channels, drive_rows, initial_rows)


def _project_state_vector(state_rows, vector):
    """Map a private state vector to its image across every public beat."""
    zero = Fraction(0)
    return tuple(sum((weight * value for weight, value in zip(row, vector)), zero)
                 for row in state_rows)


def compile_guard_waveform(schedule, model, permission):
    """Freeze the V2 drive relation and the initial-state permit in reading coordinates."""
    channels = tuple(unit.channel for unit in schedule.drive_units)
    beat_count = len(schedule.beat_ids)
    state_rows, delayed_drive = _state_observation_rows(model, beat_count, len(channels))
    drive_rows = _drive_rows(model, beat_count, len(channels), delayed_drive)
    origin_readings = _project_state_vector(state_rows, permission.origin)
    direction_readings = tuple(
        _project_state_vector(state_rows, direction) for direction in permission.directions)
    reading_permission = GuardReadingPermission(origin_readings, direction_readings)
    return GuardWaveformEvidence(schedule.beat_ids, channels, drive_rows, reading_permission)
