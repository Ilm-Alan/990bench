"""Download IRS TEOS 990-series XML batches, yearly indexes and the Business Master File.

    python -m bench990.fetch [--years 2024 2025 2026]

Skips files whose size already matches the server's Content-Length and records
SHA-256 checksums in data/raw/SHA256SUMS so a build can be traced to exact inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import httpx

from .corpus import RAW

XML = "https://apps.irs.gov/pub/epostcard/990/xml"
PAGE = "https://www.irs.gov/charities-non-profits/form-990-series-downloads"
BMF = [f"https://www.irs.gov/pub/irs-soi/eo{n}.csv" for n in (1, 2, 3, 4)]


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    head = client.head(url)
    head.raise_for_status()
    size = int(head.headers.get("content-length", -1))
    if dest.exists() and dest.stat().st_size == size:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as resp, tmp.open("wb") as fh:
        resp.raise_for_status()
        for chunk in resp.iter_bytes(1 << 20):
            fh.write(chunk)
    tmp.rename(dest)
    print(f"downloaded {dest.name} ({dest.stat().st_size:,} bytes)", flush=True)


def batches(years: list[int]) -> list[str]:
    """Batch zips as linked from the IRS download page. The index files are not a complete list:
    they label the returns of some split batches (2025 and 2026 05A/05B) with the first name only."""
    html = httpx.get(PAGE, timeout=60, follow_redirects=True).text
    names = set(re.findall(r"/990/xml/(\d{4})/(\d{4}_TEOS_XML_[0-9A-Za-z]+)\.zip", html))
    return sorted(name for year, name in names if int(year) in years)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2024, 2025, 2026])
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=600, follow_redirects=True) as client:
        for year in args.years:
            _download(client, f"{XML}/{year}/index_{year}.csv", RAW / f"index_{year}.csv")
        for batch in batches(args.years):
            _download(client, f"{XML}/{batch[:4]}/{batch}.zip", RAW / f"{batch}.zip")
        for url in BMF:
            _download(client, url, RAW / f"bmf_{url.rsplit('/', 1)[1]}")
    files = sorted(p for p in RAW.iterdir() if p.suffix in {".zip", ".csv"})
    (RAW / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print(f"{len(files)} files checksummed")


if __name__ == "__main__":
    main()
