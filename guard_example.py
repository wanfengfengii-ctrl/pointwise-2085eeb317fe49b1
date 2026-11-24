import json
import sqlite3
from contextlib import closing
from pathlib import Path

from catalog.revisions import register_revision
from demo import prepare_center, prepare_source
from intake.admission import admit
from issuer.freeze import issue
from protocol.schedule import register_schedule
from review.archive import get_report
from review.publication import review


def read_case():
    path = Path(__file__).resolve().parent / "samples" / "guard.json"
    return json.loads(path.read_text(encoding="utf-8"))


def register_case(conn, sample):
    prepare_source(conn)
    schedule = register_schedule(conn, **sample["schedule"])
    revision_ids = []
    for side in sample["sides"]:
        parent = revision_ids[-1] if revision_ids else None
        revision = register_revision(conn, sample["instrument"], schedule.schedule_id,
                                     **side["revision"], parent_id=parent)
        revision_ids.append(revision.revision_id)
    return tuple(revision_ids)


def main():
    sample = read_case()
    with closing(sqlite3.connect(":memory:")) as bench:
        revisions = register_case(bench, sample)
        pieces = tuple(issue(bench, revision_id) for revision_id in revisions)
    with closing(sqlite3.connect(":memory:")) as center:
        prepare_center(center)
        receipts = tuple(admit(center, piece) for piece in pieces)
        drive = {int(beat): values for beat, values in sample["drive"].items()}
        report = review(center, tuple(item.receipt_id for item in receipts), drive,
                        sample["retained_beats"], drive_units=sample["schedule"]["drive_units"])
        archived = get_report(center, report.report_id)
        expected_evidence = tuple(item.provenance for item in receipts)
        if report.earliest_beat is not None or archived != report or report.evidence != expected_evidence:
            raise RuntimeError("V1 comparison differs from the guard sample")
        print(json.dumps({"case": "guard-v1-comparison", "outcome": report.outcome,
                          "earliest_beat": report.earliest_beat,
                          "retained_beats": report.retained_beats,
                          "archived": archived == report}, sort_keys=True))


if __name__ == "__main__":
    main()
