def validate_parent(parent_id, instrument_id, parent_instrument):
    """Check lineage using the parent identity read by the registering transaction."""
    if parent_id is None:
        return
    if type(parent_id) is not int or parent_id <= 0:
        raise ValueError('parent revision ID must be a positive integer')
    if parent_instrument is None:
        raise ValueError(f'parent revision does not exist: {parent_id}')
    if instrument_id != parent_instrument:
        raise ValueError('parent revision belongs to a different instrument')
