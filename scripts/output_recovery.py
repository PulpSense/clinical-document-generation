"""Constrained edits to generated scalar fields; approved evidence is immutable."""
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
