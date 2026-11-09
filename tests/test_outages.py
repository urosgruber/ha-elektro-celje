"""Tests for outage math."""

from datetime import datetime, time

from custom_components.elektro_celje.models import (
    Interval,
    Notice,
    Outage,
    ParseStatus,
)
from custom_components.elektro_celje.outages import (
    build_outages,
    days_until,
    is_active,
    is_planned,
    next_boundary,
    reminder_at,
)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def outage(
    start: str | None = "2026-11-10T08:30+01:00",
    end: str | None = "2026-11-10T11:00+01:00",
    status: ParseStatus = ParseStatus.OK,
    all_day: bool = False,
    key: str = "1:0",
) -> Outage:
    return Outage(
        key=key,
        notice_id=key.split(":")[0],
        region="celje",
        station_text="Zabukovica",
        text="text",
        link="https://example.com",
        status=status,
        start=at(start) if start else None,
        end=at(end) if end else None,
        all_day=all_day,
    )


def failed() -> Outage:
    return outage(start=None, end=None, status=ParseStatus.FAILED)


def date_only() -> Outage:
    return outage(
        start="2026-11-10T00:00+01:00",
        end="2026-11-11T00:00+01:00",
        status=ParseStatus.DATE_ONLY,
        all_day=True,
    )


def test_planned_until_end():
    o = outage()
    assert is_planned(o, at("2026-11-10T10:59+01:00"))
    assert not is_planned(o, at("2026-11-10T11:00+01:00"))


def test_failed_always_planned():
    assert is_planned(failed(), at("2030-01-01T00:00+01:00"))


def test_date_only_planned_until_midnight():
    o = date_only()
    assert is_planned(o, at("2026-11-10T23:59+01:00"))
    assert not is_planned(o, at("2026-11-11T00:00+01:00"))


def test_active_only_for_ok():
    o = outage()
    assert not is_active(o, at("2026-11-10T08:29+01:00"))
    assert is_active(o, at("2026-11-10T08:30+01:00"))
    assert not is_active(o, at("2026-11-10T11:00+01:00"))
    assert not is_active(date_only(), at("2026-11-10T12:00+01:00"))
    assert not is_active(failed(), at("2026-11-10T12:00+01:00"))


def test_days_until_counts_local_dates():
    o = outage()
    assert days_until(o, at("2026-11-09T23:59+01:00")) == 1
    assert days_until(o, at("2026-11-10T00:00+01:00")) == 0
    assert days_until(o, at("2026-11-10T09:00+01:00")) == 0
    assert days_until(o, at("2026-11-12T09:00+01:00")) == 0
    assert days_until(failed(), at("2026-11-09T09:00+01:00")) is None


def test_days_until_across_dst():
    o = outage(start="2027-03-29T08:00+02:00", end="2027-03-29T10:00+02:00")
    assert days_until(o, at("2027-03-27T12:00+01:00")) == 2


def test_reminder_at_day_before():
    assert reminder_at(outage(), time(18)) == at("2026-11-09T18:00+01:00")
    assert reminder_at(failed(), time(18)) is None


def test_next_boundary_picks_earliest():
    o = outage()
    r = time(18)
    # next start
    assert next_boundary([o], at("2026-11-10T07:00+01:00"), r) == at(
        "2026-11-10T08:30+01:00"
    )
    # next end
    assert next_boundary([o], at("2026-11-10T09:00+01:00"), r) == at(
        "2026-11-10T11:00+01:00"
    )
    # reminder
    assert next_boundary([o], at("2026-11-09T17:00+01:00"), r) == at(
        "2026-11-09T18:00+01:00"
    )
    # midnight
    assert next_boundary([o], at("2026-11-09T19:00+01:00"), r) == at(
        "2026-11-10T00:00+01:00"
    )
    # no outages: next midnight
    assert next_boundary([], at("2026-11-09T19:00+01:00"), r) == at(
        "2026-11-10T00:00+01:00"
    )
    # failed outage is ignored
    assert next_boundary([failed()], at("2026-11-09T19:00+01:00"), r) == at(
        "2026-11-10T00:00+01:00"
    )


def make_notice(
    status: ParseStatus = ParseStatus.OK,
    intervals: tuple[Interval, ...] = (),
    names: tuple[str, ...] = ("Zabukovica",),
    notice_id: str = "n1",
) -> Notice:
    return Notice(
        notice_id=notice_id,
        region="celje",
        title="t",
        link="https://example.com/n",
        station_text="Zabukovica",
        station_names=names,
        text="body",
        date_texts=(),
        intervals=intervals,
        status=status,
        reason=None,
    )


def iv(start: str, end: str, all_day: bool = False) -> Interval:
    return Interval(at(start), at(end), all_day)


def test_build_outages_two_li_two_outages():
    notice = make_notice(
        intervals=(
            iv("2026-11-12T08:00+01:00", "2026-11-12T10:00+01:00"),
            iv("2026-11-10T08:00+01:00", "2026-11-10T10:00+01:00"),
        )
    )
    result = build_outages([notice], "Zabukovica")
    assert [o.key for o in result] == ["n1:1", "n1:0"]
    assert result[0].start < result[1].start


def test_build_outages_filters_by_query():
    notice = make_notice(
        intervals=(iv("2026-11-10T08:00+01:00", "2026-11-10T10:00+01:00"),)
    )
    assert build_outages([notice], "Elsewhere") == []


def test_build_outages_failed_gives_one_unknown_outage():
    notice = make_notice(
        status=ParseStatus.FAILED,
        intervals=(iv("2026-11-10T08:00+01:00", "2026-11-10T10:00+01:00"),),
    )
    (o,) = build_outages([notice], "Zabukovica")
    assert o.key == "n1:0"
    assert o.start is None and o.end is None
    assert o.status is ParseStatus.FAILED


def test_build_outages_sorted_none_last():
    bad = make_notice(status=ParseStatus.FAILED, notice_id="bad")
    good = make_notice(
        notice_id="good",
        intervals=(iv("2026-11-10T08:00+01:00", "2026-11-10T10:00+01:00"),),
    )
    result = build_outages([bad, good], "Zabukovica")
    assert [o.notice_id for o in result] == ["good", "bad"]


def test_build_outages_date_only_all_day():
    notice = make_notice(
        status=ParseStatus.DATE_ONLY,
        intervals=(
            iv("2026-11-10T00:00+01:00", "2026-11-11T00:00+01:00", all_day=True),
        ),
    )
    (o,) = build_outages([notice], "Zabukovica")
    assert o.all_day and o.status is ParseStatus.DATE_ONLY
