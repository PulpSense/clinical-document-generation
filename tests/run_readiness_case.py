#!/usr/bin/env python3
"""Explicit owner-run one operation or resume; no automatic retries/installation."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib
import json
import platform
from pathlib import Path
import sys
import uuid

from readiness_injection import ParentInterruption, campaign_adapter, draft_seed_adapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--planned-operation-id', required=True)
    parser.add_argument('--release-root', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--desktop-opener-command', type=Path, required=True)
    parser.add_argument('--parent-visual-review-command', type=Path, required=True)
    parser.add_argument('--approved-by', required=True)
    parser.add_argument('--authorize-paid-operation', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-of')
    args = parser.parse_args()
    if not args.authorize_paid_operation:
        parser.error('Explicit owner authorization for this installed/paid operation is required')
    if platform.system() != 'Linux':
        parser.error('Run this campaign on the declared installed Linux host')
    manifest = json.loads(args.manifest.read_text())
    unsigned = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != manifest['manifest_sha256']:
        raise ValueError('Frozen campaign manifest changed')
    planned = next(p for p in manifest['baseline_operations'] + manifest['supplemental_operations']
                   if p['planned_operation_id'] == args.planned_operation_id)
    root, run = args.release_root.resolve(), args.run_dir.resolve()
    if run.is_relative_to(root):
        raise ValueError('Campaign work must remain outside installed code')
    sys.path.insert(0, str(root / 'scripts'))
    workflow = importlib.import_module('workflow')
    if Path(workflow.__file__).resolve() != root / 'scripts/workflow.py':
        raise ValueError('Imported a different installed candidate')
    actual = workflow._installed_release_identity(root)
    if actual['package_fingerprint'] != manifest['candidate_identity']['package_fingerprint']:
        raise ValueError('Installed bytes differ from the frozen candidate')
    if actual.get('git_commit') != manifest['candidate_identity'].get('git_commit'):
        raise ValueError('Installed commit differs from the frozen archive candidate')
    manifest_bytes = (root / workflow.RELEASE_MANIFEST).read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest['candidate_identity'].get('package_manifest_sha256'):
        raise ValueError('Installed manifest bytes differ from the declared archive candidate')
    if manifest['candidate_identity'].get('installed_worker_identity') != workflow._worker_capability_identity(root):
        raise ValueError('Freeze the actual installed worker/model configuration identity before observing operations')
    metadata_path = run / 'campaign-case.json'
    if args.resume:
        metadata = json.loads(metadata_path.read_text())
        if metadata['manifest_sha256'] != digest or metadata['planned_operation_id'] != args.planned_operation_id:
            raise ValueError('Resume belongs to another manifest or operation')
    else:
        run.mkdir(parents=True)  # Existing runs are never overwritten.
        metadata = {'planned_operation_id': args.planned_operation_id,
            'operation_id': args.planned_operation_id + '.' + uuid.uuid4().hex,
            'manifest_sha256': digest, 'source_sha256': planned['source_sha256'],
            'candidate_identity': manifest['candidate_identity'], 'retry_of': args.retry_of}
        metadata_path.write_text(json.dumps(metadata, indent=2))
        source = planned.get('source') or next(c['source'] for c in manifest['cases'] if c['case_id'] == planned['case_id'])
        (run / 'campaign-source.json').write_text(json.dumps(source, indent=2))
        path = run / workflow.REFERENCE
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(source, indent=2))
        preparation = workflow.prepare(run)
        if preparation['status'] != 'awaiting_approval':
            (run / 'preparation-result.json').write_text(json.dumps(preparation, indent=2))
            raise ValueError('Synthetic case preparation failed; retain this planned operation')
        workflow.approve(run, approved_by=args.approved_by)
    opener = workflow.command_desktop_opener(args.desktop_opener_command)
    parent = workflow.command_parent_visual_reviewer(args.parent_visual_review_command)
    with ExitStack() as stack:
        if planned['cohort'] == 'supplemental':
            opener, _events = stack.enter_context(campaign_adapter(workflow, planned, run, opener))
        elif planned['cohort'] == 'deliberate_prose_repair':
            case = next(c for c in manifest['cases'] if c['case_id'] == planned['case_id'])
            stack.enter_context(draft_seed_adapter(workflow, run / 'campaign-fault-evidence/draft', case['injection']))
        try:
            result = workflow.run_production_desktop_operation(run, skill_root=root, opener=opener,
                parent_visual_reviewer=parent, operation_id=metadata['operation_id'], manual_review=True)
        except ParentInterruption:
            result = {'status': 'interrupted', 'operation_id': metadata['operation_id'],
                'instruction': 'Resume this run with --resume and the same frozen manifest; preserve original approval and deadline.'}
            (run / 'campaign-interruption.json').write_text(json.dumps(result, indent=2))
        else:
            (run / 'campaign-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in {'passed', 'review_required'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
