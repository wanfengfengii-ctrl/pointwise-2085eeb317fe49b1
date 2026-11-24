import sqlite3

from catalog.revisions import get_revision
from intake.receipts import get_receipt
from review.archive import get_report
from tests.support import LabCase, init_center


class ArchiveTests(LabCase):
    def test_failed_publication(self):
        pair = self.pulse_receipts()
        self.stop_source()
        original = self.decide(pair)
        self.assertEqual(self.report_counts(), (1, 1))
        self.assertEqual(self.center.execute('PRAGMA foreign_keys').fetchone(), (1,))
        self.center.executescript('''
            CREATE TABLE test_release (id INTEGER PRIMARY KEY);
            CREATE TABLE test_commit_gate (
                report_id TEXT PRIMARY KEY,
                release_id INTEGER REFERENCES test_release(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER test_defer_publication AFTER INSERT ON success_receipts
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM reports WHERE report_id = NEW.report_id
                ) THEN RAISE(ABORT, 'report was not staged') END;
                INSERT INTO test_commit_gate VALUES (NEW.report_id, 99);
            END;
        ''')
        # The receipt insert runs the trigger after staging. The missing parent is checked at COMMIT.
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            self.decide(pair, retained=[2])
        self.assertEqual(caught.exception.sqlite_errorname, 'SQLITE_CONSTRAINT_FOREIGNKEY')
        self.assertFalse(self.center.in_transaction)
        observer = self.open_db(self.center_path)
        self.assertEqual(self.report_counts(observer), (1, 1))
        self.assertEqual(observer.execute('SELECT count(*) FROM test_commit_gate').fetchone(), (0,))
        self.assertEqual(get_report(observer, original.report_id), original)
        self.assertEqual(observer.execute('SELECT report_id FROM reports').fetchall(), [(original.report_id,)])
        self.center.execute('DROP TRIGGER test_defer_publication')
        retried = self.decide(pair, retained=[2])
        self.assertEqual(self.report_counts(observer), (2, 2))
        self.assertIsNone(retried.earliest_beat)
        self.assertEqual(get_report(observer, retried.report_id), retried)

    def test_corrected_revision(self):
        base = self.revision('reference')
        replaced = self.revision('replacement', parent_id=base.revision_id)
        pair = (self.receive(base), self.receive(replaced))
        self.stop_source()
        original = self.decide(pair)
        self.assertEqual(original.earliest_beat, 2)

        self.restart_source()
        amended = self.revision('correction', parent_id=replaced.revision_id)
        self.assertEqual(get_revision(self.bench, replaced.revision_id), replaced)
        amended_receipt = self.receive(amended)
        self.stop_source()
        new = self.decide((pair[0], amended_receipt))
        self.assertIsNone(new.earliest_beat)
        self.assertEqual(new.evidence, (pair[0].provenance, amended_receipt.provenance))
        self.assertNotEqual(original.report_id, new.report_id)
        self.assertNotEqual(original.success_receipt.receipt_id, new.success_receipt.receipt_id)

        self.center.close()
        self.center = self.open_db(self.center_path)
        init_center(self.center)
        init_center(self.center)
        self.assertEqual(self.report_counts(), (2, 2))
        self.assertEqual(get_receipt(self.center, pair[1].receipt_id), pair[1])
        self.assertEqual(get_receipt(self.center, amended_receipt.receipt_id), amended_receipt)
        self.assertEqual(get_report(self.center, original.report_id), original)
        self.assertEqual(get_report(self.center, new.report_id), new)
        self.assertIsNone(get_report(self.center, 'absent-report'))
        third = self.decide(pair, retained=[1])
        self.assertIsNone(third.earliest_beat)
        self.assertEqual(self.report_counts(), (3, 3))
        self.assertEqual(get_report(self.center, original.report_id), original)
