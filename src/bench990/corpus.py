"""Filing corpus: an SQLite catalog over IRS TEOS XML batch zips, read on demand.

The catalog holds one row per filing (header facts only). Return bodies stay in the
IRS zips and are parsed when needed.
"""

from __future__ import annotations

import sqlite3
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import inflate64
from lxml import etree

NS = "{http://www.irs.gov/efile}"
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "corpus.sqlite"
RETURN_TYPES = ("990", "990EZ", "990PF")

SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
  object_id TEXT PRIMARY KEY,
  batch TEXT NOT NULL,
  ein TEXT NOT NULL,
  name TEXT NOT NULL,
  city TEXT,
  state TEXT,
  return_type TEXT NOT NULL,
  tax_year INTEGER NOT NULL,
  period_begin TEXT,
  period_end TEXT,
  return_version TEXT,
  amended INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS filings_ein ON filings(ein);
CREATE INDEX IF NOT EXISTS filings_state_city ON filings(state, city);
"""


def local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def text(el: etree._Element | None, path: str) -> str | None:
    if el is None:
        return None
    found = el.find(_ns(path))
    return found.text.strip() if found is not None and found.text else None


def _ns(path: str) -> str:
    return "/".join(NS + part for part in path.split("/"))


DEFLATE64 = 9


@lru_cache(maxsize=8)
def _zip(batch: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(RAW / f"{batch}.zip")


@lru_cache(maxsize=8)
def _members(batch: str) -> dict[str, zipfile.ZipInfo]:
    """Object ID -> zip entry. Some batches nest members in a folder."""
    return {Path(i.filename).name.removesuffix("_public.xml"): i
            for i in _zip(batch).infolist() if i.filename.endswith("_public.xml")}


def read_member(batch: str, info: zipfile.ZipInfo) -> bytes:
    """Read one entry; Python's zipfile cannot inflate the Deflate64 entries some IRS batches use."""
    zf = _zip(batch)
    if info.compress_type != DEFLATE64:
        return zf.read(info)
    with open(zf.filename, "rb") as fh:
        fh.seek(info.header_offset)
        local = fh.read(30)
        name_len, extra_len = int.from_bytes(local[26:28], "little"), int.from_bytes(local[28:30], "little")
        fh.seek(info.header_offset + 30 + name_len + extra_len)
        data = inflate64.Inflater().inflate(fh.read(info.compress_size))
    if zlib.crc32(data) != info.CRC:
        raise zipfile.BadZipFile(f"CRC mismatch in {info.filename}")
    return data


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


@dataclass(frozen=True)
class Filing:
    object_id: str
    batch: str
    ein: str
    name: str
    city: str | None
    state: str | None
    return_type: str
    tax_year: int
    period_begin: str | None
    period_end: str | None
    return_version: str | None
    amended: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Filing:
        return cls(**{k: row[k] for k in row.keys()} | {"amended": bool(row["amended"])})


def load_xml(batch: str, object_id: str) -> etree._Element:
    return etree.fromstring(read_member(batch, _members(batch)[object_id]))


def parse_header(root: etree._Element) -> dict[str, object]:
    head = root.find(NS + "ReturnHeader")
    filer = head.find(NS + "Filer")
    name = text(filer, "BusinessName/BusinessNameLine1Txt") or ""
    name2 = text(filer, "BusinessName/BusinessNameLine2Txt")
    data = root.find(NS + "ReturnData")
    main = next(iter(data))
    amended = text(main, "AmendedReturnInd") in {"X", "true", "1"}
    return {
        "ein": text(filer, "EIN"),
        "name": f"{name} {name2}".strip() if name2 else name,
        "city": text(filer, "USAddress/CityNm"),
        "state": text(filer, "USAddress/StateAbbreviationCd"),
        "return_type": text(head, "ReturnTypeCd"),
        "tax_year": int(text(head, "TaxYr") or 0),
        "period_begin": text(head, "TaxPeriodBeginDt"),
        "period_end": text(head, "TaxPeriodEndDt"),
        "return_version": root.get("returnVersion"),
        "amended": int(amended),
    }


def _headers(batch: str) -> list[dict[str, object]]:
    rows = []
    for object_id, info in _members(batch).items():
        header = parse_header(etree.fromstring(read_member(batch, info)))
        if header["return_type"] in RETURN_TYPES:
            rows.append(header | {"object_id": object_id, "batch": batch})
    return rows


def build(batches: list[str], workers: int = 8) -> int:
    con = connect()
    con.executescript(SCHEMA)
    count = 0
    with ProcessPoolExecutor(workers) as pool:
        for batch, rows in zip(batches, pool.map(_headers, batches)):
            con.executemany(
                "INSERT OR REPLACE INTO filings VALUES (:object_id, :batch, :ein, :name, :city, :state,"
                " :return_type, :tax_year, :period_begin, :period_end, :return_version, :amended)",
                rows,
            )
            count += len(rows)
            print(f"{batch}: {len(rows)} filings", flush=True)
    con.commit()
    return count


def get(object_id: str) -> Filing | None:
    row = connect().execute("SELECT * FROM filings WHERE object_id = ?", (object_id,)).fetchone()
    return Filing.from_row(row) if row else None


