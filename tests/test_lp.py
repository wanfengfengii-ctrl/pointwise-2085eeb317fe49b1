import unittest
from fractions import Fraction
from itertools import product

from protocol.lp import primal_minimum, solve_linear_system


class LinearProgramTests(unittest.TestCase):
    def test_singular_system(self):
        self.assertIsNone(solve_linear_system([[1, 1], [2, 2]], [1, 2]))
        self.assertEqual(solve_linear_system([[2, 0], [0, 4]], [1, 8]),
                         [Fraction(1, 2), Fraction(2)])

    def test_box_minimum_is_exact(self):
        # minimize t subject to t >= -z_i and t >= z_i for z = z0 + beta*g, beta in [0,1].
        z0 = (Fraction(-2), Fraction(1, 2))
        generators = ((Fraction(3), Fraction(-1)),)
        rows, rhs = [], []
        for i in range(2):
            rows.append((Fraction(1), generators[0][i]))
            rhs.append(-z0[i])
            rows.append((Fraction(1), -generators[0][i]))
            rhs.append(z0[i])
        rows.extend([(Fraction(0), Fraction(1)), (Fraction(0), Fraction(-1))])
        rhs.extend([Fraction(0), Fraction(-1)])
        value, point, _ = primal_minimum(rows, tuple(rhs), (Fraction(1), Fraction(0)))
        # Brute force over the box corners and the witness point.
        corner_best = min(
            max(abs(z0[i] + beta * generators[0][i]) for i in range(2))
            for beta in (Fraction(0), Fraction(1)))
        self.assertLessEqual(value, corner_best)
        witness = tuple(z0[i] + point[1] * generators[0][i] for i in range(2))
        self.assertEqual(max(abs(entry) for entry in witness), value)

    def test_vertex_enumeration_matches_bruteforce(self):
        cases = [
            ((Fraction(0), Fraction(1)),
             ((Fraction(-1), Fraction(-1)), (Fraction(-1), Fraction(1)))),
            ((Fraction(3, 2), Fraction(-1)),
             ((Fraction(2), Fraction(0)), (Fraction(-1), Fraction(1, 2)))),
            ((Fraction(-2), Fraction(2), Fraction(0)),
             ((Fraction(1), Fraction(-1), Fraction(1)),)),
            ((Fraction(1),), ()),
        ]
        for z0, generators in cases:
            with self.subTest(z0=z0, generators=generators):
                dimension = len(z0)
                box_count = len(generators)
                rows, rhs = [], []
                for i in range(dimension):
                    rows.append(tuple([Fraction(1)] + [g[i] for g in generators]))
                    rhs.append(-z0[i])
                    rows.append(tuple([Fraction(1)] + [-g[i] for g in generators]))
                    rhs.append(z0[i])
                for k in range(box_count):
                    row = [Fraction(0)] * (box_count + 1)
                    row[k + 1] = Fraction(1)
                    rows.append(tuple(row))
                    rhs.append(Fraction(0))
                    row = [Fraction(0)] * (box_count + 1)
                    row[k + 1] = Fraction(-1)
                    rows.append(tuple(row))
                    rhs.append(Fraction(-1))
                objective = tuple([Fraction(1)] + [Fraction(0)] * box_count)
                value, point, _ = primal_minimum(rows, tuple(rhs), objective)
                witness = tuple(
                    z0[i] + sum(generators[k][i] * point[1 + k] for k in range(box_count))
                    for i in range(dimension))
                self.assertEqual(max(abs(entry) for entry in witness), value)
                for coefficients in product((Fraction(0), Fraction(1)), repeat=box_count):
                    corner = tuple(
                        z0[i] + sum(generators[k][i] * coefficients[k]
                                    for k in range(box_count))
                        for i in range(dimension))
                    self.assertGreaterEqual(max(abs(entry) for entry in corner), value)


if __name__ == '__main__':
    unittest.main()
