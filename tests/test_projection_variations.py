"""Independent scalar expectations through the public XML generation boundary."""
import copy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from prs_xml import generate
from test_construction_reliability import source_for, FAMILIES

CASES = [
    ({'name': 'Jordan Example 1', 'first_name': 'Jordan', 'last_name': 'Example 1'}, ('Jordan', '', 'Example 1')),
    ({'name': 'María Isabel de la Cruz', 'given_name': 'María Isabel', 'surname': 'de la Cruz'}, ('María Isabel', '', 'de la Cruz')),
    ({'name': 'Jean André van der Meer', 'first_name': 'Jean', 'last_name': 'van der Meer'}, ('Jean', 'André', 'van der Meer')),
    ({'name': 'Jordan Other Example', 'first_name': 'Jordan', 'last_name': 'Example', 'middle_name': ''}, ('Jordan', '', 'Example')),
    ({'first_name': 'Alex', 'last_name': 'de Silva'}, ('Alex', '', 'de Silva')),
    ({'name': 'Taylor Morgan Reed', 'first_name': 'Taylor'}, ('Taylor', 'Morgan', 'Reed')),
    ({'name': 'Taylor Morgan de Silva', 'family_name': 'de Silva'}, ('Taylor', 'Morgan', 'de Silva')),
    ({'name': 'Dr. Casey Example'}, ('Casey', '', 'Example')),
]


@pytest.mark.parametrize('branch,family', FAMILIES[:-1])
@pytest.mark.parametrize('person,expected', CASES)
def test_person_representations_preserve_explicit_boundaries_for_every_role(tmp_path, branch, family, person, expected):
    source = source_for(branch, family)
    source['parties']['principal_investigator'].update(person)
    source['parties']['study_coordinator'].update(person)
    source['sites'][0].pop('investigators', None)
    source['sites'][0].pop('contacts', None)
    source['sites'][0]['investigator'] = copy.deepcopy(person)
    source['sites'][0]['contact'] = copy.deepcopy(person)
    before = copy.deepcopy(source)
    output = tmp_path / 'study.xml'
    generate(Path('assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml'), output,
             source, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'})
    root = ET.parse(output).getroot()
    for path in ('overall_official', 'overall_contact', 'location/investigator', 'location/contact'):
        node = root.find('.//clinical_study/' + path)
        assert tuple(node.findtext(key) for key in ('first_name', 'middle_name', 'last_name')) == expected
    assert source == before
