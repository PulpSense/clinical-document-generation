import json
import pytest
from owner_artifact_audit import validate_owner_audit


def test_success_only_audit_cannot_admit_next_case(tmp_path):
    audit={'schema_version':'readiness-artifact-audit/v1','auditor_id':'claimed-independent',
        'independent_of_drafting_and_repair':True,'all_source_facts_reviewed':True,
        'all_final_pages_inspected':True,'material_defects_remaining':0,'collateral_loss':0,
        'delivered_artifact_sha256':{'protocol.docx':'a'*64},'seed_results':{}}
    (tmp_path/'independent-artifact-audit.json').write_text(json.dumps(audit))
    with pytest.raises(ValueError,match='inspection'):
        validate_owner_audit(tmp_path,{},audit,{'protocol.docx':'a'*64},set())


def test_runtime_evidence_correlates_calls_results_and_complete_reads(tmp_path):
    import sqlite3
    from owner_artifact_audit import runtime_access,sha
    state=tmp_path/'observer';state.mkdir()
    (tmp_path/'native.txt').write_text('one\ntwo\n')
    (tmp_path/'page.png').write_bytes(b'fixture image access envelope only')
    (tmp_path/'response.json').write_text('{}')
    con=sqlite3.connect(state/'state.db')
    con.execute('CREATE TABLE sessions(id TEXT,model TEXT)')
    con.execute('CREATE TABLE messages(session_id TEXT,role TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT,content TEXT)')
    con.execute('INSERT INTO sessions VALUES(?,?)',('unit-only','gpt-6.1-sol'))
    calls=[{'id':'r','function':{'name':'read_file','arguments':{'path':str(tmp_path/'native.txt'),'limit':2}}},
        {'id':'v','function':{'name':'vision_analyze','arguments':{'image_url':str(tmp_path/'page.png')}}},
        {'id':'w','function':{'name':'write_file','arguments':{'path':str(tmp_path/'response.json'),'content':'{}'}}}]
    con.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',('unit-only','assistant',json.dumps(calls),None,None,None))
    for i,n,v in [('r','read_file',{'content':'1|one\n2|two','total_lines':2}),('v','vision_analyze',{'success':True}),('w','write_file',{'verified':True})]:
        con.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',('unit-only','tool',None,i,n,json.dumps(v)))
    con.commit();con.close()
    identity,model,reads,images,writes=runtime_access(tmp_path,state)
    assert identity=='unit-only' and reads=={'native.txt'} and images=={'page.png'}
    assert writes=={'response.json':sha(tmp_path/'response.json')}
    con=sqlite3.connect(state/'state.db');con.execute("UPDATE messages SET content=? WHERE tool_call_id='v'",(json.dumps({'success':True,'error':'no actual pixels'}),));con.commit();con.close()
    assert runtime_access(tmp_path,state)[3]==set()
    con=sqlite3.connect(state/'state.db');con.execute("UPDATE messages SET content=? WHERE tool_call_id='r'",(json.dumps({'content':'1|one\n2|two...','total_lines':2,'truncated_lines':True}),));con.commit();con.close()
    assert runtime_access(tmp_path,state)[2]==set()


def full_fixture(tmp_path):
    from docx import Document
    from owner_artifact_audit import native_structure,sha
    output=tmp_path/'output';output.mkdir()
    native=output/'protocol.docx';doc=Document();doc.add_paragraph('Synthetic fixture only');doc.save(native)
    source={'study':{'title':'Synthetic fixture only'}}
    (tmp_path/'campaign-source.json').write_text(json.dumps(source))
    structure=tmp_path/'structure.json';structure.write_text(json.dumps(native_structure(native),indent=2))
    revision=tmp_path/'revisions/r1';render=revision/'rendered';render.mkdir(parents=True)
    pdf=render/'protocol.pdf';pdf.write_bytes(b'fixture renderer binding only')
    page=render/'page-1.png';page.write_bytes(b'fixture pixels envelope only')
    renderer=revision/'hermes/verification-requests/visual.json';renderer.parent.mkdir(parents=True)
    artifact={'docx':'candidate/protocol.docx','docx_sha256':sha(native),'pdf':'rendered/protocol.pdf','pdf_sha256':sha(pdf),'page_count':1,
        'pages':[{'page':1,'path':'rendered/page-1.png','sha256':sha(page)}]}
    renderer.write_text(json.dumps({'artifacts':[artifact]}))
    relative=lambda p:str(p.relative_to(tmp_path))
    request={'schema_version':'owner-artifact-inspection/v1','source':source,'source_sha256':'source-id',
        'delivered_artifact_sha256':{'protocol.docx':sha(native)},'expected_facts':{'study.title':'Synthetic fixture only'},
        'read_inventory':[{'path':relative(p),'sha256':sha(p)} for p in [native,structure]],
        'structured_native_evidence':{'protocol.docx':relative(structure)},
        'render_artifacts':[dict(artifact,docx=relative(native),pdf=relative(pdf),pages=[dict(artifact['pages'][0],path=relative(page))],
            renderer_request_path=relative(renderer),renderer_request_sha256=sha(renderer))]}
    path=tmp_path/'inspection.json';path.write_text(json.dumps(request,indent=2));digest=sha(path)
    note={'observed':'Fixture relationship inspected in unit control only','location':'fixture location'}
    response={'request_sha256':digest,'status':'passed','material_defects_remaining':0,'fact_observations':{'study.title':note},
        'page_observations':{relative(page):note},'boundary_observations':{},'document_observations':{'protocol.docx':note},'cross_document_observation':note}
    audit={'auditor_id':'unit-only','inspection_evidence':{'request_path':relative(path),'request_sha256':digest,'units':[]}}
    return request,path,response,audit,[relative(p) for p in [path,tmp_path/'campaign-source.json',native,structure]],relative(page)


def unit_database(root,name,reads,images,response,audit):
    import sqlite3
    from owner_artifact_audit import sha
    state=root/name;state.mkdir()
    target=root/(name+'.response.json');target.write_text(json.dumps(response))
    calls=[];results=[]
    for path in reads:
        content=(root/path).read_text() if not path.endswith('.docx') else 'native projected fixture'
        lines=content.splitlines();i=str(len(calls));calls.append({'id':i,'function':{'name':'read_file','arguments':{'path':str(root/path)}}})
        results.append((i,'read_file',{'content':'\n'.join(str(n)+'|'+line for n,line in enumerate(lines,1)),'total_lines':len(lines)}))
    for path in images:
        i=str(len(calls));calls.append({'id':i,'function':{'name':'vision_analyze','arguments':{'image_url':str(root/path)}}});results.append((i,'vision_analyze',{'success':True}))
    i=str(len(calls));calls.append({'id':i,'function':{'name':'write_file','arguments':{'path':str(target),'content':target.read_text()}}});results.append((i,'write_file',{'verified':True}))
    con=sqlite3.connect(state/'state.db');con.execute('CREATE TABLE sessions(id TEXT,model TEXT)');con.execute('CREATE TABLE messages(session_id TEXT,role TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT,content TEXT)')
    identity='unit-only' if name=='one' else name
    con.execute('INSERT INTO sessions VALUES(?,?)',(identity,'gpt-6.1-sol'));con.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',(identity,'assistant',json.dumps(calls),None,None,None))
    for i,n,value in results:con.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',(identity,'tool',None,i,n,json.dumps(value)))
    con.commit();con.close()
    audit['inspection_evidence']['units'].append({'state_path':name,'response_path':target.name})


@pytest.mark.parametrize('mutation',['none','empty-document','list-document','missing-document','structure-alias','split-session'])
def test_complete_bound_audit_and_incomplete_controls(tmp_path,mutation):
    from owner_artifact_audit import sha
    request,path,response,audit,reads,page=full_fixture(tmp_path)
    if mutation=='empty-document':response['document_observations']={'protocol.docx':{}}
    if mutation=='list-document':response['document_observations']=['protocol.docx']
    if mutation=='missing-document':response.pop('document_observations')
    if mutation=='structure-alias':
        request['structured_native_evidence']={'protocol.docx':'campaign-source.json'};path.write_text(json.dumps(request));audit['inspection_evidence']['request_sha256']=sha(path);response['request_sha256']=sha(path)
    if mutation=='split-session':
        empty=dict(response,fact_observations={},page_observations={},document_observations={},cross_document_observation={})
        unit_database(tmp_path,'one',reads,[page],empty,audit)
        unit_database(tmp_path,'two',['inspection.json'],[],response,audit)
    else:unit_database(tmp_path,'one',reads,[page],response,audit)
    call=lambda:validate_owner_audit(tmp_path,{'source_sha256':'source-id'},audit,request['delivered_artifact_sha256'],set())
    if mutation=='none':assert call() is True
    else:
        with pytest.raises((ValueError,TypeError)):call()
