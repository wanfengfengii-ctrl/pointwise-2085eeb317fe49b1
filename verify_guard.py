"""Business gate checks for the closed-station guard workflow.

First runs the full unittest suite (which keeps the original V1 regression), then
exercises every GUARD.md acceptance gate on the two-beat fixture: both retention
readings, the equal-threshold pass, a non-claimable higher threshold,
no-record-on-failure, atomic publication and reopen retrieval.  Exits non-zero if any
check fails; writes nothing outside temporary databases.
"""
import json
import sqlite3
import sys
import unittest
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog.revisions import register_revision
from demo import prepare_center, prepare_source
from intake.admission import admit
from issuer.freeze import issue_guard
from protocol.schedule import register_schedule
from review.archive import get_guard_report
from review.publication import review_guard


def run_regression():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful() or result.testsRun == 0:
        return False
    return True


def load_case():
    return json.loads((Path(__file__).resolve().parent / 'samples' / 'guard.json')
                      .read_text(encoding='utf-8'))


def register(conn, sample):
    prepare_source(conn)
    schedule = register_schedule(conn, **sample['schedule'])
    revisions = []
    for side in sample['sides']:
        parent = revisions[-1].revision_id if revisions else None
        revisions.append(register_revision(conn, sample['instrument'],
                                           schedule.schedule_id, **side['revision'],
                                           parent_id=parent))
    return revisions


def main():
    if not run_regression():
        print('GUARD VERIFY FAIL: regression suite', file=sys.stderr)
        return 1
    sample = load_case()
    units = sample['schedule']['drive_units']
    drive = {int(beat): values for beat, values in sample['drive'].items()}

    with TemporaryDirectory(prefix='guard-verify-') as directory:
        bench_path = Path(directory) / 'bench.sqlite'
        center_path = Path(directory) / 'center.sqlite'
        with closing(sqlite3.connect(bench_path)) as bench:
            revisions = register(bench, sample)
            pieces = tuple(
                issue_guard(bench, revision.revision_id, side['origin'], side['directions'])
                for revision, side in zip(revisions, sample['sides']))
            no_direction_left = issue_guard(bench, revisions[0].revision_id,
                                            sample['sides'][0]['origin'], [])

        with closing(sqlite3.connect(center_path)) as center:
            prepare_center(center)
            receipts = tuple(admit(center, piece) for piece in pieces)
            pair = tuple(item.receipt_id for item in receipts)
            bench_path.rename(Path(directory) / 'parked.sqlite')

            # Gate 1: both retained beats give the signed 1/2 margin and a claimable rule.
            passing = review_guard(center, pair, drive, [1, 2], '1/2', drive_units=units)
            assert passing.margin == Fraction(1, 2)
            assert passing.claimable
            assert passing.rule.weights == (Fraction(-1, 2), Fraction(1, 2))
            assert (passing.rule.left_max, passing.rule.right_min,
                    passing.rule.threshold) == (Fraction(0), Fraction(1, 2), Fraction(1, 4))
            assert passing.waveforms == ((Fraction(1, 2), Fraction(1, 2)),
                                         (Fraction(0), Fraction(1)))

            # Gate 2: equal threshold passes, a higher threshold keeps the same evidence
            # but is not claimable.
            strict = review_guard(center, pair, drive, [1, 2], '3/4', drive_units=units)
            assert strict.claimable is False and strict.margin == Fraction(1, 2)
            assert strict.rule == passing.rule

            # Gate 3: either single retained beat leaves zero margin and a shared waveform.
            for retained in ([1], [2]):
                single = review_guard(center, pair, drive, retained, '1/2',
                                      drive_units=units)
                assert single.margin == 0 and single.rule is None
                assert single.waveforms[0] == single.waveforms[1]

            # Gate 4: a direction-free reissue of the left piece yields a full margin.
            left_fixed = admit(center, no_direction_left)
            full = review_guard(center, (left_fixed.receipt_id, pair[1]), drive, [1, 2],
                                '1/2', drive_units=units)
            assert full.margin == 1 and full.claimable

            # Gate 5: illegal requests fail without adding a signed record.
            before = (center.execute('SELECT count(*) FROM guard_reports').fetchone()[0],
                      center.execute('SELECT count(*) FROM guard_success_receipts').fetchone()[0])
            for call in (
                lambda: review_guard(center, pair, drive, [], '1/2', drive_units=units),
                lambda: review_guard(center, pair, drive, [1, 2], '0', drive_units=units),
                lambda: review_guard(center, (pair[0],), drive, [1, 2], '1/2',
                                     drive_units=units),
            ):
                try:
                    call()
                except ValueError:
                    pass
                else:
                    raise AssertionError('illegal guard request was accepted')
            after = (center.execute('SELECT count(*) FROM guard_reports').fetchone()[0],
                     center.execute('SELECT count(*) FROM guard_success_receipts').fetchone()[0])
            assert before == after

        # Gate 6: a reopened center still returns the original signed report by ID.
        with closing(sqlite3.connect(center_path)) as reopened:
            prepare_center(reopened)
            fetched = get_guard_report(reopened, passing.report_id)
            assert fetched == passing
            assert get_guard_report(reopened, 'unknown-guard-report') is None

    print('GUARD VERIFY PASS: two-beat margins, single-beat zeros, threshold equality, '
          'non-claimable evidence, no-record-on-failure and reopen retrieval')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
