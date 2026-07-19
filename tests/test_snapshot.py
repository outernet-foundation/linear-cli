from __future__ import annotations

from linear_cli.snapshot import identifier_sort_key, label_snapshot_filter


def test_label_snapshot_filter_uses_label_name_eq() -> None:
    assert label_snapshot_filter("packet/2026-07-omnibus") == {"labels": {"name": {"eq": "packet/2026-07-omnibus"}}}


def test_identifier_sort_key_numeric_within_team() -> None:
    assert identifier_sort_key("PLE-9") < identifier_sort_key("PLE-10")
    assert identifier_sort_key("PLE-99") < identifier_sort_key("PLE-358")


def test_identifier_sort_key_teams_sorted_alphabetically() -> None:
    assert identifier_sort_key("ABC-1") < identifier_sort_key("PLE-1")


def test_identifier_sort_key_unparseable_falls_back_to_string_with_zero_number() -> None:
    assert identifier_sort_key("weird") == ("weird", 0)
