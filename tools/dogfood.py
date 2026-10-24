#!/usr/bin/env python3
"""
Lattice's dogfood runner: research the way a user does, then attack the surface.

The golden path drives the real CLI end to end on a temporary database - question, offline
discovery, quote-backed extraction, synthesis, snapshot export, diff and idempotent import -
then starts the real Research Studio server on a free port and uses it over HTTP. The chaos
track sends malformed JSON, unknown routes, missing entities, an empty payload and a PDF, then
proves the server is still alive. Every subprocess runs inside a context manager that kills
its whole tree, the run uses one temporary sandbox, and the tracked tree is fingerprinted
before and after.

Usage: python tools/dogfood.py   (exit 0 pass, 1 fail, 2 cannot run)

PRINCIPLE-015.
"""

import contextlib
import hashlib
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOG_PATH = ROOT / ".aikit" / "dogfood_last_run.log"
MAX_REPORT_LINES = 15
START_TIMEOUT = 20.0
REQUEST_TIMEOUT = 5.0
SUBPROCESS_TIMEOUT = 30


class Report:
    """Collects step outcomes: the console sees a summary, the log sees everything."""

    def __init__(self) -> None:
        self.lines: List[str] = []
        self.failures: List[str] = []

    def step(self, ok: bool, label: str, detail: str = "") -> bool:
        """Record one step's outcome and hand back whether it passed."""
        mark = "PASS" if ok else "FAIL"
        self.lines.append(f"[{mark}] {label}" + (f" :: {detail}" if detail else ""))
        if not ok:
            self.failures.append(f"{label}: {detail}" if detail else label)
        return ok


def terminate_process_tree(process: subprocess.Popen) -> None:
    """Kill a process and everything it started, on Windows and POSIX alike."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, timeout=SUBPROCESS_TIMEOUT)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)


@contextlib.contextmanager
def supervised(command: List[str], log):
    """Run a command with stdin closed, killing its whole tree on the way out."""
    if os.name == "nt":
        creation = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        creation = {"start_new_session": True}
    options = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                   cwd=str(ROOT), **creation)
    process = subprocess.Popen(command, **options)  # hygiene: allow RAII teardown
    try:
        yield process
    finally:
        terminate_process_tree(process)


def free_port() -> int:
    """A port the operating system says is free right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def fingerprint() -> str:
    """A digest of every tracked file, so a run that dirties the repository fails."""
    try:
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                                capture_output=True, timeout=SUBPROCESS_TIMEOUT, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"cannot list tracked files: {exc}") from exc
    digest = hashlib.sha256()
    for name in sorted(entry for entry in listed.stdout.decode("utf-8").split("\0") if entry):
        path = ROOT / name
        if path.is_file():
            digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_cli(db: str, *arguments: str, log) -> Tuple[int, str, str]:
    """Drive the real CLI in-process and capture both streams into the log."""
    from lattice.cli import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--db", db, *arguments])
    stdout, stderr = out.getvalue(), err.getvalue()
    log.write(f"$ lattice {' '.join(arguments)}  (exit {code})\n{stdout}{stderr}\n")
    return code, stdout, stderr


def http(method: str, url: str, body: Optional[bytes] = None,
         headers: Optional[dict] = None) -> Tuple[int, str]:
    """One HTTP request; an HTTP error status is returned instead of raised."""
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def post_json(base: str, route: str, payload: dict) -> Tuple[int, str]:
    """POST one JSON object to the studio."""
    return http("POST", base + route, json.dumps(payload).encode("utf-8"),
                {"Content-Type": "application/json"})


def wait_for_server(base: str) -> bool:
    """Poll the studio until it answers or the start budget runs out."""
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        try:
            status, _ = http("GET", base + "/")
        except OSError:
            time.sleep(0.2)
            continue
        if status == 200:
            return True
        time.sleep(0.2)
    return False


def golden_cli(report: Report, sandbox: Path, log) -> None:
    """The research workflow a user actually runs, end to end on one database."""
    db = str(sandbox / "research.db")
    code, out, _ = run_cli(db, "init", log=log)
    report.step(code == 0, "cli init")

    code, out, _ = run_cli(db, "question", "Does slow-wave sleep consolidate memory?", log=log)
    report.step(code == 0 and "q_000001" in out, "cli question", out.strip()[-60:])

    code, out, _ = run_cli(db, "fetch", "slow-wave sleep memory", "--source", "offline",
                           "--limit", "3", log=log)
    report.step(code == 0 and "discovered" in out, "cli fetch offline", out.splitlines()[0][:60])

    code, out, _ = run_cli(db, "extract", "--all", "--question", "q_000001", log=log)
    report.step(code == 0 and "claim" in out, "cli extract", out.strip()[:60])

    code, out, _ = run_cli(db, "synthesize", "q_000001", log=log)
    report.step(code == 0 and bool(out.strip()), "cli synthesize", f"{len(out)} chars")

    snapshot = str(sandbox / "baseline.jsonl")
    code, out, _ = run_cli(db, "export", snapshot, log=log)
    report.step(code == 0 and Path(snapshot).is_file(), "cli export snapshot")

    run_cli(db, "question", "Does caffeine impair memory?", log=log)
    code, out, _ = run_cli(db, "diff", snapshot, log=log)
    report.step(code == 1 and "1 added" in out, "cli diff detects the change",
                out.splitlines()[0][:70] if out else "")

    other = str(sandbox / "imported.db")
    final = str(sandbox / "final.jsonl")
    code, _, _ = run_cli(db, "export", final, log=log)
    report.step(code == 0, "cli re-export after the change")
    code, _, _ = run_cli(other, "import", final, log=log)
    report.step(code == 0, "cli import snapshot")

    code, out, _ = run_cli(db, "--json", "stats", log=log)
    code2, out2, _ = run_cli(other, "--json", "stats", log=log)
    try:
        source = json.loads(out)
        target = json.loads(out2)
        same = all(source[key] == target[key]
                   for key in ("papers", "claims", "questions", "edges"))
    except ValueError:
        same = False
    report.step(code == 0 and code2 == 0 and same, "cli import round-trip matches stats")


def golden_studio(report: Report, sandbox: Path, log) -> None:
    """The real Research Studio server, driven over HTTP like the browser does."""
    db = str(sandbox / "studio.db")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-m", "lattice", "--db", db, "web",
               "--host", "127.0.0.1", "--port", str(port)]
    with supervised(command, log) as process:
        ready = wait_for_server(base)
        status, page = http("GET", base + "/") if ready else (0, "")
        report.step(ready and status == 200 and 'id="onboarding"' in page,
                    "studio serves the onboarding page")
        if not ready:
            return
        status, _ = post_json(base, "/api/demo", {})
        report.step(status == 200, "studio demo seeding", f"exit {status}")
        status, body = http("GET", base + "/api/overview")
        try:
            papers = int(json.loads(body).get("stats", {}).get("papers", 0)) if status == 200 else 0
        except ValueError:
            papers = 0
        report.step(status == 200 and papers > 0, "studio overview", f"{papers} papers")
        status, _ = http("GET", base + "/api/search?q=sleep")
        report.step(status == 200, "studio search")
        status, _ = http("GET", base + "/api/matrix")
        report.step(status == 200, "studio evidence matrix")
        status, body = post_json(base, "/api/questions", {"text": "Does the studio work?"})
        report.step(status == 200 and "question" in body, "studio records a question")
        chaos_studio(report, base, log)
        status, _ = http("GET", base + "/api/overview")
        report.step(status == 200, "studio alive after chaos", f"exit {status}")
        report.step(process.poll() is None, "studio process still running")


def chaos_studio(report: Report, base: str, log) -> None:
    """Malformed and hostile requests the browser never sends but a bug or a bot might."""
    status, _ = http("POST", base + "/api/questions", b"{not json",
                     {"Content-Type": "application/json"})
    report.step(status == 400, "chaos malformed JSON", f"exit {status}")
    status, _ = http("GET", base + "/api/nonexistent")
    report.step(status == 404, "chaos unknown route", f"exit {status}")
    status, _ = http("GET", base + "/api/subgraph?ref=claim:c_999999")
    report.step(status == 400, "chaos missing entity", f"exit {status}")
    status, _ = post_json(base, "/api/claims", {})
    report.step(status == 400, "chaos empty claim payload", f"exit {status}")
    log.write(f"chaos track finished against {base}\n")


def chaos_cli(report: Report, sandbox: Path, log) -> None:
    """CLI failures must be the documented Error/Why/Fix triad, not tracebacks."""
    fake = sandbox / "paper.pdf"
    fake.write_bytes(b"%PDF-1.4 \xff\xfe binary bytes")
    db = str(sandbox / "chaos.db")
    code, _, err = run_cli(db, "ingest", str(fake), log=log)
    report.step(code == 1 and "pdftotext" in err and "Traceback" not in err,
                "chaos pdf ingestion gives the recipe")
    code, _, err = run_cli(db, "show", "claim:c_999999", log=log)
    report.step(code == 1 and "Traceback" not in err, "chaos missing entity exits cleanly")


def main(argv: List[str]) -> int:
    """Run the golden and chaos tracks, print a summary, keep the full log on disk."""
    del argv
    report = Report()
    try:
        before = fingerprint()
    except RuntimeError as exc:
        print(f"[CANNOT RUN] {exc}")
        print("Why: the dogfood run must prove it left the tracked tree untouched.")
        print("Fix: run it inside the lattice git repository with git installed.")
        return 2
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lattice_dogfood_") as sandbox_name, \
            open(LOG_PATH, "w", encoding="utf-8") as log:
        sandbox = Path(sandbox_name)
        log.write(f"lattice dogfood run {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        try:
            golden_cli(report, sandbox, log)
            golden_studio(report, sandbox, log)
            chaos_cli(report, sandbox, log)
            report.step(fingerprint() == before, "tracked tree unchanged")
        except Exception as exc:  # noqa: BLE001 - the runner reports, never crashes
            log.write(f"\nrunner crashed: {type(exc).__name__}: {exc}\n")
            report.step(False, "runner", f"{type(exc).__name__}: {exc}")
        for line in report.lines:
            log.write(line + "\n")
    passed = len(report.lines) - len(report.failures)
    total = len(report.lines)
    print(f"LATTICE DOGFOOD (PRINCIPLE-015): {passed}/{total} steps passed")
    for failure in report.failures[:MAX_REPORT_LINES - 2]:
        print(f"  FAIL {failure}")
    print(f"  full log: {LOG_PATH.relative_to(ROOT)}")
    return 0 if not report.failures else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
