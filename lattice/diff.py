"""Deterministic diffing between JSONL graph snapshots and the live repository."""

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from lattice.repository import Repository
from lattice.snapshots import collect_repository_records, read_snapshot_records

_PLURAL = {"paper": "papers", "question": "questions", "claim": "claims", "edge": "edges"}
_IGNORED_FIELDS = frozenset({"created_at"})


def _index_records(records: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Key snapshot records by `(record_type, id)`; unknown record types are skipped."""
    indexed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for record in records:
        record_type = str(record.get("record_type") or "")
        if record_type in _PLURAL:
            indexed[(record_type, str(record.get("id")))] = dict(record)
    return indexed


def _counts(records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Per-type record counts keyed by plural table names."""
    counts = {plural: 0 for plural in _PLURAL.values()}
    for record in records:
        record_type = str(record.get("record_type") or "")
        if record_type in _PLURAL:
            counts[_PLURAL[record_type]] += 1
    return counts


def _database_label(repository: Repository) -> str:
    """The repository's database file path, or `:memory:` for an in-memory graph."""
    row = repository.connection.execute("PRAGMA database_list").fetchone()
    file = str(row["file"]) if row is not None and row["file"] else ""
    return file or ":memory:"


def diff_records(old_records: Sequence[Dict[str, Any]],
                 new_records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare two snapshot record sets and report added, removed and changed entities.

    Records are matched by `(record_type, id)`. The volatile `created_at` field never
    counts as a change, so a re-imported graph with regenerated timestamps still diffs
    as unchanged. Every reported list is sorted, making the output deterministic.
    """
    old_index = _index_records(old_records)
    new_index = _index_records(new_records)
    added = {plural: [] for plural in _PLURAL.values()}
    removed = {plural: [] for plural in _PLURAL.values()}
    changed = {plural: [] for plural in _PLURAL.values()}
    for key in sorted(set(old_index) - set(new_index)):
        removed[_PLURAL[key[0]]].append(key[1])
    for key in sorted(set(new_index) - set(old_index)):
        added[_PLURAL[key[0]]].append(key[1])
    unchanged = 0
    for key in sorted(set(old_index) & set(new_index)):
        old_record, new_record = old_index[key], new_index[key]
        fields = sorted(
            name for name in set(old_record) | set(new_record)
            if name not in _IGNORED_FIELDS and name != "record_type"
            and old_record.get(name) != new_record.get(name)
        )
        if fields:
            changed[_PLURAL[key[0]]].append({"id": key[1], "fields": fields})
        else:
            unchanged += 1
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary": {
            "added": sum(len(ids) for ids in added.values()),
            "removed": sum(len(ids) for ids in removed.values()),
            "changed": sum(len(items) for items in changed.values()),
            "unchanged": unchanged,
        },
    }


def diff_snapshots(old_path: Path, new_path: Path) -> Dict[str, Any]:
    """Diff two JSONL snapshot files: the baseline `old_path` against the newer `new_path`."""
    old_records = read_snapshot_records(old_path)
    new_records = read_snapshot_records(new_path)
    return {
        "old": {"label": str(old_path), **_counts(old_records)},
        "new": {"label": str(new_path), **_counts(new_records)},
        **diff_records(old_records, new_records),
    }


def diff_snapshot(repository: Repository, path: Path) -> Dict[str, Any]:
    """Diff a JSONL snapshot (baseline) against the live repository (current)."""
    old_records = read_snapshot_records(path)
    new_records = collect_repository_records(repository)
    return {
        "old": {"label": str(path), **_counts(old_records)},
        "new": {"label": _database_label(repository), **_counts(new_records)},
        **diff_records(old_records, new_records),
    }
