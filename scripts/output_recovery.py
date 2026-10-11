"""Native candidate editing handoffs and retained compatibility editing helpers."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from contracts import get_path


def source_path(value: str) -> str:
    return re.sub(r'\[(\d+)\]', r'.\1', value)


def xml_fields(root: ET.Element) -> dict[str, ET.Element]:
    """Stable indexed native locations, independent of model-provided XPath."""
    result = {}
    def visit(node, path):
        result[path] = node
        counts = {}
        for child in node:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            visit(child, f'{path}/{child.tag}[{counts[child.tag]}]')
    study = next(root.iter('clinical_study'))
    visit(study, 'clinical_study')
    return result


def _signature(node):
    return node.tag, (node.text or '').strip(), tuple(_signature(child) for child in node)


def xml_repair_spec(path: Path, reference: Mapping[str, Any], finding: Mapping[str, Any]) -> dict[str, Any] | None:
    """Localize an exact reviewer quotation to one generated native subtree."""
    evidence = finding.get('source_path')
    if not isinstance(evidence, str):
        return None
    evidence = source_path(evidence)
    if get_path(reference, evidence) is None:
        return None
    try:
        quoted = ET.fromstring(str(finding.get('affected_passage') or ''))
        fields = xml_fields(ET.parse(path).getroot())
    except (OSError, ValueError, ET.ParseError, StopIteration):
        return None
    matches = [(key, node) for key, node in fields.items() if _signature(node) == _signature(quoted)]
    if len(matches) != 1:
        # An exact native location may disambiguate repeated scalar values.
        locations = finding.get('document_locations') or []
        matches = [(key, node) for key, node in matches if any(
            isinstance(location, str) and key in location
            for location in locations)]
    if len(matches) != 1:
        return None
    prefix = matches[0][0]
    protected = {'uid', 'provider_study_id', 'org_study_id', 'secondary_id', 'nctid'}
    editable = [{'path': key, 'before': node.text or ''}
                for key, node in fields.items() if (key == prefix or key.startswith(prefix + '/'))
                and not len(node) and not node.attrib and node.tag not in protected]
    if not editable:
        return None
    return {'kind': 'xml_fields', 'artifact': 'study.xml', 'section_id': 'prs.structured',
            'passage_id': prefix, 'source_paths': [evidence], 'fields': editable}


def _scalars(value):
    if isinstance(value, Mapping):
        for item in value.values(): yield from _scalars(item)
    elif isinstance(value, list):
        for item in value: yield from _scalars(item)
    elif value is not None:
        yield str(value)


def validate_field_edits(spec: Mapping[str, Any], edits: Any, reference: Mapping[str, Any]) -> list[dict[str, str]]:
    """Accept only changed scoped leaves with exact approved scalar evidence."""
    if not isinstance(edits, list) or not edits:
        raise ValueError('Return a nonempty field_edits list.')
    expected = {row['path']: row['before'] for row in spec['fields']}
    seen = set()
    clean = []
    for edit in edits:
        if not isinstance(edit, Mapping) or set(edit) != {'path', 'before', 'after', 'source_path'}:
            raise ValueError('Each edit needs path, before, after and source_path.')
        if any(not isinstance(edit[k], str) for k in edit):
            raise ValueError('Field edit values must be strings.')
        key, after, evidence = edit['path'], edit['after'], edit['source_path']
        if key in seen or key not in expected or edit['before'] != expected[key] or after == expected[key]:
            raise ValueError('Edit must change one uniquely inventoried current field.')
        if not any(evidence == path or evidence.startswith(path + '.') for path in spec['source_paths']):
            raise ValueError('Edit evidence is outside the approved scope.')
        value = get_path(reference, evidence)
        scalar_values = set(_scalars(value))
        if value is None or (after and after not in scalar_values) or (not after and edit['before'] in scalar_values):
            raise ValueError('Replacement must be an exact approved scalar; empty removes an unsupported generated value.')
        if len(after) > 10000 or any(c in after for c in '<>{}'):
            raise ValueError('Replacement must be plain scalar text.')
        seen.add(key)
        clean.append(dict(edit))
    return clean


def apply_xml_repairs(path: Path, repairs: list[Mapping[str, Any]]) -> None:
    """Apply authenticated proposals after every rebuild, without changing shape."""
    selected = [row for row in repairs if row.get('repair_kind') == 'xml_fields']
    if not selected:
        return
    tree = ET.parse(path)
    fields = xml_fields(tree.getroot())
    for record in sorted(selected, key=lambda row: (row.get('sequence', 0), row.get('attempt', 0), row.get('request_id', ''))):
        for edit in record['after']:
            node = fields.get(edit['path'])
            if node is None or len(node) or (node.text or '') != edit['before']:
                raise ValueError('Accepted field repair is stale for the rebuilt candidate.')
            node.text = edit['after']
    tree.write(path, encoding='utf-8', xml_declaration=True)


def xml_proposal_findings(path: Path, reference: Mapping[str, Any], record: Mapping[str, Any],
                          structural_template: Path, generation_template: Path) -> list[dict[str, Any]]:
    """Reject objectively invalid edited fields before persisting a proposal."""
    from prs_xml import validate_output
    edited = {re.sub(r'\[\d+\]', '', edit['path']).removeprefix('clinical_study/') for edit in record['after']}
    before = validate_output(path, reference, structural_template, generation_template=generation_template)
    with tempfile.TemporaryDirectory(prefix='clinical-field-proposal-') as directory:
        candidate = Path(directory) / 'study.xml'
        candidate.write_bytes(path.read_bytes())
        apply_xml_repairs(candidate, [record])
        after = validate_output(candidate, reference, structural_template, generation_template=generation_template)
    return [finding for finding in after if finding not in before or any(
        str(finding.get('field') or '') in {field, field.rsplit('/', 1)[-1]} for field in edited)]


# Only source-owned template fields; retained clauses and narrative drafts use
# their existing owners. Field names follow the native template vocabulary.
DOCX_SOURCE_FIELDS = {
    'title': 'study.title', 'studyTitle': 'study.title', 'AI_shortTitle': 'study.short_title',
    'protocolNumber': 'meta.protocol_number', 'date': 'meta.date', 'version': 'meta.version',
    'sponsortName': 'parties.sponsor.name', 'sponsorName': 'parties.sponsor.name',
    'sponsortAdress': 'parties.sponsor.address', 'sponsorAdress': 'parties.sponsor.address',
    'investigatorName': 'parties.principal_investigator.name',
    'principalInvestigatorName': 'parties.principal_investigator.name',
    'investigatorTitle': 'parties.principal_investigator.title',
    'ibrName': 'parties.irb.name', 'irbName': 'parties.irb.name',
    'ibrAdress': 'parties.irb.address', 'irbAdress': 'parties.irb.address',
    'irbPhone': 'parties.irb.phone', 'irbEmail': 'parties.irb.email',
    'facilityName': 'sites.0.facility.name', 'facilityAddress': 'sites.0.facility.address',
    'facilityCity': 'sites.0.facility.city',
    'studyCordinatorName': 'parties.study_coordinator.name',
    'studyCordinatorPhone': 'parties.study_coordinator.business_phone',
    'studyCordinator24Phone': 'parties.study_coordinator.office_phone',
    'studyCordinatorEmail': 'parties.study_coordinator.email',
    'sitesNumber': 'design.number_of_sites', 'sampleSize': 'population.sample_size',
    'interventionName': 'design.intervention_name',
}


def docx_repair_spec(rows: list[Mapping[str, Any]], finding: Mapping[str, Any], artifact: str) -> dict[str, Any] | None:
    """Use renderer-registered field spans, never arbitrary DOCX quotations."""
    evidence = finding.get('source_path')
    before = finding.get('affected_passage')
    if not isinstance(evidence, str) or not isinstance(before, str):
        return None
    evidence = source_path(evidence)
    fields = [{'path': row['path'], 'before': row['before']} for row in rows
              if row.get('source_path') == evidence and row.get('before') == before]
    if not fields:
        return None
    return {'kind': 'docx_fields', 'artifact': artifact, 'section_id': f'{artifact}.shell',
            'passage_id': f'field:{evidence}', 'fields': fields, 'source_paths': [evidence]}


# General native-candidate handoff. These helpers authenticate files; AI owns edits.
class NativeRepairIntegrityError(ValueError):
    """The repair has changed trusted source, base, scope or binding evidence."""

def native_hash(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_digest(value: Any) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def native_read(path: Path) -> dict[str, Any]:
    import json
    return json.loads(path.read_text(encoding='utf-8'))


def native_write(path: Path, value: Any) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def native_file(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise NativeRepairIntegrityError('Native repair path escapes its workspace.')
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise NativeRepairIntegrityError(f'Native repair file is missing or symlinked: {relative}')
    if not path.resolve().is_relative_to(root.resolve()):
        raise NativeRepairIntegrityError('Native repair path escapes its workspace.')
    return path


def native_files(root: Path, names: list[str]) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir() or sorted(p.name for p in root.iterdir()) != sorted(names):
        raise ValueError('Native repair requires the complete exact document inventory.')
    return {name: native_hash(native_file(root, name)) for name in names}


def native_concerns_digest(findings: list[dict[str, Any]]) -> str:
    # Review request identities change on every final review; concern identities persist.
    return native_digest([{key: value for key, value in row.items()
                          if key not in {'verification_request_id', 'verification_source_finding'}}
                         for row in findings])


def create_native_repair(revision: Path, state: dict[str, Any], reference: Mapping[str, Any],
                         bundle: Mapping[str, Any], findings: list[dict[str, Any]],
                         remaining_seconds: float | None = None) -> Path:
    import shutil
    from contracts import document_set
    names = list(document_set(reference['meta']['study_type']))
    base = native_files(revision / 'candidate', names)
    history = state.setdefault('native_repair_history', [])
    sequence = len(history) + 1
    root = revision / 'repairs' / f'pass-{sequence:03d}'
    if root.exists():
        raise ValueError('Native repair workspace is already occupied.')
    workspace = root / 'workspace'
    workspace.mkdir(parents=True)
    shutil.copytree(revision / 'candidate', root / 'base')
    evidence = root / 'evidence'
    evidence.mkdir()
    for relative in ('candidate-build.json', 'hermes/verification-requests', 'hermes/verification-responses'):
        origin = revision / relative
        target = evidence / Path(relative).name
        if origin.is_dir():
            shutil.copytree(origin, target)
        elif origin.is_file():
            shutil.copy2(origin, target)
    for name in names:
        shutil.copy2(revision / 'candidate' / name, workspace / name)
    # Scripts live beside workspace; workspace contains only deliverable native files.
    (root / 'tools').mkdir()
    prior = []
    for row in findings:
        nested = row.get('verification_source_finding')
        concern = {**row, **(nested if isinstance(nested, Mapping) else {})}
        concern['finding_id'] = concern.get('finding_id') or f"concern-{native_digest(concern)[:16]}"
        prior.append(concern)
    trusted = {name: native_hash(native_file(revision, name))
               for name in ('approved-reference.json', 'approved-source.md')}
    feedback = []
    if any(item.get('concerns_sha256') == native_concerns_digest(prior)
           for item in history):
        feedback.append('The same substantive concerns remain after an earlier repair pass. Reassess the previous ineffective action; use a different substantive correction, dispute with source evidence, or report needs_review. Do not repeat the same ineffective action.')
    request = {'schema_version': 'hermes-native-repair-request/v1', 'task': 'document_repair',
        'request_id': f'native-repair-{sequence:03d}', 'batch_id': f'native-repair-{sequence:03d}',
        'revision_id': revision.name, 'workspace_path': workspace.relative_to(revision).as_posix(),
        'tools_path': (root / 'tools').relative_to(revision).as_posix(),
        'evidence_path': evidence.relative_to(revision).as_posix(),
        'response_path': (root / 'response.json').relative_to(revision).as_posix(),
        'approved_source': dict(reference), 'approved_source_files': trusted,
        'contracted_template_bundle': dict(bundle), 'base_files': base, 'findings': prior,
        'remaining_seconds': remaining_seconds, 'feedback': feedback,
        'instructions': [
            'Inspect current native files and approved source/template context. Batch actual defects into this repair pass.',
            'Use available document/XML libraries, terminal tools or run-local scripts in tools_path. No registered edit surface is required.',
            'Edit only workspace native files; paragraphs, tables, headers/footers, metadata and XML nodes are all available.',
            'Preserve approved facts and applicable legal/template language. Keep installation/runtime code and approved source read-only.',
            'Return a bound hermes-response/v2 with status completed, disputed or needs_review, producer.model_id, producer.reviewer_id and summary. For disputed concerns give source-grounded explanations in disputes.',
            'Do not author review results. Independent reviewers inspect the corrected files and reassess disputes.',
            'Reserve time for final rendering, independent review and complete delivery; do not reset the operation deadline.']}
    request['request_sha256'] = native_digest(request)
    path = root / 'request.json'
    native_write(path, request)
    state['pending_native_repair'] = {'path': path.relative_to(revision).as_posix(), 'sha256': native_hash(path)}
    return path


def native_repair_response_valid(request: Mapping[str, Any], response: Mapping[str, Any]) -> bool:
    if not isinstance(response, Mapping):
        return False
    producer = response.get('producer')
    return (response.get('schema_version') == 'hermes-response/v2'
        and all(response.get(key) == request.get(key) for key in
                ('request_id', 'request_sha256', 'revision_id', 'task', 'batch_id'))
        and response.get('status') in {'completed', 'disputed', 'needs_review'}
        and isinstance(producer, Mapping)
        and isinstance(producer.get('model_id'), str) and bool(producer['model_id'].strip())
        and isinstance(producer.get('reviewer_id'), str) and bool(producer['reviewer_id'].strip())
        and isinstance(response.get('summary'), str) and bool(response['summary'].strip())
        and (response.get('status') != 'disputed' or bool(response.get('disputes'))))


def adopt_native_repair(revision: Path, state: dict[str, Any], reference: Mapping[str, Any],
                        bundle: Mapping[str, Any], repo: Path) -> str:
    import shutil
    from docx import Document
    from prs_xml import validate_output
    pending = state['pending_native_repair']
    request_path = native_file(revision, pending['path'])
    if native_hash(request_path) != pending['sha256']:
        raise NativeRepairIntegrityError('Native repair request identity changed.')
    request = native_read(request_path)
    if native_digest({key: value for key, value in request.items() if key != 'request_sha256'}) != request['request_sha256']:
        raise NativeRepairIntegrityError('Native repair request binding is invalid.')
    for name, digest in request['approved_source_files'].items():
        if native_hash(native_file(revision, name)) != digest:
            raise NativeRepairIntegrityError('Approved source changed during native repair.')
    try:
        if native_files(request_path.parent / 'base', list(request['base_files'])) != request['base_files']:
            raise NativeRepairIntegrityError('Original native repair checkpoint changed.')
        if native_files(revision / 'candidate', list(request['base_files'])) != request['base_files']:
            raise NativeRepairIntegrityError('Original candidate changed during native repair.')
    except (ValueError, OSError) as exc:
        raise NativeRepairIntegrityError(str(exc)) from exc
    response_path = revision / request['response_path']
    if not response_path.exists():
        return 'pending'
    response = native_read(native_file(revision, request['response_path']))
    if not native_repair_response_valid(request, response):
        raise ValueError('Repair response is incomplete or stale; copy exact request identity and supply producer, status and summary.')
    workspace = revision / request['workspace_path']
    files = native_files(workspace, list(request['base_files']))
    for name in files:
        path = workspace / name
        if name.endswith('.docx'):
            try:
                Document(path)
            except Exception as exc:
                raise ValueError(f'Repaired DOCX is unreadable: {name}: {exc}') from exc
        elif name.endswith('.xml'):
            authority = bundle['prs_authority']
            errors = validate_output(path, reference, repo / authority['structural_reference']['path'],
                                     generation_template=repo / authority['generation_template']['path'])
            if errors:
                raise ValueError('Repaired XML structure is invalid: ' + '; '.join(row['issue'] for row in errors))
    if response['status'] == 'needs_review':
        state['native_repair_unresolved'] = {'findings': request['findings'], 'summary': response['summary']}
        return 'needs_review'
    checkpoint = request_path.parent / 'accepted'
    if checkpoint.exists():
        if native_files(checkpoint, list(files)) != files:
            raise NativeRepairIntegrityError('Accepted checkpoint conflicts with repaired output.')
    else:
        import os
        staging = Path(tempfile.mkdtemp(prefix='accepted-staging-', dir=request_path.parent))
        for name in files:
            shutil.copy2(workspace / name, staging / name)
        os.replace(staging, checkpoint)
    record = {'path': checkpoint.relative_to(revision).as_posix(), 'files': files,
              'source_files': request['approved_source_files'], 'producer': response['producer'],
              'summary': response['summary'], 'disputes': response.get('disputes', []),
              'before': request['base_files'], 'after': files, 'concerns_sha256': native_concerns_digest(request['findings'])}
    state['native_checkpoint'] = record
    state.setdefault('native_repair_history', []).append(record)
    previous = state.get('native_review_context', {}).get('prior_findings', [])
    merged = {row['finding_id']: row for row in [*previous, *request['findings']]}
    state['native_review_context'] = {'prior_findings': list(merged.values()),
        'repair_author': response['producer'],
        'repair_authors': [item['producer'] for item in state['native_repair_history']],
        'repair_summary': response['summary'],
        'disputes': response.get('disputes', [])}
    state.pop('pending_native_repair')
    return 'adopted'


def restore_native_checkpoint(revision: Path, checkpoint: Mapping[str, Any] | None,
                              font_substitutions: Mapping[str, str] | None = None) -> None:
    import shutil
    if not checkpoint:
        return
    for name, digest in checkpoint['source_files'].items():
        if native_hash(native_file(revision, name)) != digest:
            raise ValueError('Accepted repair belongs to a different approved source.')
    root = revision / checkpoint['path']
    if native_files(root, list(checkpoint['files'])) != checkpoint['files']:
        raise ValueError('Accepted native repair checkpoint changed.')
    for name in checkpoint['files']:
        target = revision / 'candidate' / name
        if target.is_symlink() or target.parent.is_symlink():
            raise ValueError('Native candidate path is symlinked.')
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(root / name, target)
        if font_substitutions and name.endswith('.docx'):
            from docx import Document
            from rendering import _apply_font_substitutions
            document = Document(target)
            if _apply_font_substitutions(document, font_substitutions):
                document.save(target)
