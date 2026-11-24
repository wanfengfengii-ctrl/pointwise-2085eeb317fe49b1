from fractions import Fraction
from itertools import combinations


def solve_linear_system(matrix, rhs):
    """Exact rational Gaussian elimination; return None for a singular system."""
    order = len(matrix)
    table = [list(map(Fraction, row)) + [Fraction(value)]
             for row, value in zip(matrix, rhs, strict=True)]
    for column in range(order):
        pivot = next((row for row in range(column, order) if table[row][column]), None)
        if pivot is None:
            return None
        table[column], table[pivot] = table[pivot], table[column]
        divisor = table[column][column]
        table[column] = [value / divisor for value in table[column]]
        for row in range(order):
            if row == column or not table[row][column]:
                continue
            factor = table[row][column]
            table[row] = [value - factor * basis
                          for value, basis in zip(table[row], table[column])]
    return [table[row][order] for row in range(order)]


def _is_feasible(rows, rhs, point):
    for row, bound in zip(rows, rhs, strict=True):
        if sum(coefficient * value for coefficient, value in zip(row, point, strict=True)) < bound:
            return False
    return True


def primal_minimum(rows, rhs, objective):
    """Minimize c.x subject to A x >= b by enumerating basic feasible solutions.

    The guard linear programs are tiny (one slack variable plus at most four box
    variables), so exact vertex enumeration keeps every result rational without a
    floating-point simplex implementation.
    """
    variable_count = len(objective)
    row_count = len(rows)
    best = None
    for combo in combinations(range(row_count), variable_count):
        basis = [rows[index] for index in combo]
        point = solve_linear_system(basis, [rhs[index] for index in combo])
        if point is None or not _is_feasible(rows, rhs, point):
            continue
        value = sum(coefficient * entry for coefficient, entry in zip(objective, point))
        candidate = (value, point, combo)
        if best is None or value < best[0] or (value == best[0] and combo < best[2]):
            best = candidate
    if best is None:
        raise ValueError('guard margin program has no feasible basic solution')
    return best


def dual_scoring_vertex(rows, rhs, objective, target, primal_point, is_witness):
    """Enumerate dual basic optima on the optimal face and return the first accepted one.

    The optimal face holds every row tight at the primal optimum.  Every dual optimum
    is supported inside that face, so restricting the basis search to it loses no
    solution while making the enumeration small even for degenerate programs.  Each
    candidate is checked against the *full* dual equality system (A^T y = c) and
    non-negativity, so non-basic dual variables cannot silently break feasibility.
    ``is_witness`` applies the exact box-score acceptance test for the discriminator.
    """
    variable_count = len(objective)
    row_count = len(rows)
    face = [
        row_index
        for row_index, row in enumerate(rows)
        if sum(coefficient * value
               for coefficient, value in zip(row, primal_point, strict=True))
        == rhs[row_index]
    ]
    for combo in combinations(face, variable_count):
        basis = [rows[index] for index in combo]
        basic = solve_linear_system(
            [list(column) for column in zip(*basis, strict=True)], objective)
        if basic is None or any(value < 0 for value in basic):
            continue
        multipliers = [Fraction(0)] * row_count
        for index, value in zip(combo, basic):
            multipliers[index] = value
        if any(sum(rows[row][column] * multipliers[row] for row in range(row_count))
               != objective[column] for column in range(variable_count)):
            continue
        if sum(bound * multipliers[row] for row, bound in enumerate(rhs)) != target:
            continue
        candidate = tuple(multipliers)
        if is_witness(candidate):
            return candidate
    raise ValueError('guard margin dual has no scoring optimum')
