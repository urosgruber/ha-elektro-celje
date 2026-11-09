"""Tests for station names and matching."""

from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.elektro_celje.matching import matches
from custom_components.elektro_celje.parser import parse_feed, split_station_names

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("text", "names"),
    [
        (
            "Zabukovica Papež - nizkonapetostni izvod Kozovinc",
            ("Zabukovica Papež",),
        ),
        ("Babna Reka in Baberšica", ("Babna Reka", "Baberšica")),
        ("Žegar, nizkonapetostno omrežje - Vodovod", ("Žegar",)),
        (
            "Mokronog nadzorništvo, nizkonapetostno omrežje – Puščava vas",
            ("Mokronog nadzorništvo",),
        ),
        ("Podgorje Vravar - izvod Podgorje 103, 104 in 104a", ("Podgorje Vravar",)),
        (
            "Impolje, Orle, Prlska gora, Zavratec ribnik, Dedna gora in Studenec Matko",
            (
                "Impolje",
                "Orle",
                "Prlska gora",
                "Zavratec ribnik",
                "Dedna gora",
                "Studenec Matko",
            ),
        ),
        (
            "Stanovanjske hiše Kotlje od št.88 do št.97",
            ("Stanovanjske hiše Kotlje od št.88 do št.97",),
        ),
    ],
)
def test_split_station_names(text, names):
    assert split_station_names(text) == names


def _notice(station_text):
    notice = parse_feed(
        "<rss version='2.0'><channel><item><title>t</title>"
        "<link>https://x/1-a</link><description>"
        "&lt;ul class=&quot;dates-list&quot;&gt;&lt;li&gt;1. nov 2026 "
        "od 8:00 do 9:00&lt;/li&gt;&lt;/ul&gt;</description></item>"
        "</channel></rss>",
        "celje",
    )[0]
    return replace(
        notice,
        station_text=station_text,
        station_names=split_station_names(station_text) if station_text else (),
    )


@pytest.mark.parametrize(
    ("query", "station_text", "expected"),
    [
        ("zabukovica papež", "Zabukovica Papež - nizkonapetostni izvod Kozovinc", True),
        ("zabukovica", "Zabukovica Papež - nizkonapetostni izvod Kozovinc", False),
        ("žusem", "Spodnji Žusem", False),
        ("žusem", "Glažuta, Aero Loka, Loka pri Žusmu, Žusem, Dobrina", True),
        ("studenec", "Studenec", True),
        ("studenec", "Impolje, Orle, Dedna gora in Studenec Matko", False),
        ("Zabukovica Papez", "Zabukovica Papež - nizkonapetostni izvod Kozovinc", True),
    ],
)
def test_matches(query, station_text, expected):
    assert matches(query, _notice(station_text)) is expected


def test_no_station_text_never_matches():
    assert matches("studenec", _notice(None)) is False


def test_every_fixture_notice_has_names():
    notices = []
    for path in sorted(FIXTURES.glob("rss_*.xml")):
        region = path.name.removeprefix("rss_").removesuffix("_2026-11-09.xml")
        notices += parse_feed(path.read_text("utf-8"), region)
    assert len(notices) == 51
    for notice in notices:
        assert notice.station_names, notice.station_text
        for name in notice.station_names:
            assert not name.casefold().startswith("nizkonapetostn"), name
