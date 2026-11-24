import hashlib
import hmac
import json
from dataclasses import dataclass

from issuer.waveform import (
    GuardWaveformEvidence, WaveformEvidence, decode_guard_waveform, decode_waveform,
)
from protocol.schedule import Schedule, decode_schedule


@dataclass(frozen=True)
class EnvelopeV1:
    piece_id: str
    checksum: str
    body: dict
    schedule: Schedule
    waveform: WaveformEvidence
    canonical_text: str
    version: int = 1


@dataclass(frozen=True)
class EnvelopeV2:
    piece_id: str
    checksum: str
    body: dict
    schedule: Schedule
    waveform: GuardWaveformEvidence
    canonical_text: str
    version: int = 2

    @property
    def permission(self):
        return self.waveform.permission


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(',', ':'),
                      allow_nan=False)


def _checksum(payload):
    return hashlib.sha256(_canonical(payload).encode('ascii')).hexdigest()


def _validate_piece_id(piece_id):
    if not isinstance(piece_id, str) or not piece_id.strip():
        raise ValueError('piece ID must be nonblank text')


def _read_provenance(schedule, source):
    text_fields = {'instrument_id', 'schedule_id', 'calibration_reference'}
    if not isinstance(source, dict) or set(source) != text_fields | {'revision_id'}:
        raise ValueError('invalid piece provenance fields')
    if any(not isinstance(source[name], str) or not source[name].strip() for name in text_fields):
        raise ValueError('invalid piece provenance text')
    if type(source['revision_id']) is not int or source['revision_id'] <= 0:
        raise ValueError('invalid piece revision ID')
    if source['schedule_id'] != schedule.schedule_id:
        raise ValueError('piece provenance names a different schedule')


def _read_body_v1(body):
    if not isinstance(body, dict) or set(body) != {'schedule', 'provenance', 'waveform'}:
        raise ValueError('invalid piece body fields')
    schedule = decode_schedule(body['schedule'])
    _read_provenance(schedule, body['provenance'])
    return schedule, decode_waveform(schedule, body['waveform'])


def _read_body_v2(body):
    if not isinstance(body, dict) or set(body) != {'schedule', 'provenance', 'waveform'}:
        raise ValueError('invalid piece body fields')
    schedule = decode_schedule(body['schedule'])
    _read_provenance(schedule, body['provenance'])
    return schedule, decode_guard_waveform(schedule, body['waveform'])


def _unique_object(entries):
    result = {}
    for key, value in entries:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def _seal(version, piece_id, body):
    _validate_piece_id(piece_id)
    payload = {'version': version, 'piece_id': piece_id, 'body': body}
    payload['checksum'] = _checksum(payload)
    return _canonical(payload)


def seal_piece(piece_id, body):
    _read_body_v1(body)
    return _seal(1, piece_id, body)


def seal_guard_piece(piece_id, body):
    _read_body_v2(body)
    return _seal(2, piece_id, body)


def _read_outer(payload):
    if not isinstance(payload, dict) or set(payload) != {'version', 'piece_id', 'body', 'checksum'}:
        raise ValueError('invalid piece envelope fields')
    if type(payload['version']) is not int or payload['version'] not in (1, 2):
        raise ValueError('unsupported piece version')
    _validate_piece_id(payload['piece_id'])
    digest = payload['checksum']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid piece checksum')
    material = {field: payload[field] for field in ('version', 'piece_id', 'body')}
    if not hmac.compare_digest(_checksum(material), digest):
        raise ValueError('piece checksum mismatch')
    return payload, digest


def read_envelope(text):
    if not isinstance(text, str):
        raise ValueError('a piece must be JSON text')
    payload = json.loads(text, object_pairs_hook=_unique_object)
    payload, digest = _read_outer(payload)
    if payload['version'] != 1:
        raise ValueError('unsupported piece version')
    schedule, waveform = _read_body_v1(payload['body'])
    return EnvelopeV1(payload['piece_id'], digest, payload['body'], schedule, waveform,
                      _canonical(payload))


def read_guard_envelope(text):
    if not isinstance(text, str):
        raise ValueError('a piece must be JSON text')
    payload = json.loads(text, object_pairs_hook=_unique_object)
    payload, digest = _read_outer(payload)
    if payload['version'] != 2:
        raise ValueError('guard review requires a version 2 piece')
    schedule, waveform = _read_body_v2(payload['body'])
    return EnvelopeV2(payload['piece_id'], digest, payload['body'], schedule, waveform,
                      _canonical(payload))


def read_any_envelope(text):
    """Validate either frozen version and return its typed envelope."""
    if not isinstance(text, str):
        raise ValueError('a piece must be JSON text')
    payload = json.loads(text, object_pairs_hook=_unique_object)
    payload, digest = _read_outer(payload)
    canonical = _canonical(payload)
    if payload['version'] == 1:
        schedule, waveform = _read_body_v1(payload['body'])
        return EnvelopeV1(payload['piece_id'], digest, payload['body'], schedule, waveform,
                          canonical)
    schedule, waveform = _read_body_v2(payload['body'])
    return EnvelopeV2(payload['piece_id'], digest, payload['body'], schedule, waveform,
                      canonical)
