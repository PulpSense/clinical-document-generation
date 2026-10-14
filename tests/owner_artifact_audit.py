"""Owner-only admission proof. Access evidence never substitutes for AI judgment."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def confined(root,name):
    p=root/str(name)
    require(not p.is_symlink() and p.resolve().is_relative_to(root.resolve()) and p.is_file(),'Foreign audit inspection path')
    return p


def runtime_access(root,state):
    database=confined(root,str((state/'state.db').relative_to(root)))
    con=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=1)
    try:
        sessions=con.execute('SELECT id,model FROM sessions').fetchall()
        require(len(sessions)==1 and all(isinstance(s,str) and s.strip() for s in sessions[0]),'Missing actual audit identity')
        session,model=sessions[0];calls={};duplicates=set()
        for (raw,) in con.execute("SELECT tool_calls FROM messages WHERE session_id=? AND role='assistant' AND tool_calls IS NOT NULL",(session,)):
            for call in json.loads(raw):
                f=call.get('function',call);args=f.get('arguments',{})
                if isinstance(args,str):args=json.loads(args)
                if call['id'] in calls:duplicates.add(call['id'])
                calls[call['id']]=(f.get('name'),args)
        rows=con.execute("SELECT tool_call_id,tool_name,content FROM messages WHERE session_id=? AND role='tool'",(session,)).fetchall()
        counts={}
        for i,_,_ in rows:counts[i]=counts.get(i,0)+1
        reads={};images=set();writes={}
        for i,name,raw in rows:
            if i in duplicates or counts[i]!=1 or i not in calls:continue
            expected,args=calls[i]
            if name!=expected:continue
            try:value=json.loads(raw)
            except (ValueError,TypeError):
                value={'success':True} if name=='vision_analyze' and isinstance(raw,str) and raw.startswith('Image loaded into your context — you can see it natively now. Use your built-in vision to answer the user.') else {}
            if not isinstance(value,dict) or 'error' in value or value.get('success') is False:continue
            namearg=args.get('image_url') if name=='vision_analyze' else args.get('path')
            if not namearg:continue
            p=Path(namearg)
            if not p.is_absolute():p=root/p
            if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or not p.is_file():continue
            key=p.resolve().relative_to(root.resolve()).as_posix()
            if name=='vision_analyze' and args.get('region') is None and value.get('success') is True:images.add(key)
            if name=='read_file' and isinstance(value.get('content'),str) and type(value.get('total_lines')) is int and value.get('truncated_lines') is not True:
                total=value['total_lines'];lines=[int(m.group(1)) for m in re.finditer(r'(?m)^(\d+)\|',value['content'])]
                offset=args.get('offset',1);limit=args.get('limit',2000)
                if type(offset)!=int or type(limit)!=int or not lines or lines!=sorted(set(lines)) or lines[0]!=offset or lines[-1]>min(total,offset+limit-1):continue
                item=reads.setdefault(key,{'total':total,'lines':set(),'consistent':True})
                item['consistent'] &= item['total']==total
                item['lines'].update(lines)
            if name=='write_file' and value.get('verified') is True and isinstance(args.get('content'),str):
                writes[key]=hashlib.sha256(args['content'].encode()).hexdigest()
        complete={k for k,v in reads.items() if v['consistent'] and v['total']>0 and len(v['lines'])==v['total']}
        return session,model,complete,images,writes
    finally:con.close()


def native_structure(native):
    """Reproducible text/relationship/structural surfaces, not a quality judgment."""
    import zipfile
    from lxml import etree
    parts={}
    if native.suffix=='.docx':
        with zipfile.ZipFile(native) as z:
            for name in z.namelist():
                if name.startswith('word/') and name.endswith('.xml') and any(s in name for s in ('document.xml','header','footer','footnotes','endnotes','comments')):
                    parts[name]=z.read(name)
    else:parts[native.name]=native.read_bytes()
    records=[]
    for name,raw in sorted(parts.items()):
        tree=etree.fromstring(raw,parser=etree.XMLParser(resolve_entities=False,no_network=True)).getroottree()
        for node in tree.getroot().iter():
            tag=etree.QName(node).localname
            if native.suffix=='.docx' and tag not in {'p','tbl','tr','tc','t','instrText','delText','tab','br','gridSpan','vMerge','hMerge','txbxContent','hyperlink','fldChar','bookmarkStart','bookmarkEnd'}:continue
            text=node.text or ''
            records.append({'location':name+':'+tree.getpath(node),'tag':node.tag,'attributes':dict(node.attrib),
                'text_chunks':[text[n:n+120] for n in range(0,len(text),120)]})
    return {'schema_version':'owner-native-structure/v1','native_sha256':sha(native),
        'part_sha256':{n:hashlib.sha256(raw).hexdigest() for n,raw in sorted(parts.items())},'records':records}


def validate_owner_audit(run,assignment,audit,delivered,authors):
    run=Path(run).resolve()
    inspection=audit.get('inspection_evidence')
    require(isinstance(inspection,dict),'Missing genuine audit inspection evidence')
    request_path=confined(run,inspection['request_path'])
    require(sha(request_path)==inspection['request_sha256'],'Changed audit inspection request')
    request=json.loads(request_path.read_text())
    require(request.get('schema_version')=='owner-artifact-inspection/v1','Unsupported audit inspection request')
    require(request['source_sha256']==assignment['source_sha256'] and request['delivered_artifact_sha256']==delivered,'Foreign audit scope')
    source=confined(run,'campaign-source.json')
    require(json.loads(source.read_text())==request['source'],'Foreign audit source')
    def leaves(value,prefix=''):
        if isinstance(value,dict):
            return {k:v for key,child in value.items() for k,v in leaves(child,(prefix+'.' if prefix else '')+key).items()}
        if isinstance(value,list):
            return {k:v for n,child in enumerate(value) for k,v in leaves(child,prefix+'['+str(n)+']').items()}
        return {prefix:value} if value not in ('',None) else {}
    require(request['expected_facts']==leaves(request['source']),'Audit omits expected source facts')
    required_reads={request_path.relative_to(run).as_posix(),'campaign-source.json'}
    for row in request['read_inventory']:
        p=confined(run,row['path']);require(sha(p)==row['sha256'],'Changed audit read inventory')
        required_reads.add(row['path'])
    # Every delivered native must be read; structured evidence must also be inspected.
    require({str(Path('output')/name) for name in delivered}<=required_reads,'Missing native inspection scope')
    structures=request.get('structured_native_evidence')
    require(isinstance(structures,dict) and set(structures)==set(delivered),'Missing structured native/XML evidence')
    for name,path in structures.items():
        require(path not in {'campaign-source.json',request_path.relative_to(run).as_posix()} and path in required_reads,'Foreign structured native evidence')
        native=confined(run,'output/'+name)
        require(sha(native)==delivered[name] and json.loads(confined(run,path).read_text())==native_structure(native),'Unbound native structure evidence')
    expected_pages={};native_names=set();boundaries=set()
    for artifact in request['render_artifacts']:
        p=confined(run,artifact['docx']);require(sha(p)==artifact['docx_sha256'] and p.name in delivered and delivered[p.name]==artifact['docx_sha256'],'Foreign rendered native')
        pdf=confined(run,artifact['pdf']);require(sha(pdf)==artifact['pdf_sha256'],'Changed audit PDF')
        native_names.add(p.name)
        require(len(artifact['pages'])==artifact['page_count'] and artifact['page_count']>0,'Incomplete audit page scope')
        for n,row in enumerate(artifact['pages'],1):
            require(row['page']==n and sha(confined(run,row['path']))==row['sha256'],'Changed or unordered audit page')
            require(row['path'] not in expected_pages,'Duplicate audit page');expected_pages[row['path']]=row['sha256']
            if n>1:boundaries.add(artifact['pages'][n-2]['path']+' -> '+row['path'])
    require(native_names=={n for n in delivered if n.endswith('.docx')},'Incomplete rendered document inventory')
    require({r['path'] for r in request['read_inventory'] if r['path'].startswith('output/')}=={'output/'+n for n in delivered},'Incomplete final native/XML inventory')
    # Match page scope to actual renderer evidence, not a reviewer-provided subset.
    for artifact in request['render_artifacts']:
        renderer=confined(run,artifact['renderer_request_path'])
        require(sha(renderer)==artifact['renderer_request_sha256'],'Changed renderer request')
        bound=json.loads(renderer.read_text())
        matches=[a for a in bound['artifacts'] if a.get('docx_sha256')==artifact['docx_sha256'] and a.get('pdf_sha256')==artifact['pdf_sha256']]
        require(len(matches)==1,'Missing exact renderer binding')
        revision=renderer.parents[2]
        actual={str((revision/r['path']).relative_to(run)):r['sha256'] for r in matches[0]['pages']}
        require(actual=={r['path']:r['sha256'] for r in artifact['pages']},'Audit excludes renderer pages')
    reads=set();images=set();fact_notes={};page_notes={};boundary_notes={};documents=set();identities=set()
    for unit in inspection['units']:
        state=run/unit['state_path']
        require(state.is_dir() and not state.is_symlink() and state.resolve().is_relative_to(run),'Foreign auditor state')
        identity,model,r,i,w=runtime_access(run,state)
        require(identity not in authors and identity not in identities,'Nonindependent or duplicate audit session')
        require(model in {'gpt-6.1-sol','openai-codex/gpt-6.1-sol'},'Unexpected audit model')
        identities.add(identity)
        response=confined(run,unit['response_path'])
        require(w.get(unit['response_path'])==sha(response),'No verified actual audit checkpoint write')
        data=json.loads(response.read_text())
        require(data['request_sha256']==inspection['request_sha256'] and data['status']=='passed' and data['material_defects_remaining']==0,'Unpassed or foreign audit judgment')
        reads.update(r);images.update(i)
        require(request_path.relative_to(run).as_posix() in r,'Auditor did not inspect its bound request')
        if data.get('fact_observations') or data.get('document_observations') or data.get('cross_document_observation'):
            require(required_reads<=r,'Judgment session lacks complete native/source/structure access')
        for page in data.get('page_observations',{}):
            require(page in i,'Page judgment session did not inspect its image')
        for boundary in data.get('boundary_observations',{}):
            require(set(boundary.split(' -> '))<=i,'Boundary judgment session lacks both images')
        for name in data.get('document_observations',{}):
            pages={row['path'] for a in request['render_artifacts'] if Path(a['docx']).name==name for row in a['pages']}
            require(pages<=i,'Document judgment session lacks whole-document image access')
        if data.get('cross_document_observation'):
            note=data['cross_document_observation']
            require(isinstance(note,dict) and bool(note.get('observed')) and bool(note.get('location')),'Missing cross-document judgment')
            documents.add('cross-document')
        for bucket,target in [('fact_observations',fact_notes),('page_observations',page_notes),('boundary_observations',boundary_notes)]:
            require(isinstance(data.get(bucket,{}),dict),'Malformed observation scope')
            for key,note in data.get(bucket,{}).items():
                require(isinstance(note,dict) and bool(note.get('observed')) and bool(note.get('location')),'Unlocalized audit judgment')
                require(key not in target,'Duplicate audit judgment');target[key]=note
        docnotes=data.get('document_observations',{})
        require(isinstance(docnotes,dict),'Malformed document observations')
        for name,note in docnotes.items():
            require(name in native_names and isinstance(note,dict) and bool(note.get('observed')) and bool(note.get('location')),'Missing whole-document judgment')
            require(name not in documents,'Duplicate document judgment');documents.add(name)
    require(required_reads<=reads and set(expected_pages)<=images,'Incomplete genuine native/image inspection coverage')
    require(set(request['expected_facts'])==set(fact_notes),'Incomplete expected-fact judgments')
    require(set(expected_pages)==set(page_notes) and boundaries==set(boundary_notes),'Incomplete page/boundary judgments')
    require(native_names<=documents and 'cross-document' in documents,'Incomplete whole-document/cross-document judgments')
    require(audit.get('auditor_id') in identities,'Audit auditor identity is selfclaimed')
    return True
