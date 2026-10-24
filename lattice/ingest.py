"""Parsers for the text bibliography formats lattice accepts, with no third-party dependencies."""

import csv
import io
from pathlib import Path
from typing import Any, Dict, Iterable, List

from lattice.errors import LatticeError, fail
from lattice.models import infer_study_type, normalize_study_type

Record = Dict[str, str]
_FIELDS = ("title", "authors", "year", "venue", "doi", "arxiv", "url", "abstract",
           "tags", "study_type", "kind")
_CSV_ALIASES = {
    "tag": "tags",
    "keyword": "tags",
    "keywords": "tags",
    "subject": "tags",
    "study": "study_type",
    "study type": "study_type",
    "type": "study_type",
}


def empty_record() -> Record:
    """A record with every supported metadata field present."""
    return {name: "" for name in _FIELDS}


def _clean(value: str) -> str:
    """Collapse whitespace and strip one layer of surrounding delimiters."""
    text = " ".join(value.replace("\n", " ").split())
    if len(text) >= 2 and text[0] == "{" and text[-1] == "}":
        text = text[1:-1].strip()
    elif len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text


def _braced_span(text: str, start: int) -> int:
    """Index of the brace closing the one at `start`, or -1 when it is unbalanced."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_top_level(text: str) -> List[str]:
    """Split a BibTeX field list on commas that are not inside braces or quotes."""
    parts: List[str] = []
    depth = 0
    quoted = False
    start = 0
    for index, char in enumerate(text):
        if char == '"' and depth == 0:
            quoted = not quoted
        elif not quoted and char == "{":
            depth += 1
        elif not quoted and char == "}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0 and not quoted:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part for part in parts if part.strip()]


def parse_bibtex(text: str) -> List[Record]:
    """Parse one or more BibTeX entries into metadata records."""
    records: List[Record] = []
    position = 0
    while True:
        at = text.find("@", position)
        if at < 0:
            break
        open_brace = text.find("{", at)
        if open_brace < 0:
            break
        close_brace = _braced_span(text, open_brace)
        if close_brace < 0:
            fail("unbalanced braces in BibTeX input", "an entry never closes",
                 "check the braces around the entry and its fields")
        body = text[open_brace + 1:close_brace]
        position = close_brace + 1
        comma = body.find(",")
        if comma < 0:
            continue
        record = empty_record()
        for field in _split_top_level(body[comma + 1:]):
            if "=" not in field:
                continue
            name, value = field.split("=", 1)
            key = name.strip().lower()
            if key == "author":
                record["authors"] = _clean(value).replace(" and ", "; ")
            elif key in ("journal", "booktitle", "publisher"):
                record["venue"] = _clean(value)
            elif key in ("year", "date"):
                record["year"] = _clean(value)[:4]
            elif key in ("doi", "url", "abstract"):
                record[key] = _clean(value)
            elif key in ("keywords", "keyword"):
                record["tags"] = _clean(value).replace(" and ", ", ")
            elif key in ("studytype", "study_type", "study-type"):
                record["study_type"] = _clean(value)
            elif key == "eprint":
                record["arxiv"] = _clean(value)
            elif key == "title":
                record["title"] = _clean(value)
        if record["title"]:
            records.append(record)
    return records


def parse_ris(text: str) -> List[Record]:
    """Parse RIS records into metadata records."""
    records: List[Record] = []
    current = empty_record()
    authors: List[str] = []
    for line in text.splitlines():
        if len(line) < 6 or line[2:4] != "  ":
            continue
        tag = line[:2].strip().upper()
        value = line[5:].strip()
        if tag == "TY":
            current = empty_record()
            authors = []
        elif tag == "TI":
            current["title"] = value
        elif tag == "AU":
            authors.append(value)
        elif tag in ("JO", "T2", "JF", "JA"):
            current["venue"] = value
        elif tag == "PY":
            current["year"] = value[:4]
        elif tag == "DO":
            current["doi"] = value
        elif tag == "UR":
            current["url"] = value
        elif tag == "AB":
            current["abstract"] = value
        elif tag == "KW":
            current["tags"] = f"{current['tags']}, {value}".strip(", ")
        elif tag == "M3":
            current["study_type"] = value
        elif tag == "AN" and "arxiv" in value.lower():
            current["arxiv"] = value.split(":")[-1].strip()
        elif tag == "ER":
            if current["title"]:
                current["authors"] = "; ".join(authors)
                records.append(current)
            current = empty_record()
            authors = []
    if current["title"]:
        current["authors"] = "; ".join(authors)
        records.append(current)
    return records


def parse_csv(text: str) -> List[Record]:
    """Parse a CSV with a header row naming any of the supported metadata fields."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        fail("the CSV has no header row", "column names map the data to metadata fields",
             "add a header such as title,authors,year,doi,venue,url,abstract")
    records: List[Record] = []
    for row in reader:
        normalized = {str(key).strip().lower(): (value or "").strip()
                      for key, value in row.items() if key is not None}
        record = empty_record()
        for field in _FIELDS:
            record[field] = normalized.get(field, "")
        for alias, field in _CSV_ALIASES.items():
            if not record[field] and normalized.get(alias):
                record[field] = normalized[alias]
        if record["title"]:
            records.append(record)
    return records


def parse_markdown(text: str, source_name: str) -> List[Record]:
    """Parse one Markdown note: YAML-like front matter, a heading or the filename as title."""
    record = empty_record()
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                body = "\n".join(lines[index + 1:])
                for header in lines[1:index]:
                    if ":" in header:
                        key, value = header.split(":", 1)
                        key = key.strip().lower()
                        if key in _FIELDS:
                            record[key] = value.strip()
                break
    if not record["title"]:
        for line in body.splitlines():
            if line.startswith("# "):
                record["title"] = line[2:].strip()
                break
    if not record["title"]:
        record["title"] = Path(source_name).stem.replace("-", " ").replace("_", " ").strip()
    record["abstract"] = body.strip()
    return [record] if record["title"] else []


def parse_text(text: str, source_name: str) -> List[Record]:
    """Parse a plain-text note as one record titled by its filename."""
    title = Path(source_name).stem.replace("-", " ").replace("_", " ").strip()
    record = empty_record()
    record["title"] = title
    record["abstract"] = text.strip()
    return [record] if title else []


def parse_file(path: Path) -> List[Record]:
    """Detect a file's format by suffix and parse it."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        fail(f"{path} is a PDF", "lattice reads text bibliographies, and PDFs are binary",
             "convert it first: `pdftotext paper.pdf paper.txt` (poppler, also on macOS via "
             "`brew install poppler`), or export BibTeX/RIS from the reference manager, "
             "then ingest the resulting text file")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"could not read {path}: {exc}", "ingestion needs a readable text file",
             "check the path and its permissions")
    except UnicodeDecodeError:
        fail(f"{path} is not UTF-8 text", "lattice reads text bibliographies, not binary PDFs",
             "convert the file to UTF-8 or pass a BibTeX, RIS, CSV or Markdown export")
    if suffix in (".bib", ".bibtex"):
        return parse_bibtex(text)
    if suffix == ".ris":
        return parse_ris(text)
    if suffix == ".csv":
        return parse_csv(text)
    if suffix in (".md", ".markdown"):
        return parse_markdown(text, path.name)
    if suffix == ".txt":
        return parse_text(text, path.name)
    fail(f"unsupported input format '{suffix or path.name}'",
         "lattice ingests BibTeX, RIS, CSV, Markdown and plain text",
         "export the source in one of those formats, or convert it first")


def parse_paths(paths: Iterable[Path]) -> List[Record]:
    """Parse every path in order and concatenate the records."""
    records: List[Record] = []
    for path in paths:
        records.extend(parse_file(path))
    return records


def sync_article_from_neurocore(repository: Any,
                                article_data: Dict[str, Any],
                                auto_extract: bool = False) -> Dict[str, Any]:
    """Sync a NeuroCore article dictionary into the Lattice graph.

    Normalizes authors, keywords/tags, journal/venue, and study type. If `key_findings`
    are provided or `auto_extract` is True, records quote-backed claims linked to the paper.
    """
    title = str(article_data.get("title") or "").strip()
    if not title:
        fail("article title is required", "cannot sync an article without a title",
             "provide a non-empty 'title' in article_data")

    authors_raw = article_data.get("authors")
    if isinstance(authors_raw, list):
        authors = ", ".join(str(a).strip() for a in authors_raw if str(a).strip())
    else:
        authors = str(authors_raw or "").strip()

    keywords_raw = article_data.get("keywords") or article_data.get("tags")
    if isinstance(keywords_raw, list):
        tags = ", ".join(str(k).strip() for k in keywords_raw if str(k).strip())
    else:
        tags = str(keywords_raw or "").strip()

    raw_type = article_data.get("study_type") or article_data.get("article_type")
    if raw_type:
        study_type = normalize_study_type(str(raw_type))
        if not study_type or study_type == "General Study":
            inferred = infer_study_type(title, str(article_data.get("abstract") or ""))
            if inferred != "General Study":
                study_type = inferred
    else:
        study_type = infer_study_type(title, str(article_data.get("abstract") or ""))

    paper_dict = {
        "title": title,
        "authors": authors,
        "year": str(article_data.get("year") or "").strip() or None,
        "venue": str(article_data.get("venue") or article_data.get("journal") or "").strip(),
        "doi": str(article_data.get("doi") or "").strip() or None,
        "abstract": str(article_data.get("abstract") or "").strip(),
        "tags": tags,
        "study_type": study_type,
    }

    paper, created = repository.add_paper(paper_dict)

    claims = []
    abstract_text = paper.abstract or ""

    key_findings = article_data.get("key_findings") or []
    if isinstance(key_findings, list):
        for finding in key_findings:
            assertion = str(finding or "").strip()
            if not assertion:
                continue
            if assertion in abstract_text:
                quote = assertion
                locator = "abstract"
            else:
                quote = assertion
                locator = "key_findings"
            try:
                claim = repository.add_claim(
                    paper=paper.id,
                    text=assertion,
                    quote=quote,
                    locator=locator,
                    stance="supports",
                    confidence=0.9,
                )
                claims.append(claim.to_dict())
            # hygiene: allow duplicate or unparseable finding is skipped
            except LatticeError:
                pass

    if auto_extract and abstract_text:
        from lattice.extraction import extract_from_paper
        ext = extract_from_paper(repository, paper.id)
        for c in ext.claims:
            if c.id not in {item["id"] for item in claims}:
                claims.append(c.to_dict())

    questions = []
    edges = []
    related_hypotheses = article_data.get("related_hypotheses") or []
    if isinstance(related_hypotheses, list):
        for hyp in related_hypotheses:
            hyp_text = ""
            hyp_ref = ""
            if isinstance(hyp, dict):
                hyp_text = str(hyp.get("statement") or hyp.get("title") or hyp.get("text") or "").strip()
                hyp_ref = str(hyp.get("id") or "").strip()
            elif isinstance(hyp, str):
                hyp_text = hyp.strip()
                hyp_ref = hyp.strip()
            if not hyp_text and not hyp_ref:
                continue

            q_target = None
            if hyp_ref:
                try:
                    q_target = repository.get_question(hyp_ref)
                # hygiene: allow lookup by ref may fail if not an existing question id
                except LatticeError:
                    pass
            if q_target is None and hyp_text:
                row = repository.connection.execute(
                    "SELECT id FROM questions WHERE text = ?", (hyp_text,)
                ).fetchone()
                if row:
                    q_target = repository.get_question(row[0])
                else:
                    q_target = repository.add_question(hyp_text)

            if q_target is not None:
                if q_target.to_dict() not in questions:
                    questions.append(q_target.to_dict())
                for c in claims:
                    stance = c.get("stance", "supports")
                    kind = stance if stance in ("supports", "contradicts") else "answers"
                    try:
                        edge = repository.add_edge(
                            f"claim:{c['id']}",
                            f"question:{q_target.id}",
                            kind=kind,
                            note="synced from neurocore article",
                        )
                        edges.append(edge.to_dict())
                    # hygiene: allow duplicate edges or self links to be silently skipped
                    except LatticeError:
                        pass
                if not claims:
                    try:
                        edge = repository.add_edge(
                            f"paper:{paper.id}",
                            f"question:{q_target.id}",
                            kind="answers",
                            note="synced from neurocore article",
                        )
                        edges.append(edge.to_dict())
                    # hygiene: allow duplicate edges or self links to be silently skipped
                    except LatticeError:
                        pass

    return {
        "paper": paper.to_dict(),
        "claims": claims,
        "questions": questions,
        "edges": edges,
        "created": created,
    }
