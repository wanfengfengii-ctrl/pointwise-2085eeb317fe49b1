import json
import sqlite3
from fractions import Fraction

from intake.admission import admit
from intake.receipts import get_receipt
from issuer.envelope import read_any_envelope, read_envelope, read_guard_envelope
from issuer.freeze import issue, issue_guard
from review.archive import get_guard_report, get_report
from review.publication import review, review_guard
from tests.support import LabCase, init_bench, init_center


class GuardLabCase(LabCase):
    def guard_sample(self):
        return json.loads((self.sample_path()).read_text(encoding='utf-8'))

    @staticmethod
    def sample_path():
        from pathlib import Path
        return Path(__file__).resolve().parents[1] / 'samples' / 'guard.json'

    def register_guard_case(self, sample):
        from protocol.schedule import register_schedule
        schedule = register_schedule(self.bench, **sample['schedule'])
        revisions = []
        for side in sample['sides']:
            parent = revisions[-1].revision_id if revisions else None
            revision = self.bench_register(sample['instrument'], schedule.schedule_id,
                                           side, parent)
            revisions.append(revision)
        return revisions

    def bench_register(self, instrument, schedule_id, side, parent):
        from catalog.revisions import register_revision
        return register_revision(self.bench, instrument, schedule_id,
                                 **side['revision'], parent_id=parent)

    def issue_sides(self, revisions, sample):
        return tuple(
            issue_guard(self.bench, revision.revision_id, side['origin'], side['directions'])
            for revision, side in zip(revisions, sample['sides']))

    def admit_guard(self, pieces):
        return tuple(admit(self.center, piece) for piece in pieces)

    def guard_decide(self, receipts, sample, *, retained=None, minimum='1/2'):
        drive = {int(beat): values for beat, values in sample['drive'].items()}
        units = sample['schedule']['drive_units']
        return review_guard(self.center, tuple(item.receipt_id for item in receipts),
                            drive, sample['retained_beats'] if retained is None else retained,
                            minimum, drive_units=units)

    def guard_counts(self):
        reports = self.center.execute('SELECT count(*) FROM guard_reports').fetchone()[0]
        receipts = self.center.execute('SELECT count(*) FROM guard_success_receipts').fetchone()[0]
        return reports, receipts


class GuardIssueTests(GuardLabCase):
    def test_v2_envelope_is_self_contained_and_keeps_the_private_model(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        text = issue_guard(self.bench, revisions[0].revision_id,
                           sample['sides'][0]['origin'], sample['sides'][0]['directions'])
        envelope = read_guard_envelope(text)
        self.assertEqual(envelope.version, 2)
        self.assertEqual(envelope.body.keys(), {'schedule', 'provenance', 'waveform'})
        self.assertEqual(set(envelope.waveform.permission.direction_readings[0]),
                         {Fraction(1)})
        # Reading-space permit: state coordinates and calibration rows never leave the bench.
        self.assertNotIn('bench-only-left', text)
        self.assertNotIn('initial_rows', text)
        self.assertEqual(envelope.waveform.permission.origin_readings, (Fraction(0), Fraction(0)))
        self.assertEqual(envelope.waveform.permission.direction_readings,
                         ((Fraction(1), Fraction(1)), (Fraction(1), Fraction(-1))))
        self.assertEqual(self.bench.execute(
            'SELECT revision_id FROM issues WHERE piece_id = ?',
            (envelope.piece_id,)).fetchone(), (revisions[0].revision_id,))

    def test_zero_state_permit_is_empty(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        text = issue_guard(self.bench, revisions[1].revision_id, [], [])
        envelope = read_guard_envelope(text)
        self.assertEqual(envelope.waveform.permission.origin_readings, (Fraction(0), Fraction(0)))
        self.assertEqual(envelope.waveform.permission.direction_readings, ())
        # D alone fixes the readings: drive rows are the identity on the single channel.
        self.assertEqual(envelope.waveform.drive_rows,
                         ((Fraction(1), Fraction(0)), (Fraction(0), Fraction(1))))

    def test_permit_validation(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        revision = revisions[0].revision_id
        for origin, directions in (
            ([0], [[1, 0]]),                       # wrong origin dimension
            ([0, 0], [[1]]),                       # wrong direction dimension
            ([0, 0], [[1, 0], [0]]),               # ragged direction table
            ('0,0', [[1, 0]]),                     # origin is not a vector
        ):
            with self.subTest(origin=origin, directions=directions):
                with self.assertRaises(ValueError):
                    issue_guard(self.bench, revision, origin, directions)
        three = [[1, 0], [0, 1], [1, 1]]
        with self.assertRaisesRegex(ValueError, 'at most two'):
            issue_guard(self.bench, revision, [0, 0], three)
        with self.assertRaisesRegex(ValueError, 'invalid rational'):
            issue_guard(self.bench, revision, [0, '1/0'], [[1, 0]])
        # Zero vector and linearly dependent directions are explicitly allowed.
        issue_guard(self.bench, revision, [0, 0], [[0, 0], [2, 2]])
        # The zero-state revision rejects any non-empty permit.
        with self.assertRaisesRegex(ValueError, 'zero-state'):
            issue_guard(self.bench, revisions[1].revision_id, [0], [])

    def test_unknown_revision_raises_keyerror(self):
        with self.assertRaises(KeyError):
            issue_guard(self.bench, 999, [], [])
        self.assertEqual(self.bench.execute('SELECT count(*) FROM issues').fetchone()[0], 0)


class GuardAdmissionTests(GuardLabCase):
    def test_admit_accepts_both_versions_and_canonical_repost(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        v2 = issue_guard(self.bench, revisions[0].revision_id,
                         sample['sides'][0]['origin'], sample['sides'][0]['directions'])
        first = admit(self.center, v2)
        # Whitespace and key order changes still reuse the first receipt.
        self.assertEqual(
            admit(self.center, json.dumps(json.loads(v2), indent=2)).receipt_id,
            first.receipt_id)
        self.assertEqual(read_any_envelope(first.sealed_text).version, 2)
        v1 = issue(self.bench, revisions[0].revision_id)
        v1_receipt = admit(self.center, v1)
        self.assertEqual(read_envelope(v1_receipt.sealed_text).version, 1)
        self.assertNotEqual(v1_receipt.receipt_id, first.receipt_id)

    def test_same_piece_id_different_body_or_version_rejected(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        v2 = issue_guard(self.bench, revisions[0].revision_id,
                         sample['sides'][0]['origin'], sample['sides'][0]['directions'])
        first = admit(self.center, v2)
        original = read_guard_envelope(v2)
        # Re-seal the same piece ID around a different body (different permit).
        from issuer.envelope import seal_guard_piece
        other_text = issue_guard(self.bench, revisions[0].revision_id, [0, 0], [])
        other_body = read_guard_envelope(other_text).body
        with self.assertRaisesRegex(ValueError, 'piece identity conflict'):
            admit(self.center, seal_guard_piece(original.piece_id, other_body))
        self.assertEqual(self.center.execute('SELECT count(*) FROM receipts').fetchone()[0], 1)
        self.assertEqual(get_receipt(self.center, first.receipt_id), first)


class GuardReviewTests(GuardLabCase):
    def _pair(self, sample):
        revisions = self.register_guard_case(sample)
        return self.admit_guard(self.issue_sides(revisions, sample))

    def test_canonical_two_beat_margin_and_claim(self):
        sample = self.guard_sample()
        pair = self._pair(sample)
        self.stop_source()
        report = self.guard_decide(pair, sample)
        self.assertEqual(report.margin, Fraction(1, 2))
        self.assertTrue(report.claimable)
        self.assertEqual(report.minimum_margin, Fraction(1, 2))
        self.assertEqual(report.rule.weights, (Fraction(-1, 2), Fraction(1, 2)))
        self.assertEqual(report.rule.left_max, Fraction(0))
        self.assertEqual(report.rule.right_min, Fraction(1, 2))
        self.assertEqual(report.rule.threshold, Fraction(1, 4))
        self.assertEqual(report.waveforms,
                         ((Fraction(1, 2), Fraction(1, 2)), (Fraction(0), Fraction(1))))
        self.assertEqual(report.retained_beats, (1, 2))
        self.assertEqual(report.evidence, tuple(item.provenance for item in pair))
        archived = get_guard_report(self.center, report.report_id)
        self.assertEqual(archived, report)
        self.assertEqual(self.guard_counts(), (1, 1))

    def test_equal_threshold_passes_but_higher_threshold_fails_claim(self):
        sample = self.guard_sample()
        pair = self._pair(sample)
        self.stop_source()
        passing = self.guard_decide(pair, sample, minimum='1/2')
        failing = self.guard_decide(pair, sample, minimum='3/4')
        self.assertTrue(passing.claimable)
        self.assertFalse(failing.claimable)
        # The signed evidence is identical regardless of the claim threshold.
        self.assertEqual(failing.margin, passing.margin)
        self.assertEqual(failing.rule, passing.rule)
        self.assertEqual(failing.waveforms, passing.waveforms)
        self.assertEqual(self.guard_counts(), (2, 2))

    def test_single_retained_beats_have_zero_margin_and_shared_waveform(self):
        sample = self.guard_sample()
        pair = self._pair(sample)
        self.stop_source()
        for retained in ([1], [2]):
            with self.subTest(retained=retained):
                report = self.guard_decide(pair, sample, retained=retained)
                self.assertEqual(report.margin, 0)
                self.assertIsNone(report.rule)
                self.assertEqual(report.waveforms[0], report.waveforms[1])
                self.assertFalse(report.claimable)
                self.assertEqual(get_guard_report(self.center, report.report_id), report)

    def test_no_direction_reissue_gives_full_margin(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        right_text = issue_guard(self.bench, revisions[1].revision_id, [], [])
        left_text = issue_guard(self.bench, revisions[0].revision_id,
                                sample['sides'][0]['origin'], [])
        pair = self.admit_guard((left_text, right_text))
        self.stop_source()
        report = self.guard_decide(pair, sample)
        self.assertEqual(report.margin, 1)
        self.assertTrue(report.claimable)
        self.assertEqual(sum(abs(weight) for weight in report.rule.weights), 1)
        self.assertEqual(report.rule.right_min - report.rule.left_max, 1)
        self.assertEqual(max(abs(r - l) for l, r in zip(*report.waveforms)), 1)

    def test_witness_waveforms_are_realizable_and_meet_the_margin(self):
        sample = self.guard_sample()
        pair = self._pair(sample)
        self.stop_source()
        report = self.guard_decide(pair, sample, minimum='999')
        left_wave, right_wave = report.waveforms
        # Left readings must have the form (a+b, a-b) with a,b in [0,1].
        a = (left_wave[0] + left_wave[1]) / 2
        b = (left_wave[0] - left_wave[1]) / 2
        self.assertTrue(all(Fraction(0) <= coefficient <= 1 for coefficient in (a, b)))
        self.assertEqual(right_wave, (Fraction(0), Fraction(1)))
        self.assertEqual(max(abs(r - l) for l, r in zip(left_wave, right_wave)),
                         report.margin)
        self.assertFalse(report.claimable)
        # The rule scores the pair exactly at its two declared score bounds.
        weights = report.rule.weights
        self.assertEqual(sum(weight * value for weight, value in zip(weights, left_wave)),
                         report.rule.left_max)
        self.assertEqual(sum(weight * value for weight, value in zip(weights, right_wave)),
                         report.rule.right_min)

    def test_v1_pieces_are_rejected_from_guard_review(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        v2_text = issue_guard(self.bench, revisions[1].revision_id, [], [])
        v2 = admit(self.center, v2_text)
        v1 = admit(self.center, issue(self.bench, revisions[0].revision_id))
        drive = {int(beat): values for beat, values in sample['drive'].items()}
        units = sample['schedule']['drive_units']
        with self.assertRaisesRegex(ValueError, 'version 2'):
            review_guard(self.center, (v1.receipt_id, v2.receipt_id), drive, [1, 2],
                         '1/2', drive_units=units)
        with self.assertRaisesRegex(ValueError, 'version 2'):
            review_guard(self.center, (v2.receipt_id, v1.receipt_id), drive, [1, 2],
                         '1/2', drive_units=units)
        self.assertEqual(self.guard_counts(), (0, 0))

    def test_invalid_guard_requests_leave_no_records(self):
        sample = self.guard_sample()
        pair = self._pair(sample)
        self.stop_source()
        drive = {int(beat): values for beat, values in sample['drive'].items()}
        units = sample['schedule']['drive_units']
        ids = tuple(item.receipt_id for item in pair)
        for kwargs in (
            dict(receipt_ids=ids, drive=drive, retained_beats=[1, 2], minimum_margin=0,
                 drive_units=units),
            dict(receipt_ids=ids, drive=drive, retained_beats=[1, 2], minimum_margin='-1/2',
                 drive_units=units),
            dict(receipt_ids=ids, drive=drive, retained_beats=[], minimum_margin='1/2',
                 drive_units=units),
            dict(receipt_ids=(ids[0],), drive=drive, retained_beats=[1, 2],
                 minimum_margin='1/2', drive_units=units),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    review_guard(self.center, **kwargs)
        with self.assertRaises(KeyError):
            review_guard(self.center, (ids[0], 999), drive, [1, 2], '1/2', drive_units=units)
        for bad_threshold in (0.5, True, None):
            with self.subTest(bad_threshold=bad_threshold):
                with self.assertRaises(ValueError):
                    review_guard(self.center, ids, drive, [1, 2], bad_threshold,
                                 drive_units=units)
        with self.assertRaises(ValueError):
            review_guard(self.center, ids, {1: {'coil': 0}}, [1, 2], '1/2',
                         drive_units=units)
        self.assertEqual(self.guard_counts(), (0, 0))

    def test_tampered_or_unknown_version_piece_is_rejected(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        text = issue_guard(self.bench, revisions[0].revision_id,
                           sample['sides'][0]['origin'], sample['sides'][0]['directions'])
        first = admit(self.center, text)
        tampered = json.loads(text)
        tampered['body']['waveform']['permission']['origin_readings'][0] = '999'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            admit(self.center, json.dumps(tampered))
        unsupported = json.loads(text)
        unsupported['version'] = 3
        with self.assertRaisesRegex(ValueError, 'unsupported piece version'):
            admit(self.center, json.dumps(unsupported))
        self.assertEqual(get_receipt(self.center, first.receipt_id), first)
        self.assertEqual(self.center.execute('SELECT count(*) FROM receipts').fetchone()[0], 1)

    def test_errata_and_reopen_keeps_the_original_guard_report(self):
        sample = self.guard_sample()
        revisions = self.register_guard_case(sample)
        pieces = self.issue_sides(revisions, sample)
        receipts = self.admit_guard(pieces)
        self.stop_source()
        original = self.guard_decide(receipts, sample)
        original_id = original.report_id

        # A later errata adds a fresh revision and V2 piece while the bench is reopened.
        self.restart_source()
        amended = self.bench_register(
            sample['instrument'], sample['schedule']['schedule_id'],
            sample['sides'][0], revisions[1].revision_id)
        amended_text = issue_guard(self.bench, amended.revision_id,
                                   sample['sides'][0]['origin'],
                                   sample['sides'][0]['directions'])
        amended_receipt = admit(self.center, amended_text)
        self.stop_source()
        renewed = review_guard(
            self.center,
            (receipts[0].receipt_id, amended_receipt.receipt_id),
            {int(beat): values for beat, values in sample['drive'].items()},
            sample['retained_beats'], '1/2',
            drive_units=sample['schedule']['drive_units'])
        self.assertNotEqual(renewed.report_id, original_id)

        self.center.close()
        self.center = self.open_db(self.center_path)
        init_center(self.center)
        fetched = get_guard_report(self.center, original_id)
        self.assertEqual(fetched, original)
        self.assertEqual(fetched.margin, Fraction(1, 2))
        self.assertTrue(fetched.claimable)
        self.assertEqual(get_guard_report(self.center, renewed.report_id), renewed)

    def test_unknown_guard_report_returns_none_and_archive_survives_reopen(self):
        sample = self.guard_sample()
        pair = self._pair(sample)
        self.stop_source()
        report = self.guard_decide(pair, sample)
        self.assertIsNone(get_guard_report(self.center, 'missing-guard-report'))
        # V1 archive and guard archive stay independent.
        self.assertIsNone(get_report(self.center, report.report_id))
        self.center.close()
        self.center = self.open_db(self.center_path)
        init_center(self.center)
        reopened = get_guard_report(self.center, report.report_id)
        self.assertEqual(reopened, report)
        self.assertEqual(reopened.rule.threshold, Fraction(1, 4))


class GuardFailureTests(GuardReviewTests):
    def test_failed_publication_is_atomic(self):
        sample = self.guard_sample()
        pair = self._pair(sample)
        self.stop_source()
        good = self.guard_decide(pair, sample)
        self.assertEqual(self.guard_counts(), (1, 1))
        self.center.executescript('''
            CREATE TABLE test_guard_gate (
                report_id TEXT PRIMARY KEY,
                release_id INTEGER REFERENCES test_guard_missing(id)
                    DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TABLE test_guard_missing (id INTEGER PRIMARY KEY);
            CREATE TRIGGER test_guard_abort AFTER INSERT ON guard_success_receipts
            BEGIN
                INSERT INTO test_guard_gate VALUES (NEW.report_id, 99);
            END;
        ''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.guard_decide(pair, sample, minimum='3/4')
        self.assertFalse(self.center.in_transaction)
        observer = self.open_db(self.center_path)
        self.assertEqual(self.guard_counts(), (1, 1))
        self.assertEqual(get_guard_report(observer, good.report_id), good)
        self.center.execute('DROP TRIGGER test_guard_abort')
        retried = self.guard_decide(pair, sample, minimum='3/4')
        self.assertFalse(retried.claimable)
        self.assertEqual(get_guard_report(observer, retried.report_id), retried)


if __name__ == '__main__':
    unittest.main()
