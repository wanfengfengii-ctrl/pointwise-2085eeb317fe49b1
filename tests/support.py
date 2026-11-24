import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog.revisions import init_revision_storage, register_revision
from intake.admission import admit
from intake.receipts import init_receipt_storage
from issuer.freeze import init_issue_storage, issue
from protocol.schedule import init_schedule_storage, register_schedule
from review.publication import review
from review.report import init_report_storage


SAMPLE = Path(__file__).resolve().parents[1] / 'samples' / 'retest.json'
UNITS = (('coil', 'V'),)
PULSE = {1: {'coil': 1}, 2: {'coil': 0}}
ZERO = {1: {'coil': 0}, 2: {'coil': 0}}


def init_bench(conn):
    init_schedule_storage(conn)
    init_revision_storage(conn)
    init_issue_storage(conn)


def init_center(conn):
    init_receipt_storage(conn)
    init_report_storage(conn)


class LabCase(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory(prefix='retest-tests-')))
        self.bench_path = directory / 'bench.sqlite'
        self.center_path = directory / 'center.sqlite'
        self.parked = directory / 'parked.sqlite'
        self.bench = self.open_db(self.bench_path)
        self.center = self.open_db(self.center_path)
        init_bench(self.bench)
        init_center(self.center)
        self.sample = json.loads(SAMPLE.read_text(encoding='utf-8'))
        self.schedule = self.make_schedule()

    def open_db(self, path):
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        return conn

    def make_schedule(self, name='pulse', beats=((1, 0), (2, 1)), units=UNITS):
        return register_schedule(self.bench, name, beats, units)

    def revision(self, name, *, schedule=None, parent_id=None, instrument=None):
        return register_revision(self.bench, instrument or self.sample['instrument'],
                                 (schedule or self.schedule).schedule_id, **self.sample[name],
                                 parent_id=parent_id)

    def receive(self, revision):
        return admit(self.center, issue(self.bench, revision.revision_id))

    def pulse_receipts(self):
        return tuple(self.receive(self.revision(name)) for name in ('reference', 'replacement'))

    def stop_source(self):
        self.bench.close()
        self.bench_path.rename(self.parked)
        self.assertFalse(self.bench_path.exists())

    def restart_source(self):
        self.parked.rename(self.bench_path)
        self.bench = self.open_db(self.bench_path)
        init_bench(self.bench)

    def decide(self, receipts, drive=PULSE, retained=(1, 2), *, units=UNITS):
        ids = tuple(receipt.receipt_id for receipt in receipts)
        return review(self.center, ids, drive, retained, drive_units=units)

    def report_counts(self, conn=None):
        connection = self.center if conn is None else conn
        reports = connection.execute('SELECT count(*) FROM reports').fetchone()[0]
        receipts = connection.execute('SELECT count(*) FROM success_receipts').fetchone()[0]
        return reports, receipts
