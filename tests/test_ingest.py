"""Format parsers stay dependency-free and deterministic."""

import tempfile
import unittest
from pathlib import Path

from lattice.errors import LatticeError
from lattice.ingest import (
    parse_bibtex,
    parse_csv,
    parse_file,
    parse_markdown,
    parse_paths,
    parse_ris,
)


class BibtexTests(unittest.TestCase):
    """BibTeX braces, authors and identifiers."""

    def test_two_entries(self):
        text = """
        @article{one, title={Sleep and {Memory}}, author={Ada Lovelace and Alan Turing},
                 year={2020}, journal={Nature}, doi={10.1000/xyz}}
        @inproceedings{two, title="A quoted title", author={Grace Hopper}, year={1999}}
        """
        records = parse_bibtex(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "Sleep and {Memory}")
        self.assertEqual(records[0]["authors"], "Ada Lovelace; Alan Turing")
        self.assertEqual(records[0]["venue"], "Nature")
        self.assertEqual(records[1]["year"], "1999")

    def test_unbalanced_braces_fail(self):
        with self.assertRaises(LatticeError):
            parse_bibtex("@article{x, title={broken}")

    def test_keywords_and_study_type_fields(self):
        records = parse_bibtex(
            "@article{x, title={A trial}, keywords={Sleep, Memory}, "
            "studytype={Randomized Controlled Trial}}"
        )
        self.assertEqual(records[0]["tags"], "Sleep, Memory")
        self.assertEqual(records[0]["study_type"], "Randomized Controlled Trial")


class RisTests(unittest.TestCase):
    """RIS tag handling."""

    def test_single_record(self):
        text = "TY  - JOUR\nTI  - A study\nAU  - One Author\nAU  - Two Author\nPY  - 2021\nDO  - 10.5/x\nER  - \n"
        records = parse_ris(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["authors"], "One Author; Two Author")
        self.assertEqual(records[0]["year"], "2021")
        self.assertEqual(records[0]["doi"], "10.5/x")

    def test_keywords_and_study_type_tags(self):
        text = (
            "TY  - JOUR\nTI  - A cohort study\nKW  - sleep\nKW  - memory\n"
            "M3  - Cohort Study\nER  - \n"
        )
        records = parse_ris(text)
        self.assertEqual(records[0]["tags"], "sleep, memory")
        self.assertEqual(records[0]["study_type"], "Cohort Study")


class CsvTests(unittest.TestCase):
    """CSV headers map to metadata fields case-insensitively."""

    def test_header_mapping(self):
        text = "Title,Authors,Year,DOI\nA paper,Someone,2022,10.9/z\n"
        records = parse_csv(text)
        self.assertEqual(records[0]["title"], "A paper")
        self.assertEqual(records[0]["doi"], "10.9/z")

    def test_keyword_and_study_type_aliases(self):
        text = (
            "title,keywords,study_type\n"
            "A paper,\"sleep, memory\",Cohort Study\n"
        )
        records = parse_csv(text)
        self.assertEqual(records[0]["tags"], "sleep, memory")
        self.assertEqual(records[0]["study_type"], "Cohort Study")


class MarkdownTests(unittest.TestCase):
    """Front matter and heading fallbacks."""

    def test_front_matter(self):
        text = "---\ntitle: Own title\nauthors: A. Person\nyear: 2023\ndoi: 10.2/q\n---\n# Heading\n\nBody."
        record = parse_markdown(text, "note.md")[0]
        self.assertEqual(record["title"], "Own title")
        self.assertEqual(record["authors"], "A. Person")
        self.assertEqual(record["doi"], "10.2/q")

    def test_heading_and_filename_fallbacks(self):
        self.assertEqual(parse_markdown("# From heading\nbody", "x.md")[0]["title"], "From heading")
        self.assertEqual(parse_markdown("body only", "my-note.md")[0]["title"], "my note")

    def test_front_matter_carries_tags_and_study_type(self):
        text = "---\ntitle: Note\ntags: sleep, memory\nstudy_type: Case Study\n---\nBody."
        record = parse_markdown(text, "note.md")[0]
        self.assertEqual(record["tags"], "sleep, memory")
        self.assertEqual(record["study_type"], "Case Study")


class FileTests(unittest.TestCase):
    """Suffix dispatch and readable failures."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def write(self, name, content):
        path = Path(self.directory.name) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_plain_text(self):
        path = self.write("field-notes.txt", "observations")
        records = parse_file(path)
        self.assertEqual(records[0]["title"], "field notes")
        self.assertEqual(records[0]["abstract"], "observations")

    def test_parse_paths(self):
        first = self.write("a.bib", "@article{a, title={A}}")
        second = self.write("b.ris", "TY  - JOUR\nTI  - B\nER  - \n")
        self.assertEqual(len(parse_paths([first, second])), 2)

    def test_unsupported_suffix(self):
        path = self.write("paper.pdf", "not really a pdf")
        with self.assertRaises(LatticeError):
            parse_file(path)


if __name__ == "__main__":
    unittest.main()
