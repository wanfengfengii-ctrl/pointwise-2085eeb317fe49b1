import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog.revisions import init_revision_storage, register_revision
from intake.admission import admit
from intake.receipts import init_receipt_storage
from issuer.freeze import init_issue_storage, issue
from protocol.schedule import init_schedule_storage, register_schedule
from review.archive import get_report
from review.publication import review
from review.report import init_report_storage


def prepare_source(conn):
    init_schedule_storage(conn)
    init_revision_storage(conn)
    init_issue_storage(conn)


def prepare_center(conn):
    init_receipt_storage(conn)
    init_report_storage(conn)


def publish_scenario(case_id, data, expected, actual, archived, paths, oracle):
    if actual != expected or not archived:
        raise RuntimeError(f'{case_id}: unexpected calculation or unavailable archive')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': data, 'expected': expected, 'actual': actual,
        'downstream_expected': True, 'downstream_actual': archived, 'code_paths': paths,
        'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


def main():
    sample_path = Path(__file__).resolve().parent / 'samples' / 'retest.json'
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    task = sample['schedule']
    units = task['drive_units']
    drive = {int(beat): row for beat, row in sample['actual_drive'].items()}
    retained = sample['retained_beats']

    with TemporaryDirectory(prefix='retest-') as directory:
        bench_path = Path(directory) / 'bench.sqlite'
        parked_path = Path(directory) / 'offline.sqlite'
        center_path = Path(directory) / 'center.sqlite'
        with closing(sqlite3.connect(bench_path)) as bench:
            prepare_source(bench)
            schedule = register_schedule(bench, task['schedule_id'], task['beats'], units)
            reference, replacement = (
                register_revision(bench, sample['instrument'], schedule.schedule_id, **sample[name])
                for name in ('reference', 'replacement')
            )
            pieces = (issue(bench, reference.revision_id), issue(bench, replacement.revision_id))

        with closing(sqlite3.connect(center_path)) as center:
            prepare_center(center)
            left, right = (admit(center, piece) for piece in pieces)
            bench_path.rename(parked_path)
            pair = (left.receipt_id, right.receipt_id)
            original = review(center, pair, drive, retained, drive_units=units)
            single = review(center, pair, drive, [2], drive_units=units)
            stored = get_report(center, original.report_id)
            publish_scenario('v4', {'drive': drive, 'retained': retained}, 2,
                             original.earliest_beat,
                             stored == original and original.evidence == (left.provenance, right.provenance),
                             ['issuer/behavior.py', 'intake/admission.py', 'review/observable.py',
                              'review/prefix.py', 'review/publication.py', 'review/archive.py'],
                             '第一拍要求 t=s，第二拍相等还要求 t=s+2')
            publish_scenario('v5', {'drive': drive, 'retained': [2]}, None,
                             single.earliest_beat, get_report(center, single.report_id) == single,
                             ['protocol/retention.py', 'review/observable.py', 'review/archive.py'],
                             '仅第二拍时 t=s+2 可匹配')

            parked_path.rename(bench_path)
            with closing(sqlite3.connect(bench_path)) as bench:
                prepare_source(bench)
                correction = register_revision(bench, sample['instrument'], schedule.schedule_id,
                                               **sample['correction'], parent_id=replacement.revision_id)
                corrected_piece = issue(bench, correction.revision_id)
            corrected = admit(center, corrected_piece)
            bench_path.rename(parked_path)
            new_pair = (left.receipt_id, corrected.receipt_id)
            newer = review(center, new_pair, drive, retained, drive_units=units)

        with closing(sqlite3.connect(center_path)) as center:
            prepare_center(center)
            history = get_report(center, original.report_id)
            new_history = get_report(center, newer.report_id)
            publish_scenario('v9', {'drive': drive, 'retained': retained,
                                   'old_receipts': pair, 'new_receipts': new_pair},
                             {'original': 2, 'corrected': None},
                             {'original': history.earliest_beat, 'corrected': new_history.earliest_beat},
                             history == original and new_history == newer and
                             newer.evidence == (left.provenance, corrected.provenance),
                             ['catalog/revisions.py', 'issuer/freeze.py', 'intake/admission.py',
                              'review/prefix.py', 'review/archive.py'],
                             '更正版可取 t=s、q=s+2，原报告及原回执可按号领取')


def run_guard_demo():
    """Closed-station guard: issue V2 permits, park the bench, sign and re-fetch."""
    from fractions import Fraction
    from issuer.freeze import issue_guard
    from review.publication import review_guard
    from review.archive import get_guard_report

    sample = json.loads((Path(__file__).resolve().parent / 'samples' / 'guard.json')
                        .read_text(encoding='utf-8'))
    units = sample['schedule']['drive_units']
    drive = {int(beat): values for beat, values in sample['drive'].items()}
    with TemporaryDirectory(prefix='guard-demo-') as directory:
        bench_path = Path(directory) / 'bench.sqlite'
        parked_path = Path(directory) / 'parked.sqlite'
        center_path = Path(directory) / 'center.sqlite'
        with closing(sqlite3.connect(bench_path)) as bench:
            prepare_source(bench)
            schedule = register_schedule(bench, **sample['schedule'])
            revisions = []
            for side in sample['sides']:
                parent = revisions[-1].revision_id if revisions else None
                revisions.append(register_revision(
                    bench, sample['instrument'], schedule.schedule_id,
                    **side['revision'], parent_id=parent))
            pieces = tuple(
                issue_guard(bench, revision.revision_id, side['origin'], side['directions'])
                for revision, side in zip(revisions, sample['sides']))

        with closing(sqlite3.connect(center_path)) as center:
            prepare_center(center)
            receipts = tuple(admit(center, piece) for piece in pieces)
            bench_path.rename(parked_path)
            pair = tuple(item.receipt_id for item in receipts)
            report = review_guard(center, pair, drive, sample['retained_beats'],
                                  Fraction(1, 2), drive_units=units)

        with closing(sqlite3.connect(center_path)) as center:
            prepare_center(center)
            fetched = get_guard_report(center, report.report_id)
            publish_scenario(
                'guard-v2',
                {'drive': drive, 'retained_beats': sample['retained_beats'],
                 'minimum_margin': '1/2'},
                {'margin': '1/2', 'claimable': True},
                {'margin': str(fetched.margin), 'claimable': fetched.claimable},
                fetched == report and fetched.rule is not None and
                [str(value) for value in fetched.rule.weights] == ['-1/2', '1/2'] and
                fetched.rule.threshold == Fraction(1, 4),
                ['issuer/freeze.py', 'issuer/permission.py', 'review/guard_observable.py',
                 'review/publication.py', 'review/archive.py'],
                '关站后按许可签出可下发判别式，余量 1/2 达门槛，重开按原号领回')


if __name__ == '__main__':
    main()
    run_guard_demo()
