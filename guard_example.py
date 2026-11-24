import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path

from catalog.revisions import register_revision
from demo import prepare_center, prepare_source
from intake.admission import admit
from issuer.envelope import read_guard_envelope
from issuer.freeze import issue, issue_guard
from protocol.schedule import register_schedule
from review.archive import get_guard_report, get_report
from review.publication import review, review_guard


def read_case():
    path = Path(__file__).resolve().parent / "samples" / "guard.json"
    return json.loads(path.read_text(encoding="utf-8"))


def register_case(conn, sample):
    prepare_source(conn)
    schedule = register_schedule(conn, **sample["schedule"])
    revision_ids = []
    revisions = []
    for side in sample["sides"]:
        parent = revision_ids[-1] if revision_ids else None
        revision = register_revision(conn, sample["instrument"], schedule.schedule_id,
                                     **side["revision"], parent_id=parent)
        revisions.append(revision)
        revision_ids.append(revision.revision_id)
    return tuple(revisions)


def main():
    sample = read_case()
    units = sample["schedule"]["drive_units"]
    drive = {int(beat): values for beat, values in sample["drive"].items()}

    # V1 baseline: the original judgment cannot separate the two revisions.
    with closing(sqlite3.connect(":memory:")) as bench:
        revisions = register_case(bench, sample)
        v1_pieces = tuple(issue(bench, revision.revision_id) for revision in revisions)
        with closing(sqlite3.connect(":memory:")) as center:
            prepare_center(center)
            v1_receipts = tuple(admit(center, piece) for piece in v1_pieces)
            v1_report = review(center, tuple(item.receipt_id for item in v1_receipts),
                               drive, sample["retained_beats"], drive_units=units)
            assert v1_report.earliest_beat is None
            assert get_report(center, v1_report.report_id) == v1_report
            print(json.dumps({"case": "guard-v1-comparison", "outcome": v1_report.outcome,
                              "earliest_beat": v1_report.earliest_beat},
                             sort_keys=True))

    # V2 flow: freeze the permitted initial states, then run with the bench library closed.
    with closing(sqlite3.connect(":memory:")) as bench:
        revisions = register_case(bench, sample)
        guard_pieces = tuple(
            issue_guard(bench, revision.revision_id, side["origin"], side["directions"])
            for revision, side in zip(revisions, sample["sides"]))
        # The pieces are self-contained: version 2 and a reading-space permit, while the
        # private state model and calibration rows never leave the bench.
        assert all(read_guard_envelope(piece).version == 2 for piece in guard_pieces)

    with closing(sqlite3.connect(":memory:")) as center:
        prepare_center(center)
        receipts = tuple(admit(center, piece) for piece in guard_pieces)
        pair = tuple(item.receipt_id for item in receipts)

        passing_margin = Fraction(sample["minimum_margins"][0])
        strict_margin = Fraction(sample["minimum_margins"][1])
        passing = review_guard(center, pair, drive, sample["retained_beats"],
                               passing_margin, drive_units=units)
        strict = review_guard(center, pair, drive, sample["retained_beats"],
                              strict_margin, drive_units=units)
        assert passing.margin == Fraction(1, 2)
        assert passing.claimable and not strict.claimable
        assert passing.rule.weights == (Fraction(-1, 2), Fraction(1, 2))
        assert passing.rule.left_max == 0
        assert passing.rule.right_min == Fraction(1, 2)
        assert passing.rule.threshold == Fraction(1, 4)
        assert passing.waveforms == ((Fraction(1, 2), Fraction(1, 2)),
                                     (Fraction(0), Fraction(1)))
        # A closed center can re-fetch the whole signed record by its original ID.
        assert get_guard_report(center, passing.report_id) == passing
        print(json.dumps({
            "case": "guard-v2-closed-station",
            "margin": str(passing.margin),
            "weights": [str(value) for value in passing.rule.weights],
            "left_max": str(passing.rule.left_max),
            "right_min": str(passing.rule.right_min),
            "threshold": str(passing.rule.threshold),
            "waveforms": [[str(value) for value in vector] for vector in passing.waveforms],
            "claim_at_1_2": passing.claimable,
            "claim_at_3_4": strict.claimable,
            "archived": get_guard_report(center, passing.report_id) == passing,
        }, sort_keys=True))


if __name__ == "__main__":
    main()
