from dataclasses import dataclass
from fractions import Fraction

from protocol.rational import encode_matrix, read_matrix


Matrix = tuple[tuple[Fraction, ...], ...]


@dataclass(frozen=True)
class LinearModel:
    A: Matrix
    B: Matrix
    C: Matrix
    D: Matrix


def validate_model(schedule, model):
    if isinstance(model, LinearModel):
        model = {name: getattr(model, name) for name in ('A', 'B', 'C', 'D')}
    if not isinstance(model, dict) or set(model) != {'A', 'B', 'C', 'D'}:
        raise ValueError('model must contain A, B, C and D')
    transition = model['A']
    if not isinstance(transition, (list, tuple)):
        raise ValueError('A must be a matrix')
    states = len(transition)
    channels = len(schedule.drive_units)
    return LinearModel(
        read_matrix(transition, states, states, 'A'),
        read_matrix(model['B'], states, channels, 'B'),
        read_matrix(model['C'], 1, states, 'C'),
        read_matrix(model['D'], 1, channels, 'D'),
    )


def encode_model(model):
    return {name: encode_matrix(getattr(model, name)) for name in ('A', 'B', 'C', 'D')}


def decode_model(schedule, payload):
    return validate_model(schedule, payload)
