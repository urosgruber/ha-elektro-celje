"""Tests of user-facing texts: README and the config flow strings."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
BASE = ROOT / "custom_components" / "elektro_celje"


def _strings(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def test_readme_states_exact_match_rule() -> None:
    """I1: the README says that a part of the name does not match."""
    assert "Enter the exact station name as the notices write it" in README
    assert "A part of the name does not\nmatch." in README
    assert "`Zabukovica Papež`" in README
    assert "Enter a part of the name" not in README
    assert "`TP Zabukovica`" not in README


def test_config_flow_texts_state_exact_match_rule() -> None:
    """I1: the station help text says that a part of the name does not match."""
    for name in ("strings.json", "translations/en.json"):
        steps = _strings(name)["config"]["step"]
        for step in ("user", "reconfigure"):
            text = steps[step]["data_description"]["station"]
            assert "exact station name" in text, (name, step)
            assert "A part of the name does not match." in text, (name, step)
    sl = _strings("translations/sl.json")["config"]["step"]
    for step in ("user", "reconfigure"):
        assert "Del imena se ne ujema." in sl[step]["data_description"]["station"]


def test_reconfigure_text_says_when_history_is_cleared() -> None:
    """M2: the history is cleared only when the region or the station changes."""
    en = _strings("strings.json")["config"]["step"]["reconfigure"]["description"]
    assert (
        "If you change the region or the station, the stored alert history is "
        "cleared." in en
    )
    sl = _strings("translations/sl.json")["config"]["step"]["reconfigure"]
    assert "Če spremenite regijo ali postajo" in sl["description"]


def test_readme_documents_payload_key_and_diagnostics() -> None:
    """I2, I3: the payload table has `key`; the diagnostics text is accurate."""
    assert "| `key` |" in README
    assert "It is safe to attach" not in README
    assert "shows the public region feeds and only the status of\nyour outages" in (
        README
    )
    assert "Do not paste raw entity states or the `outages` attribute" in README


def test_readme_documents_last_checked_and_card_locale() -> None:
    """R23: README notes last_checked in a long failure and the card texts."""
    assert "last state change of the location" in README
    assert "The integration builds all texts of the card" in README


def test_brand_icons_have_the_right_size() -> None:
    """The integration ships a 256 px icon and a 512 px icon@2x with alpha."""
    from PIL import Image

    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        image = Image.open(BASE / "brand" / name)
        assert image.size == (size, size), name
        assert image.mode == "RGBA", name
        assert image.getpixel((0, 0))[3] == 0, name


def test_readme_mentions_icon_and_no_old_version() -> None:
    """The README names the brand icon and has no 2.0.1 text."""
    assert "brand/icon.png" in README
    assert "2.0.1" not in README
