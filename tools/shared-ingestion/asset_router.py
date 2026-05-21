#!/usr/bin/env python3
"""
Shared asset routing utilities for normalized chunks.

The router is conservative. It classifies assets for routing metadata but does
not attach assets to app-ready questions or change existing generator behavior.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from normalized_chunk_schema import AssetRef


ALGORITHM_RE = re.compile(r"\b(algorithm|flowchart|approach|workup|management|diagnostic pathway)\b", re.I)
TABLE_RE = re.compile(r"\b(table|classification|criteria|score|staging|differential|vs\.?|versus)\b", re.I)


def stable_asset_id(source_id: str, kind: str, index: int, path: str = "", text: str = "") -> str:
    payload = f"{source_id}|{kind}|{index}|{path}|{text[:120]}"
    digest = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{source_id}_{kind}_{index:02d}_{digest}"


def asset_signature(asset: dict[str, Any]) -> str:
    path = str(asset.get("path") or asset.get("assetPath") or asset.get("relativePath") or "")
    text = str(asset.get("text") or asset.get("visibleText") or asset.get("caption") or "")
    image_id = str(asset.get("imageId") or asset.get("tableId") or asset.get("id") or "")
    return hashlib.sha256(f"{image_id}|{path}|{text}".encode("utf-8", errors="replace")).hexdigest()


def suppress_duplicate_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for asset in assets:
        signature = asset_signature(asset)
        if signature in seen:
            continue
        seen.add(signature)
        kept.append(asset)
    return kept


def classify_asset_kind(asset: dict[str, Any], default_kind: str = "image") -> str:
    text = " ".join(
        str(asset.get(key) or "")
        for key in ("text", "visibleText", "caption", "label", "kind")
    )
    if default_kind == "table" or asset.get("tableId"):
        return "table"
    if ALGORITHM_RE.search(text):
        return "algorithm"
    if TABLE_RE.search(text):
        return "table_image"
    return "image"


def route_asset_role(asset: dict[str, Any], source_type: str) -> str:
    location = str(asset.get("location") or asset.get("role") or "").lower()
    kind = str(asset.get("kind") or "").lower()
    if "stem" in location or "stem" in kind:
        return "stem"
    if "explanation" in location or "rationale" in location:
        return "explanation"
    if source_type == "amboss_pdf":
        return "explanation"
    if source_type in {"fast_facts_pptx", "emma_holiday_pdf"}:
        return "context"
    return "review"


def normalize_image_refs(assets: list[dict[str, Any]], *, source_id: str, source_type: str, grounding: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, asset in enumerate(suppress_duplicate_assets(assets), start=1):
        path = str(asset.get("path") or asset.get("assetPath") or asset.get("relativePath") or "")
        text_value = asset.get("visibleText") or asset.get("text") or asset.get("caption") or ""
        if isinstance(text_value, list):
            text = " ".join(str(item) for item in text_value)
        else:
            text = str(text_value or "")
        ref_id = str(asset.get("imageId") or asset.get("id") or "") or stable_asset_id(source_id, "image", index, path, text)
        refs.append(AssetRef(
            refId=ref_id,
            kind=classify_asset_kind(asset, "image"),
            role=route_asset_role(asset, source_type),
            path=path,
            text=text,
            grounding=grounding,
            confidence=0.7 if path or text else 0.4,
            metadata={k: v for k, v in asset.items() if k not in {"path", "assetPath", "relativePath", "visibleText", "text", "caption"}},
        ).to_dict())
    return refs


def normalize_table_refs(tables: list[dict[str, Any]], *, source_id: str, source_type: str, grounding: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, table in enumerate(suppress_duplicate_assets(tables), start=1):
        text = str(table.get("text") or table.get("caption") or table.get("title") or "")
        ref_id = str(table.get("tableId") or table.get("id") or "") or stable_asset_id(source_id, "table", index, text=text)
        refs.append(AssetRef(
            refId=ref_id,
            kind="table",
            role=route_asset_role(table, source_type),
            path=str(table.get("path") or ""),
            text=text,
            grounding=grounding,
            confidence=0.8,
            metadata={k: v for k, v in table.items() if k not in {"text", "caption", "title", "path"}},
        ).to_dict())
    return refs
