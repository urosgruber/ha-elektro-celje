"""Tests for the feed parser."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.elektro_celje.const import TZ
from custom_components.elektro_celje.models import ParseStatus
from custom_components.elektro_celje.parser import (
    FeedFormatError,
    normalize,
    notice_id_from,
    parse_feed,
    parse_schedule,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "expected_2026-11-09.json").read_text("utf-8"))
FILES = sorted({row["file"] for row in EXPECTED})


def read(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


def region_of(name: str) -> str:
    return name.removeprefix("rss_").removesuffix("_2026-11-09.xml")


def feed(*items: str) -> str:
    return (
        "<rss version='2.0'><channel><title>t</title>"
        + "".join(items)
        + "</channel></rss>"
    )


def item(lis: list[str], link: str = "https://x/si/a/1/43999-a-b") -> str:
    ul = "".join(f"<li><strong>{li}</strong></li>" for li in lis)
    desc = (
        "<p>Elektro Celje obvešča, da bo <strong>TP Test</strong>&nbsp;</p>"
        f"<ul class='dates-list'>{ul}</ul><p>zaradi del</p>"
    )
    escaped = desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<item><title>Naslov</title><link>{link}</link>"
        f"<description>{escaped}</description></item>"
    )


@pytest.mark.parametrize("row", EXPECTED, ids=lambda r: f"{r['file']}:{r['notice_id']}")
def test_fixture_items_parse_exactly(row):
    notices = {
        n.notice_id: n for n in parse_feed(read(row["file"]), region_of(row["file"]))
    }
    n = notices[row["notice_id"]]
    assert n.status == row["status"]
    assert n.intervals[0].start.isoformat() == row["start"]
    assert n.intervals[0].end.isoformat() == row["end"]


def test_fixture_item_count():
    assert sum(len(parse_feed(read(f), region_of(f))) for f in FILES) == 51


def test_fixture_notice_fields():
    notice = {
        n.notice_id: n
        for n in parse_feed(read("rss_velenje_2026-11-09.xml"), "velenje")
    }["43322"]
    assert notice.region == "velenje"
    assert notice.station_text == "Zabukovica Papež - nizkonapetostni izvod Kozovinc"
    assert notice.station_names == (notice.station_text,)
    assert notice.date_texts == (
        "v ponedeljek, 09. novembra 2026, predvidoma med 08.30 in 11.00 uro",
    )
    assert "zaradi del na distribucijskem omrežju" in notice.text
    assert "  " not in notice.text
    assert notice.link.endswith("43322-784-Nadzornistvo-Zalec-Obmocje-Zabukovice")
    assert notice.reason is None


@pytest.mark.parametrize(
    ("line", "start", "end"),
    [
        (
            "v ponedeljek, 09. novembra 2026, predvidoma med 08:30 in 11:30 uro",
            "08:30",
            "11:30",
        ),
        (
            "v torek, 10. novembra 2026, predvidoma med 8:00 in 13:00 uro",
            "08:00",
            "13:00",
        ),
        (
            "v ponedeljek, 9. novembra 2026, predvidoma med 8:00 in 14:00 uro",
            "08:00",
            "14:00",
        ),
        (
            "v ponedeljek, 09. novembra 2026, predvidoma med 08.30 in 11.00 uro",
            "08:30",
            "11:00",
        ),
        (
            "v ponedeljek, 09.november 2026, predvidoma med 08:00 in 11:00 uro",
            "08:00",
            "11:00",
        ),
        (
            "v ponedeljek, 9. november 2026, predvidoma med 9:00 in 13:30 uro",
            "09:00",
            "13:30",
        ),
        (
            "v sredo, 11. november 2026, predvidoma med 8:00 in 8:30 uro",
            "08:00",
            "08:30",
        ),
    ],
)
def test_time_formats(line, start, end):
    status, interval, reason = parse_schedule(line)
    assert status is ParseStatus.OK
    assert reason is None
    assert interval.start.strftime("%H:%M") == start
    assert interval.end.strftime("%H:%M") == end
    assert not interval.all_day


def test_time_without_med_uses_first_two_times():
    status, interval, _ = parse_schedule("v torek, 10. novembra 2026, od 8:00 do 13:00")
    assert status is ParseStatus.OK
    assert interval.start == datetime(2026, 11, 10, 8, 0, tzinfo=TZ)
    assert interval.end == datetime(2026, 11, 10, 13, 0, tzinfo=TZ)


def test_all_month_forms():
    forms = [
        ("januar", "januarja"), ("februar", "februarja"), ("marec", "marca"),
        ("april", "aprila"), ("maj", "maja"), ("junij", "junija"),
        ("julij", "julija"), ("avgust", "avgusta"), ("september", "septembra"),
        ("oktober", "oktobra"), ("november", "novembra"), ("december", "decembra"),
    ]  # fmt: skip
    for number, names in enumerate(forms, start=1):
        for name in names:
            status, interval, _ = parse_schedule(
                f"v petek, 5. {name} 2027, predvidoma med 8:00 in 9:00 uro"
            )
            assert status is ParseStatus.OK, name
            assert interval.start.month == number, name


def test_end_before_start_moves_to_next_day():
    status, interval, _ = parse_schedule(
        "v petek, 13. novembra 2026, predvidoma med 22:00 in 02:00 uro"
    )
    assert status is ParseStatus.OK
    assert interval.end == datetime(2026, 11, 14, 2, 0, tzinfo=TZ)


def test_two_dates_in_one_line_fail():
    status, interval, reason = parse_schedule(
        "od 9. do 11. novembra 2026, med 8:00 in 14:00 uro"
    )
    assert status is ParseStatus.FAILED
    assert interval is None
    assert reason


def test_date_without_times_is_date_only():
    status, interval, _ = parse_schedule("v torek, 10. novembra 2026, ves dan")
    assert status is ParseStatus.DATE_ONLY
    assert interval.all_day
    assert interval.start == datetime(2026, 11, 10, tzinfo=TZ)
    assert interval.end == datetime(2026, 11, 11, tzinfo=TZ)


@pytest.mark.parametrize(
    "line", ["po dogovoru", "", "v torek, 10. foo 2026, med 8:00 in 9:00 uro"]
)
def test_unreadable_line_fails(line):
    status, interval, reason = parse_schedule(line)
    assert status is ParseStatus.FAILED
    assert interval is None
    assert reason


def test_impossible_date_fails():
    status, interval, reason = parse_schedule(
        "v torek, 31. novembra 2026, predvidoma med 8:00 in 9:00 uro"
    )
    assert status is ParseStatus.FAILED
    assert interval is None
    assert reason


def test_multiple_li_give_multiple_intervals():
    xml = feed(
        item(
            [
                "v torek, 10. novembra 2026, predvidoma med 8:00 in 9:00 uro",
                "v sredo, 11. novembra 2026, predvidoma med 10:00 in 11:00 uro",
            ]
        )
    )
    (notice,) = parse_feed(xml, "celje")
    assert len(notice.intervals) == 2
    assert len(notice.date_texts) == 2
    assert notice.intervals[1].start == datetime(2026, 11, 11, 10, 0, tzinfo=TZ)
    assert notice.status is ParseStatus.OK


def test_notice_status_is_worst_of_its_lines():
    xml = feed(
        item(
            [
                "v torek, 10. novembra 2026, predvidoma med 8:00 in 9:00 uro",
                "po dogovoru",
            ]
        )
    )
    (notice,) = parse_feed(xml, "celje")
    assert notice.status is ParseStatus.FAILED
    assert notice.reason
    assert len(notice.intervals) == 1


def test_notice_with_date_only_line_is_date_only():
    xml = feed(item(["v torek, 10. novembra 2026, ves dan"]))
    (notice,) = parse_feed(xml, "celje")
    assert notice.status is ParseStatus.DATE_ONLY
    assert notice.intervals[0].all_day


def test_notice_without_dates_list_fails():
    xml = (
        "<rss><channel><item><title>t</title><link>https://x/5-a</link>"
        "<description>&lt;p&gt;Brez datuma&lt;/p&gt;</description>"
        "</item></channel></rss>"
    )
    (notice,) = parse_feed(xml, "celje")
    assert notice.status is ParseStatus.FAILED
    assert notice.intervals == ()
    assert notice.reason
    assert notice.station_text is None


def test_dst_dates_are_aware():
    status, interval, _ = parse_schedule(
        "v nedeljo, 29. marca 2026, predvidoma med 02:30 in 04:00 uro"
    )
    assert status is ParseStatus.OK
    assert interval.start.tzinfo is not None
    assert interval.end.tzinfo is not None
    assert interval.end > interval.start
    assert interval.end.utcoffset().total_seconds() == 2 * 3600


def test_not_rss_raises():
    with pytest.raises(FeedFormatError):
        parse_feed("<html><body>Error</body></html>", "celje")


@pytest.mark.parametrize("text", ["", "not xml <", "<rss version='2.0'></rss>"])
def test_broken_input_raises(text):
    with pytest.raises(FeedFormatError):
        parse_feed(text, "celje")


def test_input_over_one_megabyte_raises():
    with pytest.raises(FeedFormatError):
        parse_feed("<rss><channel>" + "x" * 1_000_001 + "</channel></rss>", "celje")


def test_empty_channel_returns_empty_list():
    assert parse_feed("<rss><channel><title>t</title></channel></rss>", "celje") == []


def test_notice_id_uses_numeric_link_id():
    link = (
        "https://www.elektro-celje.si:443/si/aktualno/obvestila-o-izklopih/"
        "celje/2026/11/43309-993-Nadzornistvo"
    )
    assert notice_id_from(link, "celje", "Repno", "x") == "43309"


def test_notice_id_without_number_is_stable_hash():
    a = notice_id_from("https://x/si/abc", "celje", "Repno", "x")
    assert a == notice_id_from("https://x/si/abc", "celje", "Repno", "x")
    assert a != notice_id_from("https://x/si/abc", "velenje", "Repno", "x")
    assert len(a) == 12


def test_normalize():
    assert normalize("  Zabukovica   PAPEŽ ") == "zabukovica papez"
