import random
import sqlite3
import unittest
from fractions import Fraction
from itertools import product
from tempfile import TemporaryDirectory
from pathlib import Path

from catalog.revisions import init_revision_storage, register_revision
from intake.admission import admit
from intake.receipts import init_receipt_storage
from issuer.freeze import init_issue_storage, issue_guard
from protocol.schedule import init_schedule_storage, register_schedule
from review.publication import review_guard
from review.report import init_report_storage


def rational(value):
    return Fraction(value).limit_denominator(4)


class GuardPropertyTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix='guard-property-')
        self.addCleanup(self.directory.cleanup)
        self.bench_path = Path(self.directory.name) / 'bench.sqlite'
        self.center_path = Path(self.directory.name) / 'center.sqlite'
        self.bench = sqlite3.connect(self.bench_path)
        self.center = sqlite3.connect(self.center_path)
        self.addCleanup(self.bench.close)
        self.addCleanup(self.center.close)
        init_schedule_storage(self.bench)
        init_revision_storage(self.bench)
        init_issue_storage(self.bench)
        init_receipt_storage(self.center)
        init_report_storage(self.center)

    def _model(self, rng, states, channels):
        if states == 0:
            return {'A': [], 'B': [], 'C': [[]],
                    'D': [[rational(rng.randint(-2, 2)) for _ in range(channels)]]}
        return {
            'A': [[rational(rng.randint(-1, 1)) for _ in range(states)] for _ in range(states)],
            'B': [[rational(rng.randint(-1, 1)) for _ in range(channels)]
                  for _ in range(states)],
            'C': [[rational(rng.randint(-1, 1)) for _ in range(states)]],
            'D': [[rational(rng.randint(-1, 1)) for _ in range(channels)]],
        }

    def _permit(self, rng, states):
        if states == 0:
            return [], []
        origin = [rational(rng.randint(-1, 1)) for _ in range(states)]
        directions = [[rational(rng.randint(-1, 1)) for _ in range(states)]
                      for _ in range(rng.randint(0, 2))]
        return origin, directions

    def test_random_pieces_bruteforce_the_margin(self):
        rng = random.Random(20261124)
        units = [('coil', 'V')]
        register_schedule(self.bench, 'random', [(1, 0), (2, 1), (3, 2)], units)
        drive = {1: {'coil': Fraction(0)}, 2: {'coil': Fraction(1)},
                 3: {'coil': Fraction(rng.randint(-1, 1))}}
        for trial in range(25):
            with self.subTest(trial=trial):
                left_states = rng.randint(0, 2)
                right_states = rng.randint(0, 2)
                left_rev = register_revision(
                    self.bench, f'random-{trial}-L', 'random',
                    self._model(rng, left_states, 1),
                    {'reference': f'CAL/L/{trial}', 'rows': [['private']]})
                right_rev = register_revision(
                    self.bench, f'random-{trial}-R', 'random',
                    self._model(rng, right_states, 1),
                    {'reference': f'CAL/R/{trial}', 'rows': []})
                left_origin, left_dirs = self._permit(rng, left_states)
                right_origin, right_dirs = self._permit(rng, right_states)
                left_piece = issue_guard(self.bench, left_rev.revision_id,
                                         left_origin, left_dirs)
                right_piece = issue_guard(self.bench, right_rev.revision_id,
                                          right_origin, right_dirs)
                left = admit(self.center, left_piece)
                right = admit(self.center, right_piece)
                retained = (1, 2, 3) if trial % 2 else (2, 3)
                report = review_guard(
                    self.center, (left.receipt_id, right.receipt_id), drive,
                    list(retained), '1/1000', drive_units=units)

                # Independent brute force: enumerate every permit-box corner on each
                # side and propagate the exact drive through the private models.
                left_waves = self._all_readings(left_rev.revision_id, left_origin,
                                                left_dirs, drive)
                right_waves = self._all_readings(right_rev.revision_id, right_origin,
                                                 right_dirs, drive, right=True)
                positions = tuple(index for index, beat in enumerate((1, 2, 3))
                                  if beat in retained)
                brute_margin = min(
                    max(abs(r[index] - l[index]) for index in positions)
                    for l in left_waves for r in right_waves)
                self.assertEqual(report.margin, brute_margin)
                pair_distance = max(
                    abs(r_value - l_value)
                    for l_value, r_value in zip(*report.waveforms))
                self.assertEqual(pair_distance, report.margin)
                if report.margin > 0:
                    rule = report.rule
                    self.assertLessEqual(sum(abs(w) for w in rule.weights), 1)
                    left_scores = [
                        sum(rule.weights[k] * wave[positions[k]] for k in range(len(positions)))
                        for wave in left_waves]
                    right_scores = [
                        sum(rule.weights[k] * wave[positions[k]] for k in range(len(positions)))
                        for wave in right_waves]
                    self.assertEqual(rule.left_max, max(left_scores))
                    self.assertEqual(rule.right_min, min(right_scores))
                    self.assertEqual(rule.right_min - rule.left_max, report.margin)
                    self.assertEqual(rule.threshold,
                                     (rule.left_max + rule.right_min) / 2)
                else:
                    self.assertIsNone(report.rule)
                    self.assertEqual(report.waveforms[0], report.waveforms[1])

    def _all_readings(self, revision_id, origin, directions, drive, *, right=False):
        from catalog.revisions import get_revision
        revision = get_revision(self.bench, revision_id)
        model = revision.model
        beat_count = 3
        drive_values = [drive[beat]['coil'] for beat in (1, 2, 3)]
        waves = []
        for coefficients in product((Fraction(0), Fraction(1)), repeat=len(directions)):
            state = tuple(origin) + tuple()
            state = tuple(Fraction(origin[index])
                          + sum(coefficients[k] * Fraction(directions[k][index])
                                for k in range(len(directions)))
                          for index in range(len(origin)))
            readings = []
            current = list(state)
            for beat in range(beat_count):
                if model.A:
                    observed = sum(model.C[0][index] * current[index]
                                   for index in range(len(current)))
                else:
                    observed = Fraction(0)
                reading = observed + model.D[0][0] * drive_values[beat]
                readings.append(reading)
                if model.A:
                    current = [
                        sum(model.A[index][column] * current[column]
                            for column in range(len(current)))
                        + model.B[index][0] * drive_values[beat]
                        for index in range(len(current))]
            waves.append(tuple(readings))
        return waves


if __name__ == '__main__':
    unittest.main()
