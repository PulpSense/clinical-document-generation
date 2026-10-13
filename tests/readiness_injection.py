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
        if seed.get('required_text'):
            texts = node.xpath('.//w:t/text()', namespaces=seed.get('namespaces', {}))
            if seed['required_text'] not in ' '.join(texts):
                raise ValueError('The predeclared material clinical row is absent; preserve an unexecuted challenge.')
        attribute = seed.get('attribute')
        actual = node.get(attribute) if attribute else node.text
        before = seed.get('before')
        if seed.get('check_before', True):
            matches = isinstance(actual, str) and isinstance(before, str) and before in actual if seed.get('replace_substring') else actual == before
            if not matches:
                raise ValueError('Predeclared seed original value differs; preserve this unexecuted challenge.')
        if seed.get('remove_node'):
            node.getparent().remove(node)
        elif seed.get('operation') == 'replace_paragraph':
            namespace = seed['namespaces']['w']
            for child in list(node):
                if child.tag != '{' + namespace + '}pPr':
                    node.remove(child)
            run = ET.SubElement(node, '{' + namespace + '}r')
            ET.SubElement(run, '{' + namespace + '}t').text = seed['after']
        elif seed.get('operation') == 'exact_row_height':
            namespace = seed['namespaces']['w']
            properties = node.find('{' + namespace + '}trPr')
            if properties is None:
                properties = ET.SubElement(node, '{' + namespace + '}trPr')
            for child in list(properties):
                if child.tag == '{' + namespace + '}trHeight':
                    properties.remove(child)
            height = ET.SubElement(properties, '{' + namespace + '}trHeight')
            height.set('{' + namespace + '}val', str(seed['twips']))
            height.set('{' + namespace + '}hRule', 'exact')
        elif attribute:
            node.set(attribute, seed['after'])
        else:
            node.text = actual.replace(before, seed['after'], 1) if seed.get('replace_substring') else seed['after']
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
                ledger = ledger_root / hashlib.sha256(identity.encode()).hexdigest()
                if ledger.exists():
                    previous = json.loads((ledger / 'after.json').read_text())
                    if response != previous:
                        raise ValueError('Saved draft injection bytes changed across resume.')
                    injected.add(identity)
                    return accepted
                changed = inject_drafting_response(request, response, sentence, ledger)
                response_path.write_text(json.dumps(changed, ensure_ascii=False, indent=2))
                injected.add(identity)
            return accepted
        workflow_module._production_publish_quiet_response = intercept
        try:
            yield injected
        finally:
            workflow_module._production_publish_quiet_response = publish
    return installed()


class ParentInterruption(BaseException):
    """Deliberate owner campaign interruption; resume the original operation."""


def campaign_adapter(workflow, planned, run_dir: Path, opener):
    """Install only the predeclared faults around the actual installed adapter.

    No reviewer response is manufactured. F1 requires a real checkpoint and
    interrupts the parent once; invoke the original operation again to resume.
    """
    from contextlib import contextmanager
    import copy
    @contextmanager
    def installed():
        case_id = planned['case_id']
        originals = {name: getattr(workflow, name) for name in (
            'render_assurance', 'create_verification_requests', '_production_subprocess_environment',
            '_production_publish_quiet_response', '_production_dispatch_handoffs', '_production_sandbox_prefix')}
        event_file = run_dir / 'campaign-fault-evidence/events.json'
        events = json.loads(event_file.read_text()) if event_file.is_file() else []
        injected_drafts = {e['request_id'] for e in events if e['event'] == 'substantive_seed_before_consumption'}
        native_seeded = any(e['event'] == 'predeclared_native_seeds_applied' for e in events)
        interrupted = any(e['event'] == 'truncate_real_final_and_interrupt_parent' for e in events)
        retrieval_failed = any(e['event'] == 'transient_actual_recipient_transport_failure' for e in events)
        denied_repair_areas = set()
        def record(event, **details):
            events.append({'event': event, **details})
            directory = run_dir / 'campaign-fault-evidence'
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'events.json').write_text(json.dumps(events, indent=2))
        def render(root, revision, *args, **kwargs):
            nonlocal native_seeded
            if case_id.startswith('Q') and not native_seeded:
                for seed in planned['native_seeds']:
                    inject_native(revision / 'candidate', seed, run_dir / 'campaign-fault-evidence/native-seeds')
                native_seeded = True
                record('predeclared_native_seeds_applied')
            return originals['render_assurance'](root, revision, *args, **kwargs)
        def requests(revision, reference, report, **kwargs):
            if case_id == 'D1' and kwargs.get('review_set', 1) == 1:
                context = copy.deepcopy(kwargs.get('review_context') or {})
                context.setdefault('prior_findings', []).extend(planned['native_seeds'])
                kwargs['review_context'] = context
                record('test_owned_prior_hypothesis_before_binding', seeds=planned['native_seeds'])
            return originals['create_verification_requests'](revision, reference, report, **kwargs)
        def environment(root):
            value = originals['_production_subprocess_environment'](root)
            if case_id == 'F1':
                shim = run_dir / 'campaign-fault-evidence/read-limit-shim'
                shim.mkdir(parents=True, exist_ok=True)
                code = "from tools import file_tools\noriginal=file_tools.read_file_tool\ndef limited(path,offset=1,limit=2000,**kwargs):\n return original(path,offset=offset,limit=min(limit,64),**kwargs)\nfile_tools.read_file_tool=limited\n"
                (shim / 'sitecustomize.py').write_text(code)
                value['PYTHONPATH'] = str(shim)
                record('real_worker_read_file_limit', maximum_lines=64, shim_sha256=sha(code.encode()))
            return value
        def publish(revision, handoff, stdout_log):
            nonlocal interrupted
            accepted = originals['_production_publish_quiet_response'](revision, handoff, stdout_log)
            if not accepted:
                return accepted
            request = json.loads((revision / handoff['request_path']).read_text())
            path = revision / request['response_path']
            response = json.loads(path.read_text())
            if case_id == 'F3' and request['task'] == 'section_drafting' and request['request_id'] not in injected_drafts and any(
                    row.get('section_id') == 'introduction' for row in response.get('section_results', [])):
                changed = inject_drafting_response(request, response, 'Participants receive an unsupported experimental drug.',
                    run_dir / 'campaign-fault-evidence' / ('draft-' + sha(request['request_id'].encode())))
                path.write_text(json.dumps(changed, indent=2))
                injected_drafts.add(request['request_id'])
                record('substantive_seed_before_consumption', request_id=request['request_id'])
            if case_id == 'F1' and handoff.get('review_unit_id') and not interrupted:
                checkpoint = revision / request['review_transport']['progress_path']
                if not checkpoint.is_file():
                    raise RuntimeError('F1 requires a real worker checkpoint; retain unexecuted fault rather than fabricate progress')
                directory = run_dir / 'campaign-fault-evidence/truncation'
                directory.mkdir()
                (directory / 'real-final.bin').write_bytes(path.read_bytes())
                (directory / 'real-checkpoint.bin').write_bytes(checkpoint.read_bytes())
                original_final = path.read_bytes()
                path.write_bytes(b'{')
                saved = workflow.content_review_unit_result(revision, revision / handoff['request_path'])
                if not saved or not (saved['section_assessments'] or saved['cross_document_assessments'] or saved['findings']):
                    path.write_bytes(original_final)
                    record('fault_not_executed_no_consumable_checkpoint', request_id=request['request_id'])
                    raise RuntimeError('F1 requires authenticated consumable saved progress; the fault was not executed')
                interrupted = True
                record('truncate_real_final_and_interrupt_parent', request_id=request['request_id'])
                raise ParentInterruption()
            if case_id == 'F3' and request['task'] == 'document_repair':
                record('real_repair_author_result', status=response.get('status'), producer=response.get('producer'))
            return accepted
        def dispatch(handoffs, remaining, revision, configuration, **kwargs):
            if case_id == 'F2':
                visual = [h for h in handoffs if h['task'] == 'rendered_page_visual_verification']
                if visual:
                    record('delegated_visual_unavailable', requests=[h['request_id'] for h in visual])
                    handoffs = [h for h in handoffs if h not in visual]
            if case_id == 'F3':
                for handoff in handoffs:
                    if handoff['task'] == 'document_repair':
                        request = json.loads((revision / handoff['request_path']).read_text())
                        denied_repair_areas.update(str((revision / request[k]).resolve()) for k in ('workspace_path', 'tools_path'))
                        record('repair_workspace_writes_unavailable')
            if handoffs:
                return originals['_production_dispatch_handoffs'](handoffs, remaining, revision, configuration, **kwargs)
        def prefix(policy):
            if case_id == 'F3' and denied_repair_areas:
                value = json.loads(policy.read_text())
                value['writable'] = [p for p in value['writable'] if p not in denied_repair_areas]
                policy.write_text(json.dumps(value))
            return originals['_production_sandbox_prefix'](policy)
        def retrieval(path):
            nonlocal retrieval_failed
            if case_id == 'F2' and not retrieval_failed:
                retrieval_failed = True
                record('transient_actual_recipient_transport_failure')
                raise OSError('Predeclared transient recipient retrieval fault')
            return opener(path)
        if hasattr(opener, 'capability_executable'):
            retrieval.capability_executable = opener.capability_executable
        replacements = {'render_assurance': render, 'create_verification_requests': requests,
            '_production_subprocess_environment': environment, '_production_publish_quiet_response': publish,
            '_production_dispatch_handoffs': dispatch, '_production_sandbox_prefix': prefix}
        for name, value in replacements.items():
            setattr(workflow, name, value)
        try:
            yield retrieval, events
        finally:
            for name, value in originals.items():
                setattr(workflow, name, value)
    return installed()
