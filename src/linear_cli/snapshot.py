from __future__ import annotations


def label_snapshot_filter(label: str) -> dict[str, object]:
    return {"labels": {"name": {"eq": label}}}


def identifier_sort_key(identifier: str) -> tuple[str, int]:
    team, _, number = identifier.partition("-")
    if number.isdigit():
        return (team, int(number))
    return (identifier, 0)
