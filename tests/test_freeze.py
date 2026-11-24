from fractions import Fraction

from catalog.revisions import get_revision, register_revision
from issuer.envelope import read_envelope
from issuer.freeze import issue
from protocol.linear import has_rational_solution
from protocol.schedule import get_schedule
from tests.support import LabCase, init_bench


class FreezeTests(LabCase):
    def test_named_revision(self):
        old = self.revision('reference')
        new = self.revision('replacement', parent_id=old.revision_id)
        new_text = issue(self.bench, new.revision_id)
        old_text = issue(self.bench, old.revision_id)
        pieces = [read_envelope(text) for text in (new_text, old_text)]
        self.assertNotEqual(pieces[0].piece_id, pieces[1].piece_id)
        for revision, gain, text, piece in zip((new, old), (-1, 1), (new_text, old_text), pieces):
            self.assertEqual(piece.schedule, self.schedule)
            self.assertEqual(piece.body['provenance'], {
                'revision_id': revision.revision_id, 'instrument_id': revision.instrument_id,
                'schedule_id': 'pulse', 'calibration_reference': revision.calibration.reference,
            })
            self.assertEqual(piece.waveform.drive_rows, ((0, 0), (gain, 0)))
            self.assertEqual(set(piece.body), {'schedule', 'provenance', 'waveform'})
            self.assertEqual(set(piece.body['waveform']),
                             {'beat_ids', 'channels', 'drive_rows', 'initial_rows'})
            self.assertNotIn(revision.calibration.rows[0][0], text)
            self.assertEqual(self.bench.execute('SELECT revision_id, sealed_text FROM issues '
                                               'WHERE piece_id = ?', (piece.piece_id,)).fetchone(),
                             (revision.revision_id, text))
        self.assertEqual(get_revision(self.bench, old.revision_id), old)
        self.assertEqual(get_revision(self.bench, new.revision_id).parent_id, old.revision_id)

    def test_schedule_conflict(self):
        revision = self.revision('reference')
        self.assertEqual(self.make_schedule(beats=((1, '0/3'), (2, '2/2'))), self.schedule)
        with self.assertRaisesRegex(ValueError, 'identity conflict'):
            self.make_schedule(beats=((1, 0), (2, 2)))
        self.assertEqual(get_schedule(self.bench, 'pulse'), self.schedule)
        self.assertEqual(read_envelope(issue(self.bench, revision.revision_id)).schedule.times, (0, 1))

    def test_invalid_schedule(self):
        cases = [
            (((1, 0),), [('coil', 'V')]),
            (tuple((k, k) for k in range(1, 8)), [('coil', 'V')]),
            (((1, 0), (1, 1)), [('coil', 'V')]),
            (((1, 0), (2, 0)), [('coil', 'V')]),
            (((1, 0), (2, '-1')), [('coil', 'V')]),
            (((1, 0), (2, '1/0')), [('coil', 'V')]),
            (((True, 0), (2, 1)), [('coil', 'V')]),
            (((1, 0), (2, 1)), [('coil', 'V'), ('coil', 'mV')]),
            (((1, 0), (2, 1)), [('coil', '')]),
        ]
        for beats, units in cases:
            with self.subTest(beats=beats, units=units):
                with self.assertRaises(ValueError):
                    self.make_schedule('invalid', beats, units)
        self.assertEqual(self.bench.execute('SELECT schedule_id FROM schedules').fetchall(), [('pulse',)])

    def test_unknown_revision(self):
        with self.assertRaisesRegex(KeyError, 'unknown revision'):
            issue(self.bench, 404)
        self.assertEqual(self.bench.execute('SELECT count(*) FROM issues').fetchone()[0], 0)

    def test_source_reinitialization(self):
        custom = self.make_schedule('user', ((4, '1/3'), (8, '7/3')))
        revision = self.revision('reference', schedule=custom)
        sealed = read_envelope(issue(self.bench, revision.revision_id))
        init_bench(self.bench)
        self.stop_source()
        self.restart_source()
        self.assertEqual(get_schedule(self.bench, 'user'), custom)
        self.assertEqual(get_revision(self.bench, revision.revision_id), revision)
        self.assertEqual(self.bench.execute('SELECT sealed_text FROM issues WHERE piece_id = ?',
                                          (sealed.piece_id,)).fetchone(), (sealed.canonical_text,))
        next_revision = self.revision('correction', schedule=custom, parent_id=revision.revision_id)
        self.assertEqual(get_revision(self.bench, next_revision.revision_id), next_revision)

    def test_joint_evidence(self):
        old = self.revision('replacement')
        new = self.revision('correction', parent_id=old.revision_id)
        possible = []
        for revision in (old, new):
            evidence = read_envelope(issue(self.bench, revision.revision_id)).waveform
            self.assertEqual(evidence.drive_rows, ((0, 0), (-1, 0)))
            self.assertTrue(all(any(row) for row in evidence.initial_rows))
            # Pulse (1,0) makes the fixed term (0,-1) in both pieces.
            # A common initial t cannot make (t,t-1) zero. Independent t and q can.
            possible.append(has_rational_solution(evidence.initial_rows, (Fraction(0), Fraction(1))))
        self.assertEqual(possible, [False, True])

    def test_bad_dimensions(self):
        old = self.revision('reference')
        broken = {'A': [[0, 1], [1]], 'B': [[1], [0]], 'C': [[1, 0]], 'D': [[0]]}
        with self.assertRaisesRegex(ValueError, 'A: row 2'):
            register_revision(self.bench, old.instrument_id, 'pulse', broken,
                              self.sample['correction']['calibration'], parent_id=old.revision_id)
        self.assertEqual(self.bench.execute('SELECT count(*) FROM revisions').fetchone()[0], 1)
        self.assertEqual(read_envelope(issue(self.bench, old.revision_id)).body['provenance']['revision_id'],
                         old.revision_id)

    def test_invalid_metadata(self):
        old = self.revision('reference')
        model = self.sample['replacement']['model']
        good = self.sample['replacement']['calibration']
        for instrument, source, parent in (
            (old.instrument_id, {'reference': ' ', 'rows': []}, old.revision_id),
            (old.instrument_id, {'reference': 'CAL', 'rows': [[None]]}, old.revision_id),
            (old.instrument_id, good, 404),
            (old.instrument_id, good, True),
            ('another meter', good, old.revision_id),
        ):
            with self.subTest(instrument=instrument, source=source, parent=parent):
                with self.assertRaises(ValueError):
                    register_revision(self.bench, instrument, 'pulse', model, source, parent_id=parent)
        with self.assertRaises(KeyError):
            register_revision(self.bench, old.instrument_id, 'unknown', model, good)
        self.assertEqual(self.bench.execute('SELECT count(*) FROM revisions').fetchone()[0], 1)
        self.assertEqual(get_revision(self.bench, old.revision_id), old)

    def test_invalid_rational(self):
        old = self.revision('reference')
        for value in ('1/0', 'meter', '', None, 0.5, True):
            with self.subTest(value=value):
                model = dict(self.sample['replacement']['model'], B=[[value]])
                with self.assertRaises(ValueError):
                    register_revision(self.bench, old.instrument_id, 'pulse', model,
                                      self.sample['replacement']['calibration'], parent_id=old.revision_id)
        self.assertEqual(get_revision(self.bench, old.revision_id), old)
        self.assertEqual(self.bench.execute('SELECT count(*) FROM revisions').fetchone()[0], 1)
