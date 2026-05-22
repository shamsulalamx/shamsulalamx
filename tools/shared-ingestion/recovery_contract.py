#!/usr/bin/env python3
"""Additive recovery metadata for Batch Import generator reports."""

from __future__ import annotations

from typing import Any


RECOVERY_CONTRACT_VERSION = "organic-generator-recovery-v1"
RECOVERY_OUTCOMES = {"completed", "completed_with_warnings", "needs_review", "failed_fatal"}
FINDING_SEVERITIES = {"warning", "review", "fatal"}
FINDING_SCOPES = {"question", "chunk", "job"}


def _message_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def normalize_finding(
    finding: dict[str, Any] | str,
    *,
    default_severity: str = "warning",
    default_scope: str = "job",
    default_code: str = "UNCLASSIFIED_FINDING",
    default_recoverable: bool = False,
) -> dict[str, Any]:
    source = finding if isinstance(finding, dict) else {"message": str(finding)}
    severity = str(source.get("severity") or default_severity).strip().lower()
    scope = str(source.get("scope") or default_scope).strip().lower()
    normalized: dict[str, Any] = {
        "severity": severity if severity in FINDING_SEVERITIES else default_severity,
        "scope": scope if scope in FINDING_SCOPES else default_scope,
        "code": str(source.get("code") or source.get("issue") or default_code).strip().upper().replace(" ", "_")[:96],
        "message": str(source.get("message") or source.get("detail") or "").strip(),
        "recoverable": bool(source.get("recoverable", default_recoverable)),
    }
    for key in ("questionIndex", "chunkId"):
        value = source.get(key)
        if value not in (None, ""):
            normalized[key] = value
    if not normalized["message"]:
        normalized["message"] = normalized["code"].replace("_", " ").lower()
    return normalized


def findings_from_messages(
    values: Any,
    *,
    severity: str,
    code: str,
    scope: str = "job",
    recoverable: bool = False,
) -> list[dict[str, Any]]:
    return [
        normalize_finding(
            message,
            default_severity=severity,
            default_scope=scope,
            default_code=code,
            default_recoverable=recoverable,
        )
        for message in _message_list(values)
    ]


def review_item_finding(item: dict[str, Any]) -> dict[str, Any]:
    return normalize_finding(
        {
            "severity": "review",
            "scope": "question" if item.get("questionIndex") not in (None, "") else "job",
            "code": item.get("category") or "REVIEW_ITEM",
            "message": item.get("message") or "Generated question requires review.",
            "questionIndex": item.get("questionIndex"),
            "recoverable": True,
        },
        default_severity="review",
        default_scope="question",
        default_code="REVIEW_ITEM",
        default_recoverable=True,
    )


def recovery_metadata(
    *,
    source_type: str,
    outcome: str,
    candidate_question_count: int = 0,
    surviving_question_count: int | None = None,
    dropped_count: int = 0,
    warnings: Any = None,
    fatal_errors: Any = None,
    review_items: Any = None,
    findings: Any = None,
    survivors_import_safe: bool = False,
    retry_from_scratch_required: bool = True,
    resume_checkpoint_safe_later: bool = False,
) -> dict[str, Any]:
    warning_findings = findings_from_messages(
        warnings,
        severity="warning",
        code="GENERATOR_WARNING",
        recoverable=True,
    )
    fatal_findings = findings_from_messages(
        fatal_errors,
        severity="fatal",
        code="GENERATOR_FATAL_ERROR",
    )
    normalized_findings = [
        normalize_finding(item)
        for item in findings or []
        if isinstance(item, (dict, str))
    ]
    normalized_review_items = [
        review_item_finding(item)
        for item in review_items or []
        if isinstance(item, dict)
    ]
    all_findings = warning_findings + fatal_findings + normalized_findings + normalized_review_items
    warning_count = sum(1 for item in all_findings if item["severity"] == "warning")
    fatal_count = sum(1 for item in all_findings if item["severity"] == "fatal")
    review_count = sum(1 for item in all_findings if item["severity"] == "review" and item["recoverable"])
    normalized_outcome = outcome if outcome in RECOVERY_OUTCOMES else "failed_fatal"
    if normalized_outcome == "completed" and warning_count:
        normalized_outcome = "completed_with_warnings"
    survivors = candidate_question_count if surviving_question_count is None else surviving_question_count
    return {
        "contractVersion": RECOVERY_CONTRACT_VERSION,
        "sourceType": source_type,
        "outcome": normalized_outcome,
        "candidateQuestionCount": max(0, int(candidate_question_count or 0)),
        "survivingQuestionCount": max(0, int(survivors or 0)),
        "acceptedQuestionCount": max(0, int(survivors or 0)),
        "droppedQuestionCount": max(0, int(dropped_count or 0)),
        "warningCount": warning_count,
        "fatalCount": fatal_count,
        "recoverableReviewItemCount": review_count,
        "survivorsImportSafe": bool(survivors_import_safe),
        "retryFromScratchRequired": bool(retry_from_scratch_required),
        "resumeCheckpointSafeLater": bool(resume_checkpoint_safe_later),
        "findings": all_findings[:200],
    }
