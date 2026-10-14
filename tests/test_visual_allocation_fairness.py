import json
import pytest
from test_visual_units import parent_fixture, response_for
from visual_review import run_visual_review,create_visual_review_unit
import tui_visual_callback as callback


def save_scope(revision,handoff):
    unit=json.loads((revision/handoff['request_path']).read_text())
    out=revision/unit['response_path'];out.parent.mkdir(parents=True,exist_ok=True)
    response=response_for(unit);response['status']='passed';out.write_text(json.dumps(response))
    return unit


def test_document_review_is_not_starved_behind_five_page_scopes(tmp_path):
    revision,path,parent=parent_fixture(tmp_path,'retrospective',count=5)
    seen=[]; now=[0.0]; document_budgets=[]
    def dispatch(handoffs,budget):
        wave=[json.loads((revision/h['request_path']).read_text()) for h in handoffs]
        seen.append(wave)
        if any(t['kind']=='document' for u in wave for t in u['visual_scope']):
            document_budgets.append(budget)
        for h in handoffs:save_scope(revision,h)
        now[0]+=140
    assert run_visual_review(revision,path,dispatch,480,clock=lambda:now[0])['complete']
    assert len(seen[0])==2  # overlapping page windows also own their boundaries
    assert document_budgets and min(document_budgets)>=200
    assert len(seen)==2  # local evidence first, then dependent document review
    assert all(len(u['visual_scope'])==1 for wave in seen for u in wave if any(t['kind']=='document' for t in u['visual_scope']))


def test_final_document_scope_receives_available_allocation_not_geometric_half(tmp_path):
    revision,path,parent=parent_fixture(tmp_path,'retrospective',count=5)
    for target in parent['visual_review_plan']['targets']:
        if target['kind']=='document':continue
        p=create_visual_review_unit(revision,path,[target],1)
        save_scope(revision,{'request_path':str(p.relative_to(revision))})
    def dispatch(handoffs,budget):
        assert 200<=budget<=240
        for h in handoffs:save_scope(revision,h)
    assert run_visual_review(revision,path,dispatch,240)['complete']


@pytest.mark.parametrize('budget',[0,-1,0.02,8,15,20])
def test_callback_entrypoint_does_not_launch_a_near_expired_wave(tmp_path,monkeypatch,budget):
    import storage_retention
    revision,path,parent=parent_fixture(tmp_path,'retrospective',count=5)
    unit_path=create_visual_review_unit(revision,path,[parent['visual_review_plan']['targets'][0]],1)
    envelope={'handoffs':[{'request_path':str(path.relative_to(revision))}]}
    monkeypatch.setattr(callback.sys,'argv',['callback',str(tmp_path/'invocation.json')])
    monkeypatch.setattr(callback,'callback_admission',lambda _: (envelope,revision,480))
    monkeypatch.setattr(callback,'recover_completed_observers',lambda *_: None)
    monkeypatch.setattr(storage_retention,'await_observer_reclamation',lambda *_: None)
    launched=[]
    monkeypatch.setattr(callback,'observe_unit',lambda *args:launched.append(args))
    def scheduler(revision,parent_path,dispatch,*args,**kwargs):
        try:
            dispatch([{'request_path':str(unit_path.relative_to(revision))}],budget)
        except TimeoutError as exc:
            assert 'allocation' in str(exc)
        return {'complete':False,'findings':[],'dispatch_errors':['Incomplete test scope']}
    monkeypatch.setattr(callback,'run_visual_review',scheduler)
    assert callback.main()==1  # never clinical acceptance
    assert len(launched)==(1 if budget>15 else 0)
    assert not (revision/'hermes/visual-review-observers').exists()
