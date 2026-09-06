"""Wikidata heritage designations (P1435) with optional start dates (P580).

Runs after cross-source merge against records that already have a Wikidata QID.
Generic awards (P166) are out of scope.
"""
from __future__ import annotations

from . import facts, log, progress
from .schema import Landmark
from .sources import wikidata

_BATCH = 40


def _query_chunk(qids: list[str]) -> list[dict]:
    values = " ".join(f"wd:{qid}" for qid in qids)
    query = f"""
SELECT ?item ?heritageLabel ?start WHERE {{
  VALUES ?item {{ {values} }}
  ?item p:P1435 ?stmt .
  ?stmt ps:P1435 ?heritage .
  ?heritage rdfs:label ?heritageLabel .
  FILTER(LANG(?heritageLabel) = "en")
  OPTIONAL {{ ?stmt pq:P580 ?start . }}
}}
"""
    return wikidata.run_sparql(query)


def apply(landmarks: list[Landmark]) -> int:
    """Attach P1435 recognitions. Returns the number of recognition rows added."""
    by_qid: dict[str, list[Landmark]] = {}
    for lm in landmarks:
        qid = (lm.attributes or {}).get("wikidata_qid")
        if not qid:
            continue
        key = str(qid).strip()
        if not facts.QID_RE.match(key):
            continue
        by_qid.setdefault(key.upper(), []).append(lm)
    if not by_qid:
        return 0

    added = 0
    ids = list(by_qid)
    n_batches = (len(ids) + _BATCH - 1) // _BATCH
    for bi, i in enumerate(range(0, len(ids), _BATCH), start=1):
        chunk = ids[i:i + _BATCH]
        try:
            rows = _query_chunk(chunk)
        except RuntimeError as exc:
            log.warn(f"[heritage] SPARQL batch failed ({exc})")
            rows = []
        log.info(log.fmt(
            "heritage", f"{len(chunk)} qids", step="sparql", idx=bi, total=n_batches,
        ))
        progress.tick(bi, n_batches, label="heritage")
        for row in rows:
            qid = wikidata.qid_from_uri(row.get("item"))
            name = row.get("heritageLabel")
            if not qid or not name:
                continue
            date = facts.iso_date(row.get("start"))
            canon = facts.canonical_recognition(name)
            for lm in by_qid.get(qid.upper(), []):
                if facts.add_recognition(lm, name, date, "Wikidata"):
                    added += 1
                if not date or not canon:
                    continue
                if canon == "National Register of Historic Places":
                    facts.record_date(lm, "listed", date)
                elif canon == "National Historic Landmark":
                    facts.record_date(lm, "designated", date)
    return added
