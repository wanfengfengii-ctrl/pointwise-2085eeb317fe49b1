def make_disclosure(revision):
    return {
        'instrument_id': revision.instrument_id,
        'revision_id': revision.revision_id,
        'schedule_id': revision.schedule_id,
        'calibration_reference': revision.calibration.reference,
    }
