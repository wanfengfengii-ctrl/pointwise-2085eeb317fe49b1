from dataclasses import dataclass
from fractions import Fraction

from protocol.rational import read_rational


@dataclass(frozen=True)
class GuardPermission:
    """Initial-state permit expressed in the private state coordinates of one revision.

    The permitted initial state is ``origin + sum(coef[j] * directions[j])`` where each
    coefficient independently ranges over the closed interval [0, 1] and the same
    coefficients are shared by every beat of a whole drive run.
    """

    origin: tuple[Fraction, ...]
    directions: tuple[tuple[Fraction, ...], ...]


@dataclass(frozen=True)
class GuardReadingPermission:
    """The permit projected onto the public per-beat reading coordinates.

    The piece carries no state-coordinate labels: the issuer interprets the private
    model once and freezes only the reading-space images of the基点 and directions.
    """

    origin_readings: tuple[Fraction, ...]
    direction_readings: tuple[tuple[Fraction, ...], ...]


def read_guard_permission(state_dim, origin, directions):
    if state_dim == 0:
        if origin or any(direction for direction in directions):
            raise ValueError('zero-state models require an empty origin and no directions')
    if not isinstance(origin, (list, tuple)):
        raise ValueError('guard origin must be a rational vector')
    if len(origin) != state_dim:
        raise ValueError(
            f'guard origin must have {state_dim} entries for this model, got {len(origin)}')
    try:
        origin_values = tuple(read_rational(entry) for entry in origin)
    except ValueError as exc:
        raise ValueError('guard origin contains an invalid rational') from exc
    if not isinstance(directions, (list, tuple)) or len(directions) > 2:
        raise ValueError('guard directions must contain at most two vectors')
    direction_values = []
    for index, direction in enumerate(directions):
        if not isinstance(direction, (list, tuple)) or len(direction) != state_dim:
            raise ValueError(
                f'guard direction {index + 1} must have {state_dim} entries')
        try:
            direction_values.append(tuple(read_rational(entry) for entry in direction))
        except ValueError as exc:
            raise ValueError(f'guard direction {index + 1} contains an invalid rational') from exc
    return GuardPermission(origin_values, tuple(direction_values))


def encode_reading_permission(permission):
    return {
        'origin_readings': [str(value) for value in permission.origin_readings],
        'direction_readings': [[str(value) for value in direction]
                               for direction in permission.direction_readings],
    }


def decode_reading_permission(beat_count, payload):
    if not isinstance(payload, dict) or set(payload) != {'origin_readings', 'direction_readings'}:
        raise ValueError('invalid guard permission fields')
    raw_origin = payload['origin_readings']
    if not isinstance(raw_origin, (list, tuple)) or len(raw_origin) != beat_count:
        raise ValueError('guard origin_readings must contain one entry per beat')
    try:
        origin = tuple(read_rational(entry) for entry in raw_origin)
    except ValueError as exc:
        raise ValueError('guard origin_readings contain an invalid rational') from exc
    raw_directions = payload['direction_readings']
    if not isinstance(raw_directions, (list, tuple)) or len(raw_directions) > 2:
        raise ValueError('guard direction_readings must contain at most two vectors')
    directions = []
    for index, direction in enumerate(raw_directions):
        if not isinstance(direction, (list, tuple)) or len(direction) != beat_count:
            raise ValueError(
                f'guard direction_readings row {index + 1} must contain one entry per beat')
        try:
            directions.append(tuple(read_rational(entry) for entry in direction))
        except ValueError as exc:
            raise ValueError(
                f'guard direction_readings row {index + 1} contains an invalid rational') from exc
    return GuardReadingPermission(origin, tuple(directions))
