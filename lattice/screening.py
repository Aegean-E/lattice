"""PRISMA 2020 systematic review screening workflow and flow diagram generation."""

import html
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lattice.database import utc_now
from lattice.errors import fail
from lattice.repository import Repository

SCREENING_STATUSES = ("identified", "screened_in", "screened_out", "included", "excluded")
DEFAULT_EXCLUSION_REASONS = (
    "wrong_population",
    "out_of_scope_design",
    "animal_model",
    "in_vitro_only",
    "uncontrolled",
    "insufficient_data",
    "duplicate",
    "other",
)


@dataclass(frozen=True)
class ScreeningDecision:
    """An auditable screening outcome for a source paper."""

    paper_id: str
    status: str
    reason: str = ""
    notes: str = ""
    screened_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "paper_id": self.paper_id,
            "status": self.status,
            "reason": self.reason,
            "notes": self.notes,
            "screened_at": self.screened_at,
        }


@dataclass
class PrismaFlow:
    """Standardized counts and reason breakdowns across PRISMA 2020 review phases."""

    identified: int = 0
    duplicates_removed: int = 0
    screened: int = 0
    screened_out: int = 0
    screened_out_reasons: Dict[str, int] = field(default_factory=dict)
    assessed_for_eligibility: int = 0
    excluded: int = 0
    excluded_reasons: Dict[str, int] = field(default_factory=dict)
    included: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "identified": self.identified,
            "duplicates_removed": self.duplicates_removed,
            "screened": self.screened,
            "screened_out": self.screened_out,
            "screened_out_reasons": self.screened_out_reasons,
            "assessed_for_eligibility": self.assessed_for_eligibility,
            "excluded": self.excluded,
            "excluded_reasons": self.excluded_reasons,
            "included": self.included,
        }


def record_screening_decision(
    repository: Repository,
    paper_id: str,
    status: str,
    reason: str = "",
    notes: str = "",
) -> ScreeningDecision:
    """Record or update a screening decision for a paper in the knowledge graph."""
    clean_id = paper_id.strip()
    if clean_id.startswith("paper:"):
        clean_id = clean_id.split(":", 1)[1]

    # Verify paper existence
    paper = repository.get_paper(clean_id)
    if not paper:
        fail(f"paper '{paper_id}' not found", "cannot screen a nonexistent paper",
             "pass an existing paper reference or id")

    norm_status = status.strip().lower()
    if norm_status not in SCREENING_STATUSES:
        fail(f"unknown screening status '{status}'",
             f"status must be one of {', '.join(SCREENING_STATUSES)}",
             "choose a valid screening status")

    clean_reason = reason.strip()
    if norm_status in ("screened_out", "excluded") and not clean_reason:
        clean_reason = "other"

    now = utc_now()
    repository.connection.execute(
        """
        INSERT OR REPLACE INTO screening (paper_id, status, reason, notes, screened_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (clean_id, norm_status, clean_reason, notes.strip(), now),
    )
    decision = ScreeningDecision(
        paper_id=clean_id,
        status=norm_status,
        reason=clean_reason,
        notes=notes.strip(),
        screened_at=now,
    )
    import json
    repository.connection.execute(
        "INSERT INTO events(at, action, payload) VALUES(?, ?, ?)",
        (now, "screen_paper", json.dumps(decision.to_dict())),
    )
    repository.connection.commit()
    return decision


def get_screening_decision(repository: Repository, paper_id: str) -> Optional[ScreeningDecision]:
    """Retrieve the current screening decision for a paper, if recorded."""
    clean_id = paper_id.strip()
    if clean_id.startswith("paper:"):
        clean_id = clean_id.split(":", 1)[1]

    row = repository.connection.execute(
        "SELECT * FROM screening WHERE paper_id = ?", (clean_id,)
    ).fetchone()
    if not row:
        return None
    return ScreeningDecision(
        paper_id=row["paper_id"],
        status=row["status"],
        reason=row["reason"],
        notes=row["notes"],
        screened_at=row["screened_at"],
    )


def list_screening_decisions(
    repository: Repository, status: Optional[str] = None
) -> List[ScreeningDecision]:
    """List recorded screening decisions, optionally filtered by status."""
    if status:
        norm_status = status.strip().lower()
        rows = repository.connection.execute(
            "SELECT * FROM screening WHERE status = ? ORDER BY screened_at DESC", (norm_status,)
        ).fetchall()
    else:
        rows = repository.connection.execute(
            "SELECT * FROM screening ORDER BY screened_at DESC"
        ).fetchall()

    return [
        ScreeningDecision(
            paper_id=row["paper_id"],
            status=row["status"],
            reason=row["reason"],
            notes=row["notes"],
            screened_at=row["screened_at"],
        )
        for row in rows
    ]


def compute_prisma_flow(repository: Repository) -> PrismaFlow:
    """Compute aggregate counts and exclusion reasons adhering to the PRISMA 2020 statement."""
    paper_rows = repository.connection.execute("SELECT id FROM papers").fetchall()
    total_identified = len(paper_rows)

    decision_rows = repository.connection.execute(
        "SELECT paper_id, status, reason FROM screening"
    ).fetchall()
    decisions_by_id = {row["paper_id"]: row for row in decision_rows}

    # Query papers with at least one extracted claim
    claimed_rows = repository.connection.execute(
        "SELECT DISTINCT paper_id FROM claims"
    ).fetchall()
    papers_with_claims = {row["paper_id"] for row in claimed_rows}

    screened_out_reasons: Counter[str] = Counter()
    excluded_reasons: Counter[str] = Counter()
    screened_out_count = 0
    excluded_count = 0
    included_count = 0

    for row in paper_rows:
        pid = row["id"]
        dec = decisions_by_id.get(pid)
        if dec:
            st = dec["status"]
            reason = dec["reason"] or "other"
            if st == "screened_out":
                screened_out_count += 1
                screened_out_reasons[reason] += 1
            elif st == "excluded":
                excluded_count += 1
                excluded_reasons[reason] += 1
            elif st == "included":
                included_count += 1
            elif st == "screened_in":
                # Screened in and awaiting eligibility determination
                pass
        else:
            # Implicit status: if it has extracted claims, it is part of the included evidence graph
            if pid in papers_with_claims:
                included_count += 1

    screened_count = total_identified
    assessed_count = max(0, screened_count - screened_out_count)

    return PrismaFlow(
        identified=total_identified,
        duplicates_removed=0,
        screened=screened_count,
        screened_out=screened_out_count,
        screened_out_reasons=dict(screened_out_reasons),
        assessed_for_eligibility=assessed_count,
        excluded=excluded_count,
        excluded_reasons=dict(excluded_reasons),
        included=included_count,
    )


def render_prisma_markdown(flow: PrismaFlow) -> str:
    """Format PRISMA 2020 metrics as a structured Markdown flow report."""
    screened_out_str = "\n".join(
        f"    - {k}: {v}" for k, v in sorted(flow.screened_out_reasons.items())
    ) if flow.screened_out_reasons else "    *(none)*"

    excluded_str = "\n".join(
        f"    - {k}: {v}" for k, v in sorted(flow.excluded_reasons.items())
    ) if flow.excluded_reasons else "    *(none)*"

    return f"""# PRISMA 2020 Flow Diagram

## 1. Identification
- **Records identified through database search / ingestion:** {flow.identified}
- **Duplicate records removed:** {flow.duplicates_removed}

## 2. Screening
- **Records screened (title / abstract):** {flow.screened}
- **Records excluded:** {flow.screened_out}
{screened_out_str}

## 3. Eligibility
- **Reports assessed for eligibility (full-text):** {flow.assessed_for_eligibility}
- **Reports excluded:** {flow.excluded}
{excluded_str}

## 4. Included
- **New studies included in review:** {flow.included}
"""


def render_prisma_svg(flow: PrismaFlow) -> str:
    """Generate a publication-grade PRISMA 2020 vector flowchart in SVG."""
    width = 780
    height = 540

    def esc(s: object) -> str:
        return html.escape(str(s))

    def format_reasons(reasons: Dict[str, int]) -> str:
        if not reasons:
            return "No specific reasons recorded"
        items = [f"{k}: {v}" for k, v in sorted(reasons.items())]
        return ", ".join(items[:3]) + ("..." if len(items) > 3 else "")

    so_reasons = format_reasons(flow.screened_out_reasons)
    ex_reasons = format_reasons(flow.excluded_reasons)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="{height}" style="background:#090e1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#38bdf8"/>
    </marker>
    <marker id="arrow-red" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#ef4444"/>
    </marker>
    <filter id="shadow" x="-5%" y="-5%" width="110%" height="115%">
      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000" flood-opacity="0.4"/>
    </filter>
  </defs>

  <!-- Title Banner -->
  <text x="{width / 2}" y="36" fill="#f8fafc" font-size="16" font-weight="700" text-anchor="middle">PRISMA 2020 Flow Diagram</text>
  <text x="{width / 2}" y="56" fill="#94a3b8" font-size="11" text-anchor="middle">Evidence Attrition from Identification to Synthesis</text>

  <!-- PHASE 1: IDENTIFICATION -->
  <g transform="translate(60, 80)" filter="url(#shadow)">
    <rect width="280" height="74" rx="8" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
    <text x="140" y="24" fill="#38bdf8" font-size="11" font-weight="700" text-anchor="middle">1. IDENTIFICATION</text>
    <text x="140" y="46" fill="#f8fafc" font-size="13" font-weight="600" text-anchor="middle">Records Identified: {flow.identified}</text>
    <text x="140" y="62" fill="#94a3b8" font-size="10" text-anchor="middle">Duplicates Removed: {flow.duplicates_removed}</text>
  </g>

  <!-- Arrow: Identification -> Screening -->
  <line x1="200" y1="154" x2="200" y2="190" stroke="#38bdf8" stroke-width="2" marker-end="url(#arrow)"/>

  <!-- PHASE 2: SCREENING -->
  <g transform="translate(60, 190)" filter="url(#shadow)">
    <rect width="280" height="74" rx="8" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
    <text x="140" y="24" fill="#38bdf8" font-size="11" font-weight="700" text-anchor="middle">2. SCREENING</text>
    <text x="140" y="46" fill="#f8fafc" font-size="13" font-weight="600" text-anchor="middle">Records Screened: {flow.screened}</text>
    <text x="140" y="62" fill="#94a3b8" font-size="10" text-anchor="middle">Title and abstract evaluation</text>
  </g>

  <!-- Side Arrow: Screening -> Screened Out -->
  <line x1="340" y1="227" x2="430" y2="227" stroke="#ef4444" stroke-width="2" marker-end="url(#arrow-red)"/>

  <!-- Box: Screened Out -->
  <g transform="translate(435, 190)" filter="url(#shadow)">
    <rect width="280" height="74" rx="8" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
    <text x="140" y="24" fill="#ef4444" font-size="11" font-weight="700" text-anchor="middle">RECORDS EXCLUDED: {flow.screened_out}</text>
    <text x="140" y="46" fill="#fca5a5" font-size="11" text-anchor="middle">{esc(so_reasons)}</text>
  </g>

  <!-- Arrow: Screening -> Eligibility -->
  <line x1="200" y1="264" x2="200" y2="300" stroke="#38bdf8" stroke-width="2" marker-end="url(#arrow)"/>

  <!-- PHASE 3: ELIGIBILITY -->
  <g transform="translate(60, 300)" filter="url(#shadow)">
    <rect width="280" height="74" rx="8" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
    <text x="140" y="24" fill="#38bdf8" font-size="11" font-weight="700" text-anchor="middle">3. ELIGIBILITY</text>
    <text x="140" y="46" fill="#f8fafc" font-size="13" font-weight="600" text-anchor="middle">Full-Text Assessed: {flow.assessed_for_eligibility}</text>
    <text x="140" y="62" fill="#94a3b8" font-size="10" text-anchor="middle">Detailed study criteria appraisal</text>
  </g>

  <!-- Side Arrow: Eligibility -> Excluded -->
  <line x1="340" y1="337" x2="430" y2="337" stroke="#ef4444" stroke-width="2" marker-end="url(#arrow-red)"/>

  <!-- Box: Full-Text Excluded -->
  <g transform="translate(435, 300)" filter="url(#shadow)">
    <rect width="280" height="74" rx="8" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
    <text x="140" y="24" fill="#ef4444" font-size="11" font-weight="700" text-anchor="middle">REPORTS EXCLUDED: {flow.excluded}</text>
    <text x="140" y="46" fill="#fca5a5" font-size="11" text-anchor="middle">{esc(ex_reasons)}</text>
  </g>

  <!-- Arrow: Eligibility -> Included -->
  <line x1="200" y1="374" x2="200" y2="410" stroke="#22c55e" stroke-width="2" marker-end="url(#arrow)"/>

  <!-- PHASE 4: INCLUDED -->
  <g transform="translate(60, 410)" filter="url(#shadow)">
    <rect width="280" height="84" rx="8" fill="#1e293b" stroke="#22c55e" stroke-width="2"/>
    <text x="140" y="26" fill="#22c55e" font-size="11" font-weight="700" text-anchor="middle">4. INCLUDED</text>
    <text x="140" y="50" fill="#f8fafc" font-size="14" font-weight="700" text-anchor="middle">Studies Included: {flow.included}</text>
    <text x="140" y="68" fill="#86efac" font-size="10" text-anchor="middle">Synthesized in Evidence Graph</text>
  </g>
</svg>"""
    return svg
