from review.observable import can_share_waveform


def earliest_distinguishing_beat(left, right, retention):
    for length, beat in enumerate(retention.beat_ids, start=1):
        if not can_share_waveform(left, right, retention.positions[:length]):
            return beat
    return None
