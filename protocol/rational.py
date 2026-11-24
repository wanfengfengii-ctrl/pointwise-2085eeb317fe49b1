from fractions import Fraction


def read_rational(value):
    """Read an exact number at a business boundary."""
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f'invalid rational: {value!r}') from exc
    raise ValueError(f'invalid rational: {value!r}')


def encode_rational(value):
    return str(read_rational(value))


def read_matrix(value, height, width, field):
    if not isinstance(value, (list, tuple)) or len(value) != height:
        raise ValueError(f'{field}: expected {height} rows')
    rows = []
    for index, row in enumerate(value, start=1):
        if not isinstance(row, (list, tuple)) or len(row) != width:
            raise ValueError(f'{field}: row {index} must have {width} columns')
        try:
            rows.append(tuple(read_rational(entry) for entry in row))
        except ValueError as exc:
            raise ValueError(f'{field}: invalid rational in row {index}') from exc
    return tuple(rows)


def encode_matrix(matrix):
    return [[encode_rational(entry) for entry in row] for row in matrix]
