"""Value objects and the validation rules shared by storage, ingestion and queries."""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lattice.errors import fail

STANCES = ("supports", "contradicts", "mentions")
STUDY_TYPES = (
    "Meta-Analysis",
    "Systematic Review",
    "Literature Review",
    "Review",
    "Randomized Controlled Trial",
    "Cohort Study",
    "Case-Control Study",
    "Cross-Sectional Study",
    "Observational Study",
    "Qualitative Study",
    "Case Study",
    "Experimental Study",
    "In Vitro Study",
    "Animal Study",
    "Computational Study",
    "General Study",
)
_STUDY_TYPE_RULES = (
    ("Meta-Analysis", re.compile(r"\bmeta[- ]?analy(?:sis|ses|tic)\b")),
    ("Systematic Review", re.compile(r"\bsystematic review\b")),
    ("Literature Review", re.compile(r"\bliterature review\b|\breview of (?:the )?literature\b")),
    ("Review", re.compile(r"\breview\b")),
    ("Randomized Controlled Trial",
     re.compile(r"\brandomi[sz]ed (?:controlled )?(?:trial|study)\b|\brct\b")),
    ("Cohort Study", re.compile(r"\bcohort\b")),
    ("Case-Control Study", re.compile(r"\bcase[- ]control\b")),
    ("Cross-Sectional Study", re.compile(r"\bcross[- ]sectional\b")),
    ("Observational Study", re.compile(r"\bobservational\b|\bsurvey\b|\bregistry\b")),
    ("Qualitative Study",
     re.compile(r"\bqualitative\b|\bfocus group(?:s)?\b|\binterview(?:s)?\b")),
    ("Case Study", re.compile(r"\bcase (?:study|report|series)\b")),
    ("In Vitro Study", re.compile(r"\bin vitro\b|\bcell cultur|\bassay\b|\bcultures?\b")),
    ("Animal Study",
     re.compile(r"\b(?:mice|mouse|rats?|rodents?|zebrafish|primates?|in vivo)\b")),
    ("Computational Study",
     re.compile(r"\bcomputational\b|\bsimulation\b|\bmachine learning\b|\bdeep learning\b"
                r"|\btransformer\b|\bneural network\b")),
    ("Experimental Study",
     re.compile(r"\bexperiment(?:al|s)?\b|\btrial\b|\bintervention\b|\bstimulat(?:ed|ion)\b"
                r"|\bparticipants?\b")),
)
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
    tags: str = ""
    study_type: str = ""
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
            "tags": self.tags,
            "study_type": self.study_type,
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


_TAG_SPLIT = re.compile(r"[,;]+")
_TAG_WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
_TAG_STOPWORDS = frozenset("""
a an and are as at be been being by can could did do does for from had has have how in into is
it its may might more most of on or our over such than that the their them these they this those
to under using was we were what when where which who why with within without study studies paper
papers result results method methods approach approaches based new novel
""".split())


def normalize_tags(value: str) -> str:
    """Normalize comma- or semicolon-separated tags into one lowercase, deduplicated string."""
    tags: List[str] = []
    for part in _TAG_SPLIT.split(str(value or "")):
        tag = normalize_text(part)
        if tag and tag not in tags:
            tags.append(tag)
    return ", ".join(tags)


def derive_tags(title: str, abstract: str = "", limit: int = 6) -> str:
    """Derive deterministic keyword tags, weighting title words over abstract words."""
    counts: Counter[str] = Counter()
    order: Dict[str, int] = {}
    for source, weight in ((title, 3), (abstract, 1)):
        for match in _TAG_WORD.finditer(source or ""):
            word = match.group(0).lower()
            if word in _TAG_STOPWORDS:
                continue
            counts[word] += weight
            order.setdefault(word, len(order))
    ranked = sorted(counts, key=lambda word: (-counts[word], order[word], word))
    return ", ".join(ranked[:max(0, int(limit))])


def normalize_study_type(value: str) -> str:
    """Trim a study type and map common abbreviations to a canonical label."""
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        return ""
    aliases = {normalize_text(name): name for name in STUDY_TYPES}
    aliases.update({
        "meta analysis": "Meta-Analysis",
        "systematic literature review": "Systematic Review",
        "randomised controlled trial": "Randomized Controlled Trial",
        "randomized trial": "Randomized Controlled Trial",
        "rct": "Randomized Controlled Trial",
        "cohort": "Cohort Study",
        "case control": "Case-Control Study",
        "cross sectional": "Cross-Sectional Study",
        "qualitative": "Qualitative Study",
        "case report": "Case Study",
        "in vitro": "In Vitro Study",
        "animal": "Animal Study",
        "computational": "Computational Study",
    })
    return aliases.get(normalize_text(cleaned), cleaned)


def infer_study_type(title: str, abstract: str = "") -> str:
    """Classify a paper by design markers in its title and abstract."""
    text = normalize_text(f"{title or ''} {abstract or ''}")
    for label, pattern in _STUDY_TYPE_RULES:
        if pattern.search(text):
            return label
    return "General Study"


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
