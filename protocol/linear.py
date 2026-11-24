from fractions import Fraction


def reduce_rows(rows):
    """Return the nonzero reduced row echelon rows over the rationals."""
    matrix = [list(map(Fraction, row)) for row in rows]
    if not matrix:
        return ()
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ValueError('row reduction requires a rectangular matrix')
    pivot_row = 0
    for column in range(width):
        found = next((index for index in range(pivot_row, len(matrix))
                      if matrix[index][column]), None)
        if found is None:
            continue
        matrix[pivot_row], matrix[found] = matrix[found], matrix[pivot_row]
        pivot = matrix[pivot_row][column]
        normalized = [value / pivot for value in matrix[pivot_row]]
        matrix[pivot_row] = normalized
        for index, row in enumerate(matrix):
            if index == pivot_row or not row[column]:
                continue
            factor = row[column]
            matrix[index] = [value - factor * basis for value, basis in zip(row, normalized)]
        pivot_row += 1
        if pivot_row == len(matrix):
            break
    return tuple(tuple(row) for row in matrix[:pivot_row])


def span_basis(vectors):
    """Return a basis written in the coordinates of the supplied vectors."""
    return reduce_rows(vectors)


def has_rational_solution(coefficients, right_hand_side):
    augmented = (tuple(row) + (value,)
                 for row, value in zip(coefficients, right_hand_side, strict=True))
    return all(any(row[:-1]) or not row[-1] for row in reduce_rows(augmented))
