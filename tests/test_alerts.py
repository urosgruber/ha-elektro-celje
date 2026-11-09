"""Tests for alert evaluation."""

from datetime import datetime, time

from custom_components.elektro_celje.alerts import (
    OutageRecord,
    evaluate,
    event_payload,
    event_type,
)
from custom_components.elektro_celje.const import (
    EVENT_OUTAGE_CHANGED,
    EVENT_OUTAGE_DETECTED,
    EVENT_OUTAGE_REMINDER,
    EVENT_OUTAGE_REMOVED,
    TZ,
)
from custom_components.elektro_celje.models import Outage, ParseStatus

REM = time(18, 0)
OK = {"celje"}


def dt(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def outage(key="1:0", start=None, end=None, status=ParseStatus.OK, all_day=False):
    if status is not ParseStatus.FAILED:
        start = start or dt(11, 8, 30)
        end = end or dt(11, 11)
    return Outage(
        key=key,
        notice_id=key.split(":")[0],
        region="celje",
        station_text="TP Test",
        text="text",
        link="https://example.com",
        status=status,
        start=start,
        end=end,
        all_day=all_day,
    )


def run(records, outages, now, ok=OK):
    events, new = evaluate(records, outages, now, ok, REM)
    return [e.kind for e in events], new, events


def test_new_outage_fires_detected_once():
    kinds, recs, _ = run({}, [outage()], dt(9, 10))
    assert kinds == ["detected"]
    kinds, _, _ = run(recs, [outage()], dt(9, 10, 15))
    assert kinds == []


def test_reminder_fires_at_reminder_time():
    _, recs, _ = run({}, [outage()], dt(9, 10))
    kinds, recs, _ = run(recs, [outage()], dt(10, 17, 59))
    assert kinds == []
    kinds, recs, _ = run(recs, [outage()], dt(10, 18))
    assert kinds == ["reminder"]
    kinds, _, _ = run(recs, [outage()], dt(10, 18, 15))
    assert kinds == []


def test_late_detection_skips_reminder():
    kinds, recs, _ = run({}, [outage()], dt(10, 20))
    assert kinds == ["detected"]
    assert recs["1:0"].reminder_sent is True
    kinds, _, _ = run(recs, [outage()], dt(10, 21))
    assert kinds == []


def test_changed_time_fires_changed_with_old_times():
    _, recs, _ = run({}, [outage()], dt(9, 10))
    new = outage(start=dt(11, 9), end=dt(11, 12))
    kinds, recs, events = run(recs, [new], dt(9, 11))
    assert kinds == ["changed"]
    assert events[0].old_start == dt(11, 8, 30)
    assert events[0].old_end == dt(11, 11)
    assert recs["1:0"].start == dt(11, 9)


def test_changed_status_failed_to_ok():
    _, recs, _ = run({}, [outage(status=ParseStatus.FAILED)], dt(9, 10))
    kinds, recs, events = run(recs, [outage()], dt(9, 11))
    assert kinds == ["changed"]
    assert events[0].old_start is None
    assert recs["1:0"].status is ParseStatus.OK


def test_changed_time_rearms_reminder():
    _, recs, _ = run({}, [outage()], dt(10, 12))
    kinds, recs, _ = run(recs, [outage()], dt(10, 18))
    assert kinds == ["reminder"]
    new = outage(start=dt(12, 8), end=dt(12, 10))
    kinds, recs, _ = run(recs, [new], dt(10, 19))
    assert kinds == ["changed"]
    assert recs["1:0"].reminder_sent is False
    kinds, _, _ = run(recs, [new], dt(11, 18))
    assert kinds == ["reminder"]


def test_removed_before_end_fires_removed():
    _, recs, _ = run({}, [outage()], dt(9, 10))
    kinds, recs, _ = run(recs, [], dt(9, 11))
    assert kinds == ["removed"]
    assert recs == {}


def test_removed_after_end_is_silent():
    _, recs, _ = run({}, [outage()], dt(9, 10))
    kinds, recs, _ = run(recs, [], dt(11, 12))
    assert kinds == []
    assert recs == {}


def test_failed_notice_never_fires_removed():
    _, recs, _ = run({}, [outage(status=ParseStatus.FAILED)], dt(9, 10))
    kinds, recs, _ = run(recs, [], dt(9, 11))
    assert kinds == []
    assert recs == {}


def test_failed_notice_never_fires_reminder():
    _, recs, _ = run({}, [outage(status=ParseStatus.FAILED)], dt(9, 10))
    kinds, _, _ = run(recs, [outage(status=ParseStatus.FAILED)], dt(10, 18))
    assert kinds == []


def test_date_only_removed_same_day_fires_removed():
    o = outage(
        status=ParseStatus.DATE_ONLY,
        start=dt(11, 0),
        end=dt(12, 0),
        all_day=True,
    )
    _, recs, _ = run({}, [o], dt(9, 10))
    kinds, _, _ = run(recs, [], dt(11, 9))
    assert kinds == ["removed"]


def test_no_reminder_after_start():
    _, recs, _ = run({}, [outage()], dt(9, 10))
    recs["1:0"].reminder_sent = False
    kinds, _, _ = run(recs, [outage()], dt(11, 9))
    assert kinds == []


def test_no_removed_when_region_failed():
    _, recs, _ = run({}, [outage()], dt(9, 10))
    kinds, recs2, _ = run(recs, [], dt(9, 11), ok=set())
    assert kinds == []
    assert recs2 == recs


def test_records_round_trip_through_dict():
    _, recs, _ = run({}, [outage()], dt(9, 10))
    rec = recs["1:0"]
    data = rec.to_dict()
    assert data["status"] == "ok"
    assert isinstance(data["start"], str)
    assert OutageRecord.from_dict(data) == rec
    _, recs, _ = run({}, [outage(status=ParseStatus.FAILED)], dt(9, 10))
    rec = recs["1:0"]
    assert OutageRecord.from_dict(rec.to_dict()) == rec


def test_event_type_mapping():
    assert event_type("detected") == EVENT_OUTAGE_DETECTED
    assert event_type("reminder") == EVENT_OUTAGE_REMINDER
    assert event_type("changed") == EVENT_OUTAGE_CHANGED
    assert event_type("removed") == EVENT_OUTAGE_REMOVED


def test_payload_keys_and_duration():
    _, recs, events = run({}, [outage()], dt(9, 10))
    p = event_payload(events[0], "Home", "abc")
    assert set(p) == {
        "location", "entry_id", "notice_id", "region", "station", "start",
        "end", "all_day", "duration_minutes", "status", "text", "link",
    }  # fmt: skip
    assert p["duration_minutes"] == 150
    assert p["status"] == "ok"
    assert p["station"] == "TP Test"
    new = outage(start=dt(11, 9), end=dt(11, 12))
    _, _, events = run(recs, [new], dt(9, 11))
    p = event_payload(events[0], "Home", "abc")
    assert p["old_start"] == dt(11, 8, 30).isoformat()
    assert p["old_end"] == dt(11, 11).isoformat()
    _, _, events = run({}, [outage(status=ParseStatus.FAILED)], dt(9, 10))
    p = event_payload(events[0], "Home", "abc")
    assert p["start"] is None
    assert p["duration_minutes"] is None
