#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
GENERATOR_PATH = ROOT / "generate_lecture_slide_questions.py"
EVENT_PREFIX = "CH" + "UNK_"


def event_name(name: str) -> str:
    return EVENT_PREFIX + name


def load_generator() -> Any:
    os.environ["BIC_JOB_OUTPUT_ROOT"] = tempfile.mkdtemp(prefix="ff-contract-runtime-")
    os.environ["GEMINI_API_KEY"] = "contract-test-key"
    spec = importlib.util.spec_from_file_location("ff_generator_contract", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.ensure_dirs()
    return module


def slide(index: int) -> dict[str, Any]:
    return {
        "slideId": f"s{index}",
        "primaryConcepts": [f"Concept {index}"],
        "clinicalFacts": [f"Clinical fact {index}", f"Presentation fact {index}"],
        "diagnosticFacts": [f"Diagnostic fact {index}"],
        "managementFacts": [f"Management fact {index}"],
        "questionArchetype": "diagnosis",
        "metadata": {"sourceSlideIds": [f"slide-{index}"]},
    }


def allocation(index: int, count: int = 1) -> dict[str, Any]:
    s = slide(index)
    return {"slideId": s["slideId"], "questionCount": count, "slide": s}


def question(slide_id: str, suffix: str = "") -> dict[str, Any]:
    return {
        "slideId": slide_id,
        "questionKind": "single-best-answer",
        "stemTemplate": "contract",
        "testedConcept": f"Concept {slide_id}",
        "diagnosisOrTarget": f"Target {slide_id}",
        "distractorFamily": "diagnosis",
        "stem": f"A patient presents with symptoms {suffix}. Which of the following is the most likely diagnosis?",
        "answerChoices": [
            {"label": "A", "text": f"Correct {slide_id}{suffix}"},
            {"label": "B", "text": f"Distractor B {slide_id}{suffix}"},
            {"label": "C", "text": f"Distractor C {slide_id}{suffix}"},
            {"label": "D", "text": f"Distractor D {slide_id}{suffix}"},
        ],
        "correctAnswer": "A",
        "correctExplanation": "The grounded facts support the correct diagnosis.",
        "incorrectExplanations": [
            {"label": "B", "explanation": "Not supported."},
            {"label": "C", "explanation": "Not supported."},
            {"label": "D", "explanation": "Not supported."},
        ],
        "educationalObjective": "Recognize the diagnosis from the presentation.",
        "retrievalTag": "contract",
        "reviewPearl": "Use the key clinical finding.",
        "imageRouting": [],
        "tableUse": [],
        "sourceFactIds": [],
    }


def normalized_payload(count: int) -> dict[str, Any]:
    return {
        "sourceFile": "contract_fast_facts.pptx",
        "pptxSha256": "contract",
        "slides": [slide(i) for i in range(1, count + 1)],
    }


def graph_for(gen: Any, chunk_label: str, allocs: list[dict[str, Any]]) -> Any:
    return gen.build_execution_graph("", [{
        "chunkId": chunk_label,
        "expectedQuestions": sum(int(a.get("questionCount") or 0) for a in allocs),
        "conceptIds": [str(a.get("slideId") or "") for a in allocs],
    }])


def assert_chunk_lifecycle(events: list[dict[str, Any]]) -> None:
    starts = [e for e in events if e.get("event") == event_name("START")]
    assert starts, "no chunk start events emitted"
    terminal = [e for e in events if e.get("event") in {event_name("SUCCESS"), event_name("DROP")}]
    assert terminal, "no terminal chunk events emitted"
    terminal_labels = {str(e.get("chunk") or "") for e in terminal}
    for event in starts:
        assert "/" in str(event.get("chunk") or ""), f"chunk X/Y missing: {event}"
        assert int(event.get("allocatedQuestions") or 0) >= 0, f"allocated question count missing: {event}"
        assert int(event.get("globalRetryId") or 0) >= 1, f"global retry id missing: {event}"
        assert str(event.get("chunkLabel") or "") in terminal_labels, f"chunk has no terminal lifecycle event: {event}"


def assert_retry_bounds(events: list[dict[str, Any]], telemetry: dict[str, Any] | None = None) -> None:
    graph = telemetry.get("executionGraph") if telemetry else None
    if isinstance(graph, dict):
        for chunk in graph.get("chunks") or []:
            attempts = chunk.get("attempts") or []
            assert len(attempts) <= 3, f"chunk retry attempts exceeded bound: {chunk}"
            phases = {str(attempt.get("phase") or "") for attempt in attempts}
            assert phases <= {"initial", "repair", "fallback"}, f"unexpected retry phases: {chunk}"
        return
    attempts = [int(e.get("globalRetryId") or 0) for e in events if e.get("event") in {event_name("START"), event_name("SUCCESS"), event_name("DROP"), event_name("HEARTBEAT")}]
    assert attempts, "global retry ids missing"
    assert max(attempts) <= 3, f"local retry ids exceeded bound: {attempts}"


def assert_execution_graph(telemetry: dict[str, Any], total_chunks: int, completed: int, dropped: int) -> None:
    graph = telemetry.get("executionGraph")
    assert isinstance(graph, dict), "execution graph missing"
    assert graph["totalChunks"] == total_chunks
    assert len(graph["chunks"]) == total_chunks
    assert graph["progress"]["completedChunks"] == completed
    assert graph["progress"]["droppedChunks"] == dropped


def write_review_for_drops(gen: Any, result: dict[str, Any]) -> Path | None:
    drops = [d for d in result.get("dropped") or [] if isinstance(d, dict)]
    if not drops:
        return None
    failed = [d["originalQuestion"] for d in drops]
    return gen.write_failed_repair_review_draft(
        "contract_fast_facts.pptx",
        gen.SOURCE_FORMAT,
        "fast_facts_pptx",
        failed,
        drops,
        {"chunkTelemetry": result},
        None,
        None,
    )


def test_perfect_input() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(i) for i in range(1, 5)]

    def exact(_api_key: str, _source: str, chunk: list[dict[str, Any]], *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [question(a["slideId"]) for a in chunk]

    gen.call_fast_facts_generation_chunk_once = exact
    questions, telemetry = gen.generate_fast_facts_questions(normalized_payload(4), allocs, gen.empty_memory())
    events = telemetry["events"]
    assert len(questions) == 4
    assert not telemetry["dropped"]
    assert_chunk_lifecycle(events)
    assert_retry_bounds(events, telemetry)
    assert events[0]["event"] == event_name("PLAN")
    assert_execution_graph(telemetry, 2, 2, 0)
    return {"events": events, "reviewPath": None}


def test_partial_failure_continues() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(i) for i in range(1, 5)]

    def mixed(_api_key: str, _source: str, chunk: list[dict[str, Any]], _memory: dict[str, Any], chunk_label: str, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        if chunk_label.startswith("fast_facts_chunk1"):
            raise gen.PipelineError("forced schema failure")
        return [question(a["slideId"]) for a in chunk]

    gen.call_fast_facts_generation_chunk_once = mixed
    questions, telemetry = gen.generate_fast_facts_questions(normalized_payload(4), allocs, gen.empty_memory())
    review_path = write_review_for_drops(gen, telemetry)
    assert len(questions) == 1, "pipeline did not continue to next chunk after failure"
    assert review_path and review_path.exists()
    draft = json.loads(review_path.read_text())
    assert len(draft["candidateQuestions"]) == 3
    assert all("rawGenerationPayload" in q["metadata"] for q in draft["candidateQuestions"])
    assert_chunk_lifecycle(telemetry["events"])
    assert_retry_bounds(telemetry["events"], telemetry)
    assert_execution_graph(telemetry, 2, 1, 1)
    return {"events": telemetry["events"], "reviewPath": str(review_path)}


def test_total_chunk_failure() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(1)]

    def fail(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise gen.PipelineError("total synthetic failure")

    gen.call_fast_facts_generation_chunk_once = fail
    questions, telemetry = gen.generate_fast_facts_questions(normalized_payload(1), allocs, gen.empty_memory())
    review_path = write_review_for_drops(gen, telemetry)
    assert not questions
    assert review_path and review_path.exists()
    draft = json.loads(review_path.read_text())
    assert draft["candidateQuestions"][0]["metadata"]["rawGenerationPayload"] is not None
    assert any(e["event"] == event_name("DROP") for e in telemetry["events"])
    assert_retry_bounds(telemetry["events"], telemetry)
    assert_execution_graph(telemetry, 1, 0, 1)
    return {"events": telemetry["events"], "reviewPath": str(review_path)}


def test_cardinality_overflow() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(1)]
    raw = {"questions": [question("s1", "a"), question("s1", "b")]}
    items, diagnostics = gen.normalize_fast_facts_generated_question_items(raw, allocs, "overflow")
    assert len(items) == 1
    assert diagnostics["overflowCount"] == 1
    assert diagnostics["overflowItems"]
    return {"events": [{"event": "CARDINALITY_OVERFLOW", **diagnostics}], "reviewPath": None}


def test_cardinality_underflow() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(1, count=2)]

    def under(_api_key: str, _source: str, chunk: list[dict[str, Any]], *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [question(chunk[0]["slideId"])]

    gen.call_fast_facts_generation_chunk_once = under
    result = gen.generate_fast_facts_chunk_with_retries("key", "contract.pptx", allocs, {}, "underflow", 1, 1, graph_for(gen, "underflow", allocs))
    assert len(result["items"]) == 1
    assert any(e["event"] == event_name("SUCCESS") and e["globalRetryId"] == 2 and e["retryPhase"] == "repair" for e in result["events"])
    assert_retry_bounds(result["events"])
    return {"events": result["events"], "reviewPath": None}


def test_packaged_path_stress() -> dict[str, Any]:
    gen = load_generator()
    report_path = gen.write_report({"pathStress": True}, "contract_path_stress")
    assert gen.BASE_DIR not in report_path.parents
    display = gen.display_path(report_path)
    assert display.startswith("/")
    return {"events": [{"event": "PACKAGED_PATH_STRESS", "reportPath": display}], "reviewPath": None}


def test_stall_detection_slow_chunk() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(1)]

    def slow(_api_key: str, _source: str, chunk: list[dict[str, Any]], *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        time.sleep(0.2)
        return [question(chunk[0]["slideId"])]

    gen.call_fast_facts_generation_chunk_once = slow
    result = gen.generate_fast_facts_chunk_with_retries("key", "contract.pptx", allocs, {}, "slow", 1, 1, graph_for(gen, "slow", allocs))
    assert result["events"][0]["event"] == event_name("START")
    assert any(e["event"] == event_name("SUCCESS") and e["runtime"] >= 0.2 for e in result["events"])
    return {"events": result["events"], "reviewPath": None}


def test_heartbeat_blocking_call() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(1)]
    emitted: list[dict[str, Any]] = []
    original_event = gen.fast_facts_chunk_event

    def capture(event_type: str, **payload: Any) -> dict[str, Any]:
        event = original_event(event_type, **payload)
        emitted.append(event)
        return event

    def slow_raw(*_args: Any, **_kwargs: Any) -> str:
        time.sleep(3.2)
        return json.dumps({"questions": [question("s1")]})

    gen.fast_facts_chunk_event = capture
    gen.raw_gemini_call = slow_raw
    items = gen.call_fast_facts_generation_chunk_once("key", "contract.pptx", allocs, {}, "heartbeat", "global_retry_1_initial", chunk_index=1, chunk_total=1)
    assert len(items) == 1
    heartbeat_events = [event for event in emitted if event.get("event") == event_name("HEARTBEAT")]
    assert heartbeat_events, "blocking call emitted no chunk heartbeat"
    assert heartbeat_events[0]["chunkLabel"] == "heartbeat"
    assert heartbeat_events[0]["phase"] == "generating"
    assert int(heartbeat_events[0]["elapsedMs"]) >= 2000
    return {"events": emitted, "reviewPath": None}


def test_long_run_ten_plus_chunks() -> dict[str, Any]:
    gen = load_generator()
    allocs = [allocation(i) for i in range(1, 32)]

    def exact(_api_key: str, _source: str, chunk: list[dict[str, Any]], *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [question(a["slideId"]) for a in chunk]

    gen.call_fast_facts_generation_chunk_once = exact
    questions, telemetry = gen.generate_fast_facts_questions(normalized_payload(31), allocs, gen.empty_memory())
    plan = next(event for event in telemetry["events"] if event.get("event") == event_name("PLAN"))
    assert plan["totalChunks"] >= 10
    assert len(questions) == 31
    assert_chunk_lifecycle(telemetry["events"])
    assert_execution_graph(telemetry, plan["totalChunks"], plan["totalChunks"], 0)
    return {"events": telemetry["events"], "reviewPath": None}


TESTS = [
    ("PERFECT_INPUT_TEST", test_perfect_input),
    ("PARTIAL_FAILURE_TEST", test_partial_failure_continues),
    ("TOTAL_FAILURE_TEST", test_total_chunk_failure),
    ("CARDINALITY_OVERFLOW_TEST", test_cardinality_overflow),
    ("CARDINALITY_UNDERFLOW_TEST", test_cardinality_underflow),
    ("PACKAGED_PATH_STRESS_TEST", test_packaged_path_stress),
    ("STALL_DETECTION_TEST", test_stall_detection_slow_chunk),
    ("HEARTBEAT_BLOCKING_CALL_TEST", test_heartbeat_blocking_call),
    ("TEN_PLUS_LONG_RUN_TEST", test_long_run_ten_plus_chunks),
]


def main() -> int:
    results: list[dict[str, Any]] = []
    failed = False
    for name, fn in TESTS:
        try:
            result = fn()
            results.append({"name": name, "status": "PASS", **result})
            print(f"{name}: PASS")
            for event in result["events"][:8]:
                print("  " + json.dumps(event, ensure_ascii=False, default=str))
            if result.get("reviewPath"):
                print(f"  reviewPath={result['reviewPath']}")
        except Exception as exc:
            failed = True
            results.append({"name": name, "status": "FAIL", "error": str(exc)})
            print(f"{name}: FAIL: {exc}")
    summary = {
        "contractSuite": "fast-facts-generation-contract-v1",
        "passed": sum(1 for item in results if item["status"] == "PASS"),
        "failed": sum(1 for item in results if item["status"] == "FAIL"),
        "results": results,
    }
    print("CONTRACT_SUMMARY " + json.dumps(summary, ensure_ascii=False, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
