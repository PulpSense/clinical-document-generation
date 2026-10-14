"""TOC destination review belongs to authenticated whole-document scope."""
import json
import pytest
import quality
from test_visual_units import parent_fixture, response_for
from visual_review import create_visual_review_unit, run_visual_review


def test_page_units_do_not_request_out_of_scope_toc_destinations(tmp_path):
    revision, path, parent=parent_fixture(tmp_path,'retrospective',count=5)
    pages=[t for t in parent['visual_review_plan']['targets'] if t['kind']=='page']
    unit=json.loads(create_visual_review_unit(revision,path,pages[:3],1).read_text())
    assert 'toc_mismatch' not in unit['checks']
    assert all('toc_mismatch' not in t['checks'] for t in unit['visual_scope'])
    document=next(t for t in parent['visual_review_plan']['targets'] if t['kind']=='document')
    assert 'toc_mismatch' in document['checks']
    assert 'toc_destinations' in document['checks']
    assert {p['page'] for a in unit['artifacts'] for p in a['pages']}=={1,2,3}


@pytest.mark.parametrize('bad_toc',[False,True])
def test_full_recombination_still_requires_document_toc_judgment(tmp_path,bad_toc):
    revision,path,parent=parent_fixture(tmp_path,'retrospective',count=5)
    observed=[]
    def dispatch(handoffs,budget):
        for h in handoffs:
            unit=json.loads((revision/h['request_path']).read_text())
            assert unit['checks']==list(dict.fromkeys(c for t in unit['visual_scope'] for c in t['checks']))
            response=response_for(unit)
            for row in response['visual_assessments']:
                observed.append(row['target_id'])
                if row['kind']!='document':
                    assert 'toc_mismatch' not in row['checks']
                else:
                    assert unit.get('document_evidence')
                    assert 'toc_mismatch' in row['checks']
                    if bad_toc:
                        row['status']='blocked'
                        response['findings']=[{'target_id':row['target_id'],'artifact':'protocol','page':2,
                            'check':'toc_mismatch','element':'TOC destination','issue':'Fixture TOC destination differs from actual bound heading','recommended_action':'Correct native TOC and rerender'}]
            target=revision/unit['response_path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(response))
    result=run_visual_review(revision,path,dispatch,60)
    assert result['complete']
    assert len(observed)==len(parent['visual_review_plan']['targets'])
    assert bool(result['findings'])==bad_toc
    final=json.loads((revision/parent['response_path']).read_text())
    assert (final['status']=='passed') is (not bad_toc)
    assert quality.verification_response_is_terminal(revision,path)


@pytest.mark.parametrize('tamper',['missing_document_proof','omitted_document_toc','invented_page_toc'])
def test_final_adoption_rejects_toc_coverage_or_proof_tampering(tmp_path,tamper):
    revision,path,parent=parent_fixture(tmp_path,'retrospective',count=5)
    def dispatch(handoffs,budget):
        for h in handoffs:
            unit=json.loads((revision/h['request_path']).read_text())
            target=revision/unit['response_path'];target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(response_for(unit)))
    assert run_visual_review(revision,path,dispatch,60)['complete']
    assert quality.verification_response_is_terminal(revision,path)
    response_path=revision/parent['response_path'];response=json.loads(response_path.read_text())
    document=next(row for row in response['visual_assessments'] if row['kind']=='document')
    if tamper=='missing_document_proof':
        (revision/document['proof']['response_path']).unlink()
    elif tamper=='omitted_document_toc':
        document['checks'].remove('toc_mismatch');response_path.write_text(json.dumps(response))
    else:
        response['page_assessments'][0]['checks'].append('toc_mismatch');response_path.write_text(json.dumps(response))
    assert not quality.verification_response_is_terminal(revision,path)
