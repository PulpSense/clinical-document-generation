"""PRS output uses the client's vocabulary without changing approved facts."""
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from prs_xml import generate

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml'


def source():
    return json.loads((ROOT / 'tests/fixtures/prospective-acceptance-source.json').read_text())


def export(tmp_path, reference):
    path = tmp_path / 'study.xml'
    generate(TEMPLATE, path, reference, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'}, check_output=False)
    return next(ET.parse(path).getroot().iter('clinical_study'))


@pytest.mark.parametrize('value,expected', [(False, 'No'), ('False', 'No'), (' false ', 'No'),
                                           (True, 'Yes'), ('TRUE', 'Yes'), ('yes', 'Yes'), (' No ', 'No')])
def test_explicit_boolean_values_use_client_yes_no_vocabulary(tmp_path, value, expected):
    reference = source()
    reference['population']['healthy_volunteers'] = value
    reference['regulatory']['prs'].update(fda_regulated_drug=value, fda_regulated_device=value)
    before = copy.deepcopy(reference)
    study = export(tmp_path, reference)
    assert [study.findtext(p) for p in ('eligibility/healthy_volunteers', 'oversight_info/fda_regulated_drug',
                                      'oversight_info/fda_regulated_device')] == [expected] * 3
    assert reference == before


def test_observational_groups_keep_names_and_descriptions_with_blank_arm_types(tmp_path):
    reference = source()
    reference['regulatory']['prs']['study_type'] = 'Observational'
    reference['design']['arms'] = [
        {'label': 'One ingredient', 'type': 'Observational exposure group', 'description': 'One prescribed ingredient.'},
        {'label': 'Two or more', 'arm_type': 'Experimental', 'description': 'At least two prescribed ingredients.'},
    ]
    before = copy.deepcopy(reference)
    study = export(tmp_path, reference)
    assert [(n.findtext('arm_group_label'), n.findtext('arm_type'), n.findtext('arm_group_description/textblock'))
            for n in study.findall('arm_group')] == [
        ('One ingredient', '', 'One prescribed ingredient.'),
        ('Two or more', '', 'At least two prescribed ingredients.'),
    ]
    assert study.findtext('study_design/observational_design/number_of_groups') == '2'
    assert reference == before


@pytest.mark.parametrize('value,expected', [(None, ''), ('', ''), ('Unknown', 'Unknown'), ('No decision yet', 'No decision yet'), (0, '0')])
def test_absent_or_unknown_boolean_values_are_not_inferred(tmp_path, value, expected):
    reference = source()
    reference['population']['healthy_volunteers'] = value
    reference['regulatory']['prs'].update(fda_regulated_drug=value, fda_regulated_device=value)
    study = export(tmp_path, reference)
    assert [study.findtext(p) for p in ('eligibility/healthy_volunteers', 'oversight_info/fda_regulated_drug',
                                      'oversight_info/fda_regulated_device')] == [expected] * 3


def test_interventional_arm_types_remain_explicit(tmp_path):
    reference = source()
    reference['regulatory']['prs']['study_type'] = 'Interventional'
    reference['design']['arms'] = [{'label': 'Treatment', 'type': 'Experimental'},
                                   {'label': 'Usual habits', 'arm_type': 'No Intervention'}]
    study = export(tmp_path, reference)
    assert [n.findtext('arm_type') for n in study.findall('arm_group')] == ['Experimental', 'No Intervention']
    assert study.findtext('study_design/interventional_design/number_of_arms') == '2'


@pytest.mark.parametrize('value', [False, 'false', 'No', 'no', True, 'yes'])
def test_source_provenance_recognizes_boolean_transport_without_losing_meaning(tmp_path, value):
    reference = source()
    reference['population']['healthy_volunteers'] = value
    report = generate(TEMPLATE, tmp_path / 'study.xml', reference, {})
    assert report['source_provenance']['eligibility/healthy_volunteers']['status'] == 'mapped'
