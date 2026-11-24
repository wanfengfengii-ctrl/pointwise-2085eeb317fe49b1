from dataclasses import dataclass
from fractions import Fraction

from protocol.lp import dual_scoring_vertex, primal_minimum


@dataclass(frozen=True)
class GuardResponse:
    """A V2 piece after the actual complete drive has been fixed.

    Every legal retained-beat reading vector is
    ``offset + origin + coef_1 * direction_1 + coef_2 * direction_2`` with each
    coefficient independently in the closed interval [0, 1] and shared across every
    beat of the run.
    """

    offsets: tuple[Fraction, ...]
    origin_readings: tuple[Fraction, ...]
    direction_readings: tuple[tuple[Fraction, ...], ...]

    def project(self, positions):
        directions = tuple(tuple(reading[position] for position in positions)
                           for reading in self.direction_readings)
        return ProjectedResponse(
            tuple(self.offsets[position] for position in positions),
            tuple(self.origin_readings[position] for position in positions),
            directions,
        )


@dataclass(frozen=True)
class ProjectedResponse:
    offsets: tuple[Fraction, ...]
    origin_readings: tuple[Fraction, ...]
    direction_readings: tuple[tuple[Fraction, ...], ...]

    @property
    def constant(self):
        """Reading at the基点 (all coefficients zero), per retained beat."""
        return tuple(origin + offset
                     for origin, offset in zip(self.origin_readings, self.offsets, strict=True))

    def reading(self, coefficients):
        if len(coefficients) != len(self.direction_readings):
            raise ValueError('guard permit coefficient count does not match its directions')
        return tuple(
            self.origin_readings[index]
            + sum(coefficient * direction[index]
                  for coefficient, direction in zip(coefficients, self.direction_readings,
                                                     strict=True))
            + self.offsets[index]
            for index in range(len(self.offsets)))


@dataclass(frozen=True)
class MarginResult:
    margin: Fraction
    weights: tuple[Fraction, ...]
    left_max: Fraction
    right_min: Fraction
    threshold: Fraction
    left_waveform: tuple[Fraction, ...]
    right_waveform: tuple[Fraction, ...]


def fix_guard_drive(evidence, drive):
    channels = tuple(unit.channel for unit in drive.units)
    if drive.beat_ids != evidence.beat_ids or channels != evidence.channels:
        raise ValueError('drive and waveform use different coordinates')
    vector = drive.vector
    offsets = tuple(sum((coefficient * value for coefficient, value in zip(row, vector, strict=True)),
                        Fraction(0)) for row in evidence.drive_rows)
    return GuardResponse(offsets, evidence.permission.origin_readings,
                         evidence.permission.direction_readings)


def _build_program(z0, generators):
    """Primal: minimize t over -t <= z_i <= t with z in the difference box.

    Rows are emitted per retained beat as the pair (a_i, u_i), so dual multiplier
    indices 2*i and 2*i+1 map directly to the lower and upper bound of beat i.  The
    final 2*m rows encode 0 <= beta_k <= 1 as beta_k >= 0 and -beta_k >= -1.
    """
    dimension = len(z0)
    box_count = len(generators)
    rows = []
    rhs = []
    for index in range(dimension):
        # z_i = z0_i + sum_k g_ki beta_k.
        # Lower bound t >= -z_i  <=>  t + sum_k g_ki beta_k >= -z0_i.
        rows.append(tuple([Fraction(1)]
                          + [generator[index] for generator in generators]))
        rhs.append(-z0[index])
        # Upper bound t >= z_i  <=>  t - sum_k g_ki beta_k >= z0_i.
        rows.append(tuple([Fraction(1)]
                          + [-generator[index] for generator in generators]))
        rhs.append(z0[index])
    for box in range(box_count):
        row = [Fraction(0)] * (box_count + 1)
        row[box + 1] = Fraction(1)
        rows.append(tuple(row))
        rhs.append(Fraction(0))
    for box in range(box_count):
        row = [Fraction(0)] * (box_count + 1)
        row[box + 1] = Fraction(-1)
        rows.append(tuple(row))
        rhs.append(Fraction(-1))
    objective = tuple([Fraction(1)] + [Fraction(0)] * box_count)
    return rows, tuple(rhs), objective


def _score(vector, weights):
    return sum(coefficient * value for coefficient, value in zip(weights, vector, strict=True))


def _extreme_coefficients(response, weights, *, maximize):
    coefficients = []
    for direction in response.direction_readings:
        contribution = _score(direction, weights)
        if maximize:
            coefficient = Fraction(1) if contribution > 0 else Fraction(0)
        else:
            coefficient = Fraction(1) if contribution < 0 else Fraction(0)
        coefficients.append(coefficient)
    return tuple(coefficients)


def compute_margin(left, right):
    """Exact largest guaranteed separation between two permitted reading sets.

    ``margin = max over ||w||_1 <= 1 of (min right score - max left score)``.  The
    returned waveform pair is realizable by the two admitted pieces and its maximum
    per-beat absolute difference equals the signed margin.  Every value is rational.
    """
    if len(left.offsets) != len(right.offsets):
        raise ValueError('guard responses must cover the same retained beats')
    dimension = len(left.offsets)

    # z = y_right - y_left.  The two permits choose their box coefficients
    # independently, so the difference box carries every left direction negated
    # followed by every right direction.
    z0 = tuple(right.constant[index] - left.constant[index]
               for index in range(dimension))
    generators = (tuple(tuple(-direction[index] for index in range(dimension))
                        for direction in left.direction_readings)
                  + tuple(right.direction_readings))
    left_count = len(left.direction_readings)

    rows, rhs, objective = _build_program(z0, generators)
    margin, point, _ = primal_minimum(rows, rhs, objective)
    box_coefficients = tuple(point[1:])
    left_coefficients = box_coefficients[:left_count]
    right_coefficients = box_coefficients[left_count:]
    left_waveform = left.reading(left_coefficients)
    right_waveform = right.reading(right_coefficients)
    achieved = max(abs(r_value - l_value)
                   for r_value, l_value in zip(right_waveform, left_waveform, strict=True))
    if achieved != margin:
        raise ValueError('guard witness pair does not reach the signed margin')

    if margin == 0:
        if left_waveform != right_waveform:
            raise ValueError('zero margin requires a shared waveform')
        return MarginResult(margin, tuple(), Fraction(0), Fraction(0), Fraction(0),
                            left_waveform, right_waveform)

    box_count = len(generators)

    def is_scoring_witness(multipliers):
        candidate_weights = tuple(multipliers[2 * index + 1] - multipliers[2 * index]
                                  for index in range(dimension))
        # A valid discriminator scores no point of the difference permit box below the
        # signed margin; linear extrema over a box occur at its corners.
        for corner in range(2 ** box_count):
            score = Fraction(0)
            for index in range(dimension):
                value = z0[index]
                for box in range(box_count):
                    if (corner >> box) & 1:
                        value += generators[box][index]
                score += candidate_weights[index] * value
            if score < margin:
                return False
        return True

    multipliers = dual_scoring_vertex(rows, rhs, objective, margin, point,
                                      is_scoring_witness)
    weights = tuple(multipliers[2 * index + 1] - multipliers[2 * index]
                    for index in range(dimension))
    weight_norm = sum(abs(weight) for weight in weights)
    if weight_norm > 1:
        raise ValueError('guard scoring vector exceeds the unit ball')

    left_max_vector = left.reading(_extreme_coefficients(left, weights, maximize=True))
    right_min_vector = right.reading(_extreme_coefficients(right, weights, maximize=False))
    left_max = _score(left_max_vector, weights)
    right_min = _score(right_min_vector, weights)
    if right_min - left_max != margin:
        raise ValueError('guard score separation does not match the signed margin')
    threshold = (left_max + right_min) / 2
    return MarginResult(margin, weights, left_max, right_min, threshold,
                        left_waveform, right_waveform)
