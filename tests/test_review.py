import json
from fractions import Fraction

from catalog.revisions import register_revision
from review.archive import get_report
from review.publication import review
from tests.support import LabCase, PULSE, UNITS, ZERO


class ReviewTests(LabCase):
    def test_pulse_prefix(self):
        pair = self.pulse_receipts()
        self.stop_source()
        report = self.decide(pair)
        self.assertEqual(report.earliest_beat, 2,
                         'WAVE_PREFIX_MISSED: the first shared reading fixes t=s, but the second needs t=s+2')
        self.assertEqual(report.outcome, 'distinguishable')
        self.assertEqual(report.retained_beats, (1, 2))
        self.assertEqual(report.drive.rows, ((Fraction(1),), (Fraction(0),)))
        self.assertEqual(report.evidence, tuple(receipt.provenance for receipt in pair))
        self.assertEqual(report.success_receipt.report_id, report.report_id)
        archived = get_report(self.center, report.report_id)
        self.assertEqual(archived, report)
        self.assertEqual(self.report_counts(), (1, 1))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v4', 'input': {'drive': PULSE, 'retained_beats': [1, 2]},
            'expected': 2, 'actual': report.earliest_beat,
            'downstream_expected': True, 'downstream_actual': archived == report,
            'code_paths': ['issuer/behavior.py', 'intake/admission.py', 'review/prefix.py',
                           'review/observable.py', 'review/publication.py', 'review/archive.py'],
            'oracle': 'Equality in the first reading fixes t=s, contradicting equality in the second.',
        }, sort_keys=True))

    def test_missing_first_sample(self):
        pair = self.pulse_receipts()
        self.stop_source()
        report = self.decide(pair, retained=[2])
        self.assertEqual(report.retained_beats, (2,))
        self.assertIsNone(report.earliest_beat)
        self.assertEqual(report.outcome, 'indistinguishable')
        self.assertEqual(get_report(self.center, report.report_id), report)

    def test_first_sample_only(self):
        pair = self.pulse_receipts()
        self.stop_source()
        self.assertIsNone(self.decide(pair, retained=[1]).earliest_beat)

    def test_empty_retention(self):
        pair = self.pulse_receipts()
        self.stop_source()
        report = self.decide(pair, retained=set())
        self.assertIsNone(report.earliest_beat)
        self.assertEqual(report.retained_beats, ())
        self.assertEqual(get_report(self.center, report.report_id), report)

    def test_zero_drive(self):
        pair = self.pulse_receipts()
        self.stop_source()
        self.assertIsNone(self.decide(pair, drive=ZERO).earliest_beat)

    def test_intersecting_responses(self):
        pair = []
        for instrument, transition in (('steady', 1), ('decays', 0)):
            revision = register_revision(
                self.bench, instrument, 'pulse',
                {'A': [[transition]], 'B': [[0]], 'C': [[1]], 'D': [[0]]},
                {'reference': f'CAL/{instrument}', 'rows': []},
            )
            pair.append(self.receive(revision))
        self.stop_source()
        report = self.decide(pair)
        # (s,s) and (t,0) share (0,0) despite having different possible waveforms.
        self.assertIsNone(report.earliest_beat)
        self.assertEqual(report.receipt_ids, tuple(receipt.receipt_id for receipt in pair))

    def test_sparse_prefix(self):
        schedule = self.make_schedule('sparse', ((4, 0), (9, '1/2'), (17, 1), (25, 2)))
        pair = [self.receive(self.revision(name, schedule=schedule))
                for name in ('reference', 'replacement')]
        self.stop_source()
        actual = {25: {'coil': 0}, 17: {'coil': 0}, 9: {'coil': '1/2'}, 4: {'coil': 0}}
        report = self.decide(pair, actual, [25, 4, 25])
        # The pulse at unretained beat 9 still changes the later observed state.
        self.assertEqual(report.earliest_beat, 25)
        self.assertEqual(report.retained_beats, (4, 25))
        self.assertEqual(report.drive.rows, ((0,), (Fraction(1, 2),), (0,), (0,)))

    def test_multichannel_six_beats(self):
        beats = (10, 20, 40, 45, 60, 80)
        units = [('coil', 'V'), ('trim', 'mV')]
        self.make_schedule('six', tuple(zip(beats, range(6))), units)
        pair = []
        for gain in ('1/2', '-1/2'):
            revision = register_revision(self.bench, 'direct', 'six',
                                         {'A': [], 'B': [], 'C': [[]], 'D': [[2, gain]]},
                                         {'reference': f'CAL/direct/{gain}', 'rows': []})
            pair.append(self.receive(revision))
        self.stop_source()
        actual = {beat: {'trim': '1/2' if beat == 45 else 0, 'coil': '1/3'} for beat in beats}
        report = self.decide(pair, actual, sorted(beats, reverse=True), units=list(reversed(units)))
        self.assertEqual(report.earliest_beat, 45)
        self.assertEqual(report.retained_beats, beats)
        self.assertEqual(report.drive.rows[3], (Fraction(1, 3), Fraction(1, 2)))

    def test_wrong_clock(self):
        other = self.make_schedule('other', ((1, 0), (2, 1), (3, 2)))
        left = self.receive(self.revision('reference'))
        right = self.receive(self.revision('replacement', schedule=other))
        self.stop_source()
        with self.assertRaisesRegex(ValueError, 'timebases'):
            self.decide((left, right))
        self.assertEqual(self.report_counts(), (0, 0))

    def test_same_length_clock(self):
        other = self.make_schedule('other', ((1, 0), (2, 2)))
        left = self.receive(self.revision('reference'))
        right = self.receive(self.revision('replacement', schedule=other))
        self.stop_source()
        with self.assertRaisesRegex(ValueError, 'timebases'):
            self.decide((left, right))
        self.assertEqual(self.report_counts(), (0, 0))

    def test_equivalent_clock_keeps_ordered_provenance(self):
        other = self.make_schedule('alternate name', ((1, '0/4'), (2, '8/8')))
        left = self.receive(self.revision('reference'))
        right = self.receive(self.revision('replacement', schedule=other))
        self.stop_source()
        report = self.decide((right, left))
        self.assertEqual(report.earliest_beat, 2)
        self.assertEqual(report.evidence, (right.provenance, left.provenance))
        self.assertEqual(tuple(source.schedule_id for source in report.evidence), ('alternate name', 'pulse'))

    def test_incompatible_drive_unit(self):
        other = self.make_schedule('millivolts', units=[('coil', 'mV')])
        left = self.receive(self.revision('reference'))
        right = self.receive(self.revision('replacement', schedule=other))
        self.stop_source()
        with self.assertRaisesRegex(ValueError, 'drive declarations'):
            self.decide((left, right))
        self.assertEqual(self.report_counts(), (0, 0))

    def test_unknown_receipt(self):
        left, _ = self.pulse_receipts()
        self.stop_source()
        with self.assertRaisesRegex(KeyError, 'unknown receipt'):
            review(self.center, (left.receipt_id, 999), PULSE, [1, 2], drive_units=UNITS)
        with self.assertRaises(ValueError):
            review(self.center, (left.receipt_id,), PULSE, [1, 2], drive_units=UNITS)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_invalid_drive(self):
        pair = self.pulse_receipts()
        self.stop_source()
        for drive, units in (
            ({1: {'coil': 1}}, UNITS),
            ({True: {'coil': 1}, 2: {'coil': 0}}, UNITS),
            ({1: {'coil': 1, 'spare': 0}, 2: {'coil': 0}}, UNITS),
            ({1: {'coil': None}, 2: {'coil': 0}}, UNITS),
            ({1: {'coil': '1/0'}, 2: {'coil': 0}}, UNITS),
            ({1: {'coil': 0.25}, 2: {'coil': 0}}, UNITS),
            (PULSE, [('coil', 'mV')]),
            (PULSE, [('coil', 'V'), ('coil', 'V')]),
        ):
            with self.subTest(drive=drive, units=units):
                with self.assertRaises(ValueError):
                    self.decide(pair, drive, units=units)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_invalid_retention(self):
        pair = self.pulse_receipts()
        self.stop_source()
        original = self.decide(pair)
        for beats in ([1, 3], [True], '2', None):
            with self.subTest(beats=beats):
                with self.assertRaises(ValueError):
                    self.decide(pair, retained=beats)
        self.assertEqual(self.report_counts(), (1, 1))
        self.assertEqual(get_report(self.center, original.report_id), original)
