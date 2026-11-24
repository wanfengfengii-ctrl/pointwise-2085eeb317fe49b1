from dataclasses import dataclass
from fractions import Fraction

from issuer.permission import (
    GuardReadingPermission, decode_reading_permission, encode_reading_permission,
)
from protocol.rational import encode_matrix, read_matrix


@dataclass(frozen=True)
class WaveformEvidence:
    beat_ids: tuple[int, ...]
    channels: tuple[str, ...]
    drive_rows: tuple[tuple[Fraction, ...], ...]
    initial_rows: tuple[tuple[Fraction, ...], ...]


@dataclass(frozen=True)
class GuardWaveformEvidence:
    """V2 self-contained joint reading relation.

    ``drive_rows`` keeps the exact V1 convention (beat rows, columns ordered by beat then
    declared channel) so the piece preserves exact joint readings for every legal complete
    drive.  The frozen initial-state permit is carried separately in reading coordinates.
    """

    beat_ids: tuple[int, ...]
    channels: tuple[str, ...]
    drive_rows: tuple[tuple[Fraction, ...], ...]
    permission: GuardReadingPermission


def encode_waveform(evidence):
    return {
        'beat_ids': list(evidence.beat_ids),
        'channels': list(evidence.channels),
        'drive_rows': encode_matrix(evidence.drive_rows),
        'initial_rows': encode_matrix(evidence.initial_rows),
    }


def decode_waveform(schedule, payload):
    fields = {'beat_ids', 'channels', 'drive_rows', 'initial_rows'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid waveform fields')
    beats = payload['beat_ids']
    channels = tuple(unit.channel for unit in schedule.drive_units)
    if (not isinstance(beats, list) or any(type(beat) is not int for beat in beats)
            or tuple(beats) != schedule.beat_ids):
        raise ValueError('waveform beats do not match the schedule')
    if not isinstance(payload['channels'], list) or tuple(payload['channels']) != channels:
        raise ValueError('waveform channels do not match the schedule')
    height = len(beats)
    drive = read_matrix(payload['drive_rows'], height, height * len(channels), 'drive_rows')
    initial = payload['initial_rows']
    if not isinstance(initial, list) or len(initial) != height or not isinstance(initial[0], list):
        raise ValueError('initial_rows must contain one row per beat')
    initial = read_matrix(initial, height, len(initial[0]), 'initial_rows')
    return WaveformEvidence(schedule.beat_ids, channels, drive, initial)


def encode_guard_waveform(evidence):
    return {
        'beat_ids': list(evidence.beat_ids),
        'channels': list(evidence.channels),
        'drive_rows': encode_matrix(evidence.drive_rows),
        'permission': encode_reading_permission(evidence.permission),
    }


def decode_guard_waveform(schedule, payload):
    fields = {'beat_ids', 'channels', 'drive_rows', 'permission'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid guard waveform fields')
    beats = payload['beat_ids']
    channels = tuple(unit.channel for unit in schedule.drive_units)
    if (not isinstance(beats, list) or any(type(beat) is not int for beat in beats)
            or tuple(beats) != schedule.beat_ids):
        raise ValueError('guard waveform beats do not match the schedule')
    if not isinstance(payload['channels'], list) or tuple(payload['channels']) != channels:
        raise ValueError('guard waveform channels do not match the schedule')
    height = len(beats)
    drive = read_matrix(payload['drive_rows'], height, height * len(channels), 'drive_rows')
    permission = decode_reading_permission(height, payload['permission'])
    return GuardWaveformEvidence(schedule.beat_ids, channels, drive, permission)
