"""Generic ArcGIS Feature Service helpers: paged feature queries + attachments.

ArcGIS caps a single response (typically 1000-2000 features) and signals more via
`exceededTransferLimit`, so we page with resultOffset/resultRecordCount.
"""
from __future__ import annotations

from typing import Any, Iterator

from ..http_util import get_json, post_json


def query_features(
    layer_url: str,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = True,
    out_sr: int = 4326,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Return all features (paged) as raw ArcGIS feature dicts."""
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "outSR": out_sr,
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        payload = get_json(layer_url + "/query", params)
        batch = payload.get("features", [])
        features.extend(batch)
        if not payload.get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)
    return features


def count(layer_url: str, where: str = "1=1") -> int:
    payload = get_json(
        layer_url + "/query",
        {"where": where, "returnCountOnly": "true", "f": "json"},
    )
    return int(payload.get("count", 0))


def first_attachment_urls(
    layer_url: str, object_ids: list[int], batch: int = 100
) -> dict[int, str]:
    """Map OBJECTID -> URL of its first attachment (e.g. a marker photo).

    Uses the bulk queryAttachments operation to avoid one request per feature.
    """
    result: dict[int, str] = {}
    for chunk in _chunks(object_ids, batch):
        ids = ",".join(str(i) for i in chunk)
        try:
            payload = post_json(
                layer_url + "/queryAttachments",
                {"objectIds": ids, "f": "json"},
            )
        except RuntimeError:
            continue
        for group in payload.get("attachmentGroups", []):
            oid = group.get("parentObjectId")
            infos = group.get("attachmentInfos") or []
            if oid is None or not infos:
                continue
            att_id = infos[0].get("id")
            if att_id is not None:
                result[int(oid)] = f"{layer_url}/{oid}/attachments/{att_id}"
    return result


def point_lonlat(feature: dict[str, Any]) -> tuple[float, float] | None:
    geom = feature.get("geometry") or {}
    x, y = geom.get("x"), geom.get("y")
    if x is None or y is None:
        return None
    return float(x), float(y)


def _chunks(seq: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
