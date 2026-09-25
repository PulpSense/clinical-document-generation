#!/usr/bin/env python3
"""Supplemental pre-activation check for repeated real Hermes certification runs."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from hermes_e2e import CERTIFICATION_CORPUS


def verify_repeated_corpora(paths: Sequence[Path]) -> dict[str, Any]:
    if len(paths) < 2 or len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("Supply at least two distinct full-corpus report paths.")
    reports = []
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, Mapping):
            raise ValueError(f"Invalid corpus report: {path}")
        reports.append(report)
    first = reports[0]
    release_identity = first.get("release_identity")
    preflight_sha256 = first.get("preflight_evidence_sha256")
    if (
        not isinstance(release_identity, Mapping)
        or not all(release_identity.get(key) for key in ("git_commit", "package_fingerprint"))
        or not isinstance(preflight_sha256, str)
        or len(preflight_sha256) != 64
    ):
        raise ValueError("The first corpus lacks a complete frozen candidate or preflight identity.")
    all_case_hashes: set[str] = set()
    bundle_hashes: set[str] = set()
    for path, report in zip(paths, reports):
        cases = report.get("cases")
        bundle = report.get("evidence_bundle")
        if (
            report.get("schema_version") != "release-certification-corpus/v1"
            or report.get("status") != "passed"
            or report.get("certification_scope") != "complete_five_case_corpus"
            or report.get("release_identity") != release_identity
            or report.get("preflight_evidence_sha256") != preflight_sha256
            or report.get("case_order") != list(CERTIFICATION_CORPUS)
            or not isinstance(cases, list)
            or len(cases) != len(CERTIFICATION_CORPUS)
            or report.get("findings")
            or not isinstance(bundle, Mapping)
            or bundle.get("schema_version") != "release-certification-evidence/v1"
        ):
            raise ValueError(f"Corpus failed or does not bind the same frozen candidate: {path}")
        entries = bundle.get("entries")
        if not isinstance(entries, list) or not entries or any(not isinstance(entry, Mapping) for entry in entries):
            raise ValueError(f"Corpus has no retained certification evidence: {path}")
        metadata = [{key: value for key, value in entry.items() if key != "content_base64"} for entry in entries]
        inventory_sha256 = hashlib.sha256(json.dumps(
            metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        if inventory_sha256 != bundle.get("inventory_sha256") or inventory_sha256 in bundle_hashes:
            raise ValueError("Certification evidence inventory is invalid or reused.")
        bundle_hashes.add(inventory_sha256)
        total_bytes = 0
        for entry in entries:
            try:
                payload = base64.b64decode(entry.get("content_base64", ""), validate=True)
            except (binascii.Error, ValueError, TypeError) as exc:
                raise ValueError("Certification evidence entry is not valid base64.") from exc
            if len(payload) != entry.get("bytes") or hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
                raise ValueError("Certification evidence entry does not match its retained bytes.")
            total_bytes += len(payload)
        if total_bytes != bundle.get("total_bytes"):
            raise ValueError("Certification evidence total byte count is invalid.")
        for fixture_id, case in zip(CERTIFICATION_CORPUS, cases):
            if (
                not isinstance(case, Mapping)
                or case.get("fixture_id") != fixture_id
                or case.get("status") != "passed"
                or case.get("findings")
                or case.get("within_approved_runtime") is not True
                or case.get("release_identity") != release_identity
                or not isinstance(case.get("report_sha256"), str)
                or len(case["report_sha256"]) != 64
            ):
                raise ValueError(f"A case failed, timed out, or changed candidate identity: {path}: {fixture_id}")
            if case["report_sha256"] in all_case_hashes:
                raise ValueError("Repeated certification reused a case report instead of rerunning it.")
            all_case_hashes.add(case["report_sha256"])
    return {
        "status": "passed",
        "release_identity": dict(release_identity),
        "preflight_evidence_sha256": preflight_sha256,
        "repeat_count": len(paths),
        "case_count": len(all_case_hashes),
        "corpus_report_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_reports", type=Path, nargs="+", help="Separate live corpus reports from one frozen candidate")
    args = parser.parse_args()
    try:
        print(json.dumps(verify_repeated_corpora(args.corpus_reports), indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Pre-activation repeat gate failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
