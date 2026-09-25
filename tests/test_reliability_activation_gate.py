import copy
import base64
import hashlib
import json

import pytest

from hermes_e2e import CERTIFICATION_CORPUS
from reliability_activation_gate import verify_repeated_corpora


def corpus_report(seed):
    identity = {"git_commit": "a" * 40, "package_fingerprint": "b" * 64}
    payload = f"independent evidence {seed}".encode()
    entry = {
        "identity": "case-report", "kind": "case_report", "case_id": CERTIFICATION_CORPUS[0],
        "path": "cases/report.json", "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content_base64": base64.b64encode(payload).decode(),
    }
    metadata = [{key: value for key, value in entry.items() if key != "content_base64"}]
    inventory_sha256 = hashlib.sha256(json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    return {
        "schema_version": "release-certification-corpus/v1",
        "status": "passed",
        "certification_scope": "complete_five_case_corpus",
        "release_identity": identity,
        "preflight_evidence_sha256": "c" * 64,
        "case_order": list(CERTIFICATION_CORPUS),
        "cases": [
            {
                "fixture_id": fixture,
                "status": "passed",
                "findings": [],
                "within_approved_runtime": True,
                "release_identity": identity,
                "report_sha256": hashlib.sha256(f"{seed}:{fixture}".encode()).hexdigest(),
            }
            for fixture in CERTIFICATION_CORPUS
        ],
        "findings": [],
        "evidence_bundle": {
            "schema_version": "release-certification-evidence/v1",
            "inventory_sha256": inventory_sha256,
            "total_bytes": len(payload), "entries": [entry],
        },
    }


def write_reports(tmp_path, reports):
    paths = []
    for index, report in enumerate(reports):
        path = tmp_path / f"corpus-{index}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        paths.append(path)
    return paths


def test_repeat_gate_accepts_two_fresh_complete_corpora(tmp_path):
    result = verify_repeated_corpora(write_reports(tmp_path, [corpus_report(1), corpus_report(2)]))
    assert result["status"] == "passed"
    assert result["repeat_count"] == 2
    assert result["case_count"] == 2 * len(CERTIFICATION_CORPUS)


@pytest.mark.parametrize("mutation", ["blocked", "different_candidate", "reused_case", "slow"])
def test_repeat_gate_rejects_failed_or_nonindependent_run(tmp_path, mutation):
    first, second = corpus_report(1), corpus_report(2)
    second = copy.deepcopy(second)
    if mutation == "blocked":
        second["cases"][0]["status"] = "failed"
    elif mutation == "different_candidate":
        second["release_identity"]["git_commit"] = "d" * 40
    elif mutation == "reused_case":
        second["cases"][0]["report_sha256"] = first["cases"][0]["report_sha256"]
    else:
        second["cases"][0]["within_approved_runtime"] = False

    with pytest.raises(ValueError):
        verify_repeated_corpora(write_reports(tmp_path, [first, second]))
