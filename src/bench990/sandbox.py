"""Per-run analyst workstation: a network-less Docker container with the IRS data mounted read-only.

Layout inside the container:
  /data/README.md   description of the files (sandbox/README.md)
  /data/irs/        IRS TEOS XML batch zips, yearly index CSVs, Business Master File CSVs
  /work/            writable working directory; the deliverable is written here
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from .corpus import RAW, ROOT

IMAGE = "bench990-sandbox"
README = ROOT / "sandbox" / "README.md"
README_DOCUMENTS = ROOT / "sandbox" / "README-documents.md"
OUTPUT_LIMIT = 8000


class Sandbox:
    """`documents=True` mounts only the index and BMF CSVs: returns are then seen as page images
    through host-side tools, never as XML."""

    def __init__(self, work: Path, documents: bool = False) -> None:
        self.work = work
        self.documents = documents
        self.name = f"bench990-{uuid.uuid4().hex[:10]}"

    def _mounts(self) -> list[str]:
        if not self.documents:
            return ["-v", f"{RAW}:/data/irs:ro", "-v", f"{README}:/data/README.md:ro"]
        files = sorted(RAW.glob("index_*.csv")) + sorted(RAW.glob("bmf_eo*.csv"))
        return [arg for f in files for arg in ("-v", f"{f}:/data/irs/{f.name}:ro")] + \
            ["-v", f"{README_DOCUMENTS}:/data/README.md:ro"]

    def __enter__(self) -> Sandbox:
        self.work.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", self.name, "--network", "none",
             "--memory", "3g", "--cpus", "2", "--pids-limit", "512",
             *self._mounts(), "-v", f"{self.work.resolve()}:/work", IMAGE, "sleep", "infinity"],
            check=True, capture_output=True,
        )
        return self

    def __exit__(self, *exc: object) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)

    def bash(self, command: str, timeout: int = 300) -> str:
        proc = subprocess.run(
            ["docker", "exec", "-w", "/work", self.name, "timeout", str(timeout), "bash", "-lc", command],
            capture_output=True, text=True, errors="replace",
        )
        out = proc.stdout + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        if proc.returncode == 124:
            out += f"\n[command timed out after {timeout}s]"
        elif proc.returncode:
            out += f"\n[exit code {proc.returncode}]"
        if len(out) > OUTPUT_LIMIT:
            half = OUTPUT_LIMIT // 2
            out = f"{out[:half]}\n[... {len(out) - OUTPUT_LIMIT} characters omitted ...]\n{out[-half:]}"
        return out or "[no output]"
