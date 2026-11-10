"""Tests of the card text builder."""

from datetime import datetime, timedelta

from custom_components.elektro_celje.cardtext import build_card
from custom_components.elektro_celje.const import TZ
from custom_components.elektro_celje.location import LocationData
from custom_components.elektro_celje.models import Outage, ParseStatus


def _t(month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


def _o(
    key: str,
    start: datetime | None,
    end: datetime | None,
    status: ParseStatus = ParseStatus.OK,
    all_day: bool = False,
    text: str = "Vzdrževanje",
) -> Outage:
    return Outage(
        key=key,
        notice_id=key,
        region="velenje",
        station_text="TP Zabukovica",
        text=text,
        link="https://example.com",
        status=status,
        start=start,
        end=end,
        all_day=all_day,
    )


def _data(
    outages: list[Outage],
    planned: list[Outage] | None = None,
    last_success: datetime | None = None,
    problem_since: datetime | None = None,
) -> LocationData:
    now_planned = (
        planned
        if planned is not None
        else [o for o in outages if o.end is None or o.end > _t(11, 9, 12)]
    )
    return LocationData(
        outages=outages,
        planned=now_planned,
        records={},
        feed_urls=[],
        last_attempt=last_success,
        last_success=last_success,
        problem_since=problem_since,
        feed_ok=problem_since is None,
    )


NOW = _t(11, 9, 12)


def _card(outages, now=NOW, lang="en", **kwargs) -> dict:
    planned = [o for o in outages if o.end is None or o.end > now]
    return build_card(_data(outages, planned, **kwargs), "Dom", now, lang)


def test_next_tomorrow_english() -> None:
    result = _card([_o("a", _t(11, 10, 8, 30), _t(11, 10, 11))])
    item = result["card"][0]
    assert item["location"] == "Dom"
    assert item["group"] == "next"
    assert item["title"] == "Tomorrow, Tue 10 Nov · 08:30–11:00"
    assert item["detail"] == "2 h 30 min · tomorrow"
    assert item["day"] == "Tue 10 Nov"
    assert item["row"] == "08:30–11:00 · 2 h 30 min · tomorrow"
    assert item["sort"] == "2026-11-10T07:30:00+00:00"


def test_next_today_and_in_days() -> None:
    result = _card(
        [
            _o("a", _t(11, 9, 14), _t(11, 9, 16)),
            _o("b", _t(11, 12, 8), _t(11, 12, 14)),
        ]
    )
    today, later = result["card"]
    assert today["title"] == "Today · 14:00–16:00"
    assert today["detail"] == "2 h · today"
    assert later["title"] == "Thu 12 Nov · 08:00–14:00"
    assert later["row"] == "08:00–14:00 · 6 h · in 3 days"


def test_all_day_and_unknown_time() -> None:
    result = _card(
        [
            _o("a", _t(11, 12), _t(11, 13), ParseStatus.DATE_ONLY, all_day=True),
            _o("b", None, None, ParseStatus.FAILED, text="x" * 200),
        ]
    )
    all_day, failed = result["card"]
    assert all_day["title"] == "Thu 12 Nov · all day"
    assert all_day["detail"] == "in 3 days"
    assert all_day["row"] == "all day · in 3 days"
    assert failed["title"] == "Date unknown · time unknown"
    assert failed["detail"] == "x" * 120
    assert failed["row"] == "time unknown · " + "x" * 120
    assert failed["day"] == "Date unknown"
    assert failed["sort"] > all_day["sort"]


def test_live_outage() -> None:
    result = _card([_o("a", _t(11, 9, 11), _t(11, 9, 13))])
    item = result["card"][0]
    assert item["group"] == "live"
    assert item["title"] == "Outage now · 11:00–13:00"
    assert item["detail"] == "until 13:00"


def test_ended_today_group() -> None:
    result = _card(
        [
            _o("a", _t(11, 9, 8, 30), _t(11, 9, 11)),
            _o("b", _t(11, 8, 8), _t(11, 8, 10)),
        ]
    )
    assert [i["group"] for i in result["card"]] == ["ended"]
    assert result["card"][0]["title"] == "08:30–11:00 · ended"


def test_ended_today_excludes_failed_and_midnight_end() -> None:
    result = _card(
        [
            _o("f", None, None, ParseStatus.FAILED),
            _o("m", _t(11, 8, 22), _t(11, 9, 0)),
        ]
    )
    assert [i["group"] for i in result["card"]] == ["next"]


def test_labels_footer_problem_english() -> None:
    result = _card(
        [],
        last_success=_t(11, 9, 12, 23),
        problem_since=NOW - timedelta(hours=2),
    )
    assert result["card_labels"]["also_planned"] == "Also planned"
    assert result["card_labels"]["ended_today"] == "Ended today"
    assert result["card_labels"]["nothing_planned"] == "No planned outages"
    assert result["card_footer"] == "Checked Mon 9 Nov 2026, 12:23 · elektro-celje.si"
    assert result["card_problem"] == (
        "Cannot read the Elektro Celje feed. Last good check: today 12:23. "
        "The list below may be old."
    )


def test_short_problem_and_no_success() -> None:
    result = _card([], problem_since=NOW - timedelta(minutes=30))
    assert result["card_problem"] is None
    assert result["card_footer"] is None
    long = _card([], problem_since=NOW - timedelta(hours=2))
    assert long["card_problem"].endswith(
        "Last good check: –. The list below may be old."
    )


def test_problem_last_good_other_day() -> None:
    result = _card(
        [], last_success=_t(11, 7, 9, 5), problem_since=NOW - timedelta(hours=2)
    )
    assert "Last good check: Sat 7 Nov, 09:05." in result["card_problem"]


def test_slovenian() -> None:
    result = _card(
        [
            _o("a", _t(11, 10, 8, 30), _t(11, 10, 11)),
            _o("b", _t(11, 12, 8), _t(11, 12, 14)),
            _o("c", _t(11, 9, 8, 30), _t(11, 9, 11)),
            _o("d", _t(11, 13), _t(11, 14), ParseStatus.DATE_ONLY, all_day=True),
        ],
        lang="sl",
        last_success=_t(11, 9, 12, 23),
        problem_since=NOW - timedelta(hours=2),
    )
    by_key = {i["row"]: i for i in result["card"]}
    assert by_key["08:30–11:00 · 2 h 30 min · jutri"]["title"] == (
        "Jutri, tor 10. nov · 08:30–11:00"
    )
    assert (
        by_key["08:00–14:00 · 6 h · čez 3 dni"]["title"] == "čet 12. nov · 08:00–14:00"
    )
    assert by_key["ves dan · čez 4 dni"]["title"] == "pet 13. nov · ves dan"
    assert result["card_labels"]["ended_today"] == "Danes končani izklopi"
    assert result["card_labels"]["nothing_planned"] == "Ni načrtovanih izklopov"
    assert result["card_labels"]["also_planned"] == "Še načrtovani izklopi"
    assert result["card_footer"].startswith("Preverjeno pon 9. nov 2026, 12:23")
    assert "Zadnje uspešno preverjanje: danes 12:23." in result["card_problem"]


def test_language_fallback() -> None:
    assert _card([], lang="de")["card_labels"]["ended_today"] == "Ended today"
    assert (
        _card([], lang="sl-SI")["card_labels"]["ended_today"] == "Danes končani izklopi"
    )


def test_midnight_roll_over() -> None:
    outage = _o("a", _t(11, 10, 8), _t(11, 10, 10))
    before = _card([outage], now=_t(11, 9, 23, 59))["card"][0]
    after = _card([outage], now=_t(11, 10, 0, 1))["card"][0]
    assert before["title"].startswith("Tomorrow, ")
    assert after["title"].startswith("Today · ")


def test_midnight_clears_ended() -> None:
    outage = _o("a", _t(11, 9, 8), _t(11, 9, 10))
    assert _card([outage], now=_t(11, 9, 23, 59))["card"][0]["group"] == "ended"
    assert _card([outage], now=_t(11, 10, 0, 1))["card"] == []


def test_dst_change_day() -> None:
    """On 25 Oct 2026 the clock goes back. 01:00 to 05:00 lasts five hours."""
    now = _t(10, 24, 23)
    outage = _o("a", _t(10, 25, 1), _t(10, 25, 5))
    item = build_card(_data([outage], [outage]), "Dom", now, "en")["card"][0]
    assert item["title"] == "Tomorrow, Sun 25 Oct · 01:00–05:00"
    assert item["detail"].startswith("5 h")


def test_sort_uses_utc() -> None:
    a = _o("a", _t(10, 25, 2), _t(10, 25, 3))
    b = _o("b", _t(10, 26, 8), _t(10, 26, 9))
    items = build_card(_data([a, b], [a, b]), "Dom", _t(10, 20), "en")["card"]
    assert items[0]["sort"] < items[1]["sort"]


def test_slovenian_wording() -> None:
    result = _card(
        [_o("a", _t(11, 9, 11), _t(11, 9, 13))],
        lang="sl",
        last_success=_t(11, 9, 12, 23),
        problem_since=NOW - timedelta(hours=2),
    )
    assert result["card"][0]["title"].startswith("Izklop zdaj · ")
    assert result["card_labels"]["also_planned"] == "Še načrtovani izklopi"
    assert result["card_labels"]["ended_today"] == "Danes končani izklopi"
    assert result["card_problem"].endswith(" Spodnji seznam je morda zastarel.")
    from custom_components.elektro_celje.cardtext import TEXTS

    assert "izpad" not in str(TEXTS).lower()


def test_problem_warns_that_the_list_may_be_old() -> None:
    result = _card([], problem_since=NOW - timedelta(hours=2))
    assert result["card_problem"].endswith(" The list below may be old.")


def test_feed_text_is_cleaned() -> None:
    text = 'Izklop "A" <b>\n  zaradi\tdel</b>'
    failed = _o("f", None, None, ParseStatus.FAILED, text=text)
    item = _card([failed])["card"][0]
    assert item["detail"] == 'Izklop "A" <b> zaradi del</b>'
    assert item["row"] == 'time unknown · Izklop "A" <b> zaradi del</b>'


def test_span_and_chip_english() -> None:
    """The card shows the time span and a relative-day chip in separate parts."""
    result = _card(
        [
            _o("a", _t(11, 10, 8, 30), _t(11, 10, 11)),
            _o("b", _t(11, 12, 8), _t(11, 12, 14)),
            _o("c", _t(11, 13), _t(11, 14), ParseStatus.DATE_ONLY, all_day=True),
            _o("d", _t(11, 9, 14), _t(11, 9, 16)),
            _o("f", None, None, ParseStatus.FAILED, text="Notice"),
        ]
    )
    by_row = {i["row"]: i for i in result["card"]}
    tomorrow = by_row["08:30–11:00 · 2 h 30 min · tomorrow"]
    assert tomorrow["span"] == "08:30–11:00 · 2 h 30 min"
    assert tomorrow["chip"] == "tomorrow"
    later = by_row["08:00–14:00 · 6 h · in 3 days"]
    assert later["span"] == "08:00–14:00 · 6 h"
    assert later["chip"] == "in 3 days"
    all_day = by_row["all day · in 4 days"]
    assert all_day["span"] == "all day"
    assert all_day["chip"] == "in 4 days"
    today = by_row["14:00–16:00 · 2 h · today"]
    assert today["chip"] == "today"
    failed = by_row["time unknown · Notice"]
    assert failed["span"] == "time unknown · Notice"
    assert failed["chip"] == ""


def test_span_and_chip_live_and_ended() -> None:
    result = _card(
        [
            _o("a", _t(11, 9, 11), _t(11, 9, 13)),
            _o("b", _t(11, 9, 8), _t(11, 9, 10)),
        ]
    )
    live, ended = result["card"]
    assert (live["span"], live["chip"]) == ("11:00–13:00", "")
    assert (ended["span"], ended["chip"]) == ("08:00–10:00", "")


def test_span_and_chip_slovenian() -> None:
    result = _card([_o("b", _t(11, 12, 8), _t(11, 12, 14))], lang="sl")
    item = result["card"][0]
    assert item["span"] == "08:00–14:00 · 6 h"
    assert item["chip"] == "čez 3 dni"


def test_live_item_has_end_and_labels_english() -> None:
    result = _card([_o("a", _t(11, 9, 11), _t(11, 9, 13))])
    item = result["card"][0]
    assert item["end"] == "2026-11-09T12:00:00+00:00"
    assert item["detail"] == "until 13:00"
    labels = result["card_labels"]
    assert labels["now"] == "Outage now"
    assert labels["ends_in"] == "ends in {d}"
    assert labels["hours_minutes"] == "{h} h {m} min"
    assert labels["hours"] == "{h} h"
    assert labels["minutes"] == "{m} min"


def test_only_live_items_have_end() -> None:
    result = _card(
        [
            _o("b", _t(11, 10, 8), _t(11, 10, 10)),
            _o("c", _t(11, 9, 8), _t(11, 9, 10)),
        ]
    )
    nxt, ended = result["card"]
    assert "end" not in nxt
    assert "end" not in ended


def test_live_labels_slovenian() -> None:
    labels = _card([], lang="sl")["card_labels"]
    assert labels["now"] == "Izklop zdaj"
    assert labels["ends_in"] == "konča se čez {d}"
    assert labels["hours_minutes"] == "{h} h {m} min"
    assert labels["hours"] == "{h} h"
    assert labels["minutes"] == "{m} min"


def test_problem_title_and_detail_english() -> None:
    result = _card(
        [], last_success=_t(11, 9, 12, 23), problem_since=NOW - timedelta(hours=2)
    )
    assert result["card_problem_title"] == "Cannot read the Elektro Celje feed"
    assert result["card_problem_detail"] == (
        "Last good check: today 12:23 · the list below may be old"
    )
    assert result["card_problem"].startswith("Cannot read the Elektro Celje feed.")


def test_problem_title_and_detail_slovenian() -> None:
    result = _card(
        [],
        lang="sl",
        last_success=_t(11, 9, 12, 23),
        problem_since=NOW - timedelta(hours=2),
    )
    assert result["card_problem_title"] == "Podatkov Elektro Celje ni mogoče prebrati"
    assert result["card_problem_detail"] == (
        "Zadnje uspešno preverjanje: danes 12:23 · spodnji seznam je morda zastarel"
    )


def test_no_problem_title_without_problem() -> None:
    result = _card([], problem_since=NOW - timedelta(minutes=30))
    assert result["card_problem_title"] is None
    assert result["card_problem_detail"] is None
