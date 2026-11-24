import hashlib
import json

from intake.admission import admit
from intake.receipts import get_receipt
from issuer.envelope import read_envelope, seal_piece
from issuer.freeze import issue
from tests.support import LabCase


def with_checksum(payload):
    material = {field: payload[field] for field in ('version', 'piece_id', 'body')}
    canonical = json.dumps(material, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    payload['checksum'] = hashlib.sha256(canonical.encode('ascii')).hexdigest()
    return json.dumps(payload)


class IntakeTests(LabCase):
    def test_duplicate_and_conflict(self):
        left = self.receive(self.revision('reference'))
        right_text = issue(self.bench, self.revision('replacement').revision_id)
        first = admit(self.center, right_text)
        self.assertEqual(admit(self.center, right_text), first)
        self.assertEqual(admit(self.center, json.dumps(json.loads(right_text), indent=2)), first)
        original = read_envelope(right_text)
        alternate = read_envelope(left.sealed_text).body
        with self.assertRaisesRegex(ValueError, 'piece identity conflict'):
            admit(self.center, seal_piece(original.piece_id, alternate))
        self.assertEqual(get_receipt(self.center, first.receipt_id), first)
        self.assertEqual(self.center.execute('SELECT count(*) FROM receipts').fetchone()[0], 2)
        self.stop_source()
        report = self.decide((left, first))
        self.assertEqual(report.earliest_beat, 2)
        self.assertEqual(report.evidence, (left.provenance, first.provenance))
        self.assertEqual(report.evidence[1].checksum, original.checksum)

    def test_invalid_envelope(self):
        original = issue(self.bench, self.revision('reference').revision_id)
        first = admit(self.center, original)
        bad_seal = json.loads(original)
        bad_seal['body']['provenance']['calibration_reference'] = 'changed after sealing'
        bad_dimensions = json.loads(original)
        bad_dimensions['body']['waveform']['drive_rows'][1] = ['1']
        bad_rational = json.loads(original)
        bad_rational['body']['waveform']['initial_rows'][1][0] = '1/0'
        bad_order = json.loads(original)
        bad_order['body']['waveform']['beat_ids'] = [2, 1]
        bad_channel = json.loads(original)
        bad_channel['body']['waveform']['channels'] = ['other']
        bad_source = json.loads(original)
        bad_source['body']['provenance']['schedule_id'] = 'different'
        bad_version = dict(json.loads(original), version=True)
        for label, text in (
            ('invalid JSON', '{'),
            ('duplicate fields', original[:-1] + ',"version":1}'),
            ('altered seal', json.dumps(bad_seal)),
            ('row dimensions', with_checksum(bad_dimensions)),
            ('rational coefficient', with_checksum(bad_rational)),
            ('beat order', with_checksum(bad_order)),
            ('channel alignment', with_checksum(bad_channel)),
            ('source schedule', with_checksum(bad_source)),
            ('unsupported version', with_checksum(bad_version)),
        ):
            with self.subTest(envelope_error=label):
                with self.assertRaises(ValueError):
                    admit(self.center, text)
        self.assertEqual(get_receipt(self.center, first.receipt_id), first)
        self.assertEqual(self.center.execute('SELECT count(*) FROM receipts').fetchone()[0], 1)
