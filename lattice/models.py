"""Value objects and the validation rules shared by storage, ingestion and queries."""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lattice.errors import fail

STANCES = ("supports", "contradicts", "mentions")
EDGE_KINDS = (
    "cites",
    "supports",
    "contradicts",
    "replicates",
    "extends",
    "uses_method",
    "measures",
    "answers",
    "mentions",
    "related",
)
ENTITY_PREFIXES = {"p": "paper", "c": "claim", "q": "question"}
REF_PREFIX = {"paper": "p", "claim": "c", "question": "q"}
_NORMALIZE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Paper:
    """A source record: bibliographic metadata plus its stable identifier."""

    id: str
    title: str
    authors: str = ""
    year: str = ""
    venue: str = ""
    doi: str = ""
    arxiv: str = ""
    url: str = ""
    abstract: str = ""
    kind: str = "paper"
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "id": self.id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "arxiv": self.arxiv,
            "url": self.url,
            "abstract": self.abstract,
            "kind": self.kind,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Claim:
    """One asserted statement tied to an exact source quote and locator."""

    id: str
    paper_id: str
    text: str
    quote: str
    locator: str = ""
    stance: str = "mentions"
    confidence: float = 0.5
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "id": self.id,
            "paper_id": self.paper_id,
            "text": self.text,
            "quote": self.quote,
            "locator": self.locator,
            "stance": self.stance,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Question:
    """A research question whose evidence is assembled from linked claims."""

    id: str
    text: str
    status: str = "open"
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Edge:
    """A typed, directed relation between two entity references."""

    id: int
    src: str
    dst: str
    kind: str
    note: str = ""
    created_at: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation, including resolved endpoint details when present."""
        return {
            "id": self.id,
            "src": self.src,
            "dst": self.dst,
            "kind": self.kind,
            "note": self.note,
            "created_at": self.created_at,
            "details": self.details,
        }


def normalize_text(value: str) -> str:
    """Lowercase and collapse punctuation for identity comparisons."""
    return _NORMALIZE.sub(" ", value.lower()).strip()


def paper_id(title: str, doi: str = "", arxiv: str = "") -> str:
    """A stable identifier derived from DOI, then arXiv ID, then normalized title."""
    identity = (doi or "").strip().lower() or (arxiv or "").strip().lower() or normalize_text(title)
    if not identity:
        fail("a paper needs a title, DOI or arXiv ID", "the identity would be empty",
             "pass a non-empty title or identifier")
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"p_{digest}"


def next_id(prefix: str, rows: List[Any]) -> str:
    """The next sequential identifier for a table whose ids share a prefix."""
    highest = 0
    for row in rows:
        value = str(row[0] if not isinstance(row, str) else row)
        suffix = value[len(prefix) + 1:] if value.startswith(prefix + "_") else ""
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}_{highest + 1:06d}"


def validate_stance(stance: Optional[str]) -> str:
    """A claim stance must be one of `STANCES`."""
    value = (stance or "mentions").strip().lower()
    if value not in STANCES:
        fail(f"unknown stance '{stance}'", f"stance must be one of {', '.join(STANCES)}",
             "use --stance supports, --stance contradicts or --stance mentions")
    return value


def parse_confidence(value: Optional[float]) -> float:
    """Confidence is a number in [0, 1]; the default is 0.5."""
    if value is None:
        return 0.5
    number = float(value)
    if not 0.0 <= number <= 1.0:
        fail(f"confidence {number} is outside [0, 1]", "confidence is a probability-like weight",
             "pass a value between 0 and 1")
    return number


def validate_edge_kind(kind: str) -> str:
    """An edge kind must be one of `EDGE_KINDS`."""
    value = (kind or "").strip().lower()
    if value not in EDGE_KINDS:
        fail(f"unknown edge kind '{kind}'", f"kind must be one of {', '.join(EDGE_KINDS)}",
             "use one of the listed --type values")
    return value


def entity_type(ref: str) -> str:
    """The entity type named by a reference such as `claim:c_000001`."""
    if ":" not in ref:
        fail(f"'{ref}' is not a reference", "references look like paper:p_xxx or claim:c_xxx",
             "pass a reference including its prefix")
    prefix = ref.split(":", 1)[0].strip().lower()
    if prefix not in REF_PREFIX:
        fail(f"unknown reference prefix '{prefix}'", "only paper, claim and question are entities",
             "use paper:, claim: or question:")
    return prefix


def validate_ref(ref: str) -> str:
    """Normalize `claim:c_000001` and reject malformed references."""
    kind = entity_type(ref)
    value = ref.split(":", 1)[1].strip()
    if not value.startswith(REF_PREFIX[kind] + "_"):
        fail(f"'{ref}' does not match its prefix", f"a {kind} id starts with '{REF_PREFIX[kind]}_'",
             f"pass a reference such as {kind}:{REF_PREFIX[kind]}_000001")
    return f"{kind}:{value}"


def bare_id(ref: str) -> str:
    """The identifier part of a reference."""
    return validate_ref(ref).split(":", 1)[1]


def estimate_tokens(text: str) -> int:
    """A deterministic, conservative token estimate used by `brief`."""
    return max(1, (len(text) + 3) // 4)
