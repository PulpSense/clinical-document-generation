"""Admission consumes exact installed lifecycle capability evidence, never a tiny-read claim.

Owner-authorized installation probes produce this report outside the immutable
package. Ordinary generation only validates identities and retained probe files.
It never provisions tools or launches a maintenance/model campaign.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

REQUIRED_CAPABILITIES = frozenset({
    'ordinary_worker_launch', 'bounded_realistic_evidence_reads', 'checkpoint_write_readback',
    'page_image_inspection', 'native_docx_xml_execution', 'parent_visual_fallback',
    'recipient_attachment_retrieval', 'filesystem_denials', 'provider_route', 'worker_child_cleanup',
})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_assurance(path: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise ValueError('Capability assurance cannot be a symlink.')
        report = json.loads(path.read_text())
        if not isinstance(report, dict) or report.get('schema_version') != 'worker-capabilities/v1':
            raise ValueError('Missing worker-capabilities/v1 installation evidence.')
        if report.get('identity') != identity:
            raise ValueError('Worker capability evidence is stale for the package, Hermes, configuration, runtime, renderer, fonts or tools.')
        capabilities = report.get('capabilities', {})
        for name in sorted(REQUIRED_CAPABILITIES):
            probe = capabilities.get(name, {})
            if probe.get('status') != 'passed' or not probe.get('evidence_files'):
                raise ValueError(f'Unproven lifecycle capability: {name}.')
            for row in probe['evidence_files']:
                file = path.parent / row['path']
                if (not file.resolve().is_relative_to(path.parent.resolve())
                        or any(p.is_symlink() for p in [file, *file.parents] if p != path.parent.parent)
                        or not file.is_file() or digest(file) != row['sha256']):
                    raise ValueError(f'Changed/missing probe evidence for {name}.')
        return {'status': 'passed', 'assurance_sha256': digest(path),
                'capabilities': sorted(REQUIRED_CAPABILITIES), 'identity': dict(identity)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'status': 'blocked', 'issue': f'{exc} Run the owner-authorized installed Linux capability campaign and retain exact evidence before admitting clinical work.'}
