"""Owner-run, run-local injection boundary; never supplies reviewer judgments.

Live integration must call this before candidate/render/review binding. A missing
or ambiguous predeclared selector fails closed; it cannot choose a new challenge
by inspecting results. All before/after bytes stay in an append-only seed ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import io

from lxml import etree as ET


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inject_native(candidate_dir: Path, seed: dict, ledger_dir: Path):
    """Apply one predeclared generic native XML edit, retaining exact original bytes."""
    revision = candidate_dir.parent
    if any((revision / directory).exists() and any((revision / directory).iterdir())
           for directory in ('hermes/verification-requests', 'rendered')):
        raise ValueError('Injection must precede render/review evidence binding.')
    relative = Path(seed['artifact'])
    artifact = candidate_dir / relative
    if relative.is_absolute() or '..' in relative.parts or any(p.is_symlink() for p in [artifact, *artifact.parents]):
        raise ValueError('Seed artifact escapes the run-local candidate.')
    original = artifact.read_bytes()
    part = seed.get('part')
    if artifact.suffix == '.docx':
        with ZipFile(io.BytesIO(original)) as archive:
            xml = archive.read(part)
    elif artifact.suffix == '.xml' and part is None:
        xml = original
    else:
        raise ValueError('Seeds require a native DOCX XML part or PRS XML artifact.')
    root = ET.fromstring(xml, ET.XMLParser(resolve_entities=False, no_network=True))
    nodes = root.xpath(seed['xpath'], namespaces=seed.get('namespaces', {}))
    if len(nodes) != seed.get('expected_matches', 1):
        raise ValueError('Predeclared native seed selector is missing or ambiguous.')
    for node in nodes:
        attribute = seed.get('attribute')
        actual = node.get(attribute) if attribute else node.text
        if actual != seed['before']:
            raise ValueError('Predeclared seed original value differs; preserve this unexecuted challenge.')
        if seed.get('remove_node'):
            node.getparent().remove(node)
        elif attribute:
            node.set(attribute, seed['after'])
        else:
            node.text = seed['after']
    changed_xml = ET.tostring(root, xml_declaration=True, encoding='UTF-8')
    changed = changed_xml
    if part:
        buffer = io.BytesIO()
        with ZipFile(io.BytesIO(original)) as source, ZipFile(buffer, 'w') as output:
            for member in source.infolist():
                output.writestr(member, changed_xml if member.filename == part else source.read(member.filename))
        changed = buffer.getvalue()
    ledger_dir.mkdir(parents=True, exist_ok=True)
    if Path(seed['seed_id']).name != seed['seed_id'] or seed['seed_id'] in {'.', '..'}:
        raise ValueError('Seed identity must be a single safe path component.')
    seed_dir = ledger_dir / seed['seed_id']
    seed_dir.mkdir()  # Never overwrite a prior injection attempt.
    (seed_dir / 'before.bin').write_bytes(original)
    (seed_dir / 'after.bin').write_bytes(changed)
    (seed_dir / 'seed.json').write_text(json.dumps({'seed': seed, 'before_sha256': sha(original),
        'after_sha256': sha(changed), 'provenance': 'test_owned_native_seed_before_review'}, indent=2))
    artifact.write_bytes(changed)
    return {'before_sha256': sha(original), 'after_sha256': sha(changed)}


def inject_drafting_response(request: dict, response: dict, sentence: str, ledger_dir: Path):
    """The owner protocol's unsupported sentence, before response consumption."""
    if any(response.get(k) != request.get(k) for k in ('request_id', 'request_sha256', 'task', 'revision_id')):
        raise ValueError('Draft injection requires the actual bound author response.')
    changed = json.loads(json.dumps(response))
    # Select the introduction explicitly; never inject into an arbitrary section.
    drafts = changed.get('section_results', [])
    section = next((r for r in drafts if r.get('section_id') == 'introduction'), None)
    if section is None or not section.get('paragraphs'):
        raise ValueError('Initial Protocol introduction is absent; do not adapt the fixed challenge.')
    paragraph = section['paragraphs'][0]
    if not isinstance(paragraph, dict) or not isinstance(paragraph.get('text'), str):
        raise ValueError('Unsupported drafting response paragraph shape.')
    paragraph['text'] += ' ' + sentence
    ledger_dir.mkdir(parents=True)  # Preserve each attempt rather than overwrite.
    for name, value in [('before', response), ('after', changed)]:
        (ledger_dir / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))
    (ledger_dir / 'provenance.json').write_text(json.dumps({
        'seed_author': 'owner_campaign_harness', 'kind': 'test_owned_draft_mutation',
        'original_producer': response.get('producer'),
        'request_sha256': request['request_sha256'],
        'before_sha256': sha((ledger_dir / 'before.json').read_bytes()),
        'after_sha256': sha((ledger_dir / 'after.json').read_bytes())}, indent=2))
    return changed


def draft_seed_adapter(workflow_module, ledger_root: Path, sentence: str):
    """Owner-reviewed context manager around the installed pre-consumption publisher.

    Patches the test process adapter in memory, never installed script bytes or
    worker identities. Independent review always runs through the real adapter.
    """
    from contextlib import contextmanager
    @contextmanager
    def installed():
        publish = workflow_module._production_publish_quiet_response
        injected = set()
        def intercept(revision, handoff, stdout_log):
            accepted = publish(revision, handoff, stdout_log)
            if not accepted or handoff.get('task') != 'section_drafting':
                return accepted
            request = json.loads((revision / handoff['request_path']).read_text())
            identity = request['request_id']
            response_path = revision / request['response_path']
            response = json.loads(response_path.read_text())
            if identity not in injected and any(r.get('section_id') == 'introduction'
                                               for r in response.get('section_results', [])):
                changed = inject_drafting_response(request, response, sentence,
                    ledger_root / hashlib.sha256(identity.encode()).hexdigest())
                response_path.write_text(json.dumps(changed, ensure_ascii=False, indent=2))
                injected.add(identity)
            return accepted
        workflow_module._production_publish_quiet_response = intercept
        try:
            yield injected
        finally:
            workflow_module._production_publish_quiet_response = publish
    return installed()
