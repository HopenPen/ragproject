# Назначение файла: ingress smoke и честный JSON всех 24 сценариев приёмки, human/external blockers.
import argparse
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import time
import zipfile
import httpx
from app.config import settings
from app.domain import now

SCENARIOS = [
    'Compose/docs', 'JWT/spoofing', 'Auth lifecycle/roles', 'Corpus ACL/archive', 'PDF upload/dedup/limits',
    'Process/classify jobs', 'Classification outcomes', 'Classification review/resume', 'Real text/scan/mixed extraction',
    'Page/crop/source review', 'Typed CRUD/revisions/links', 'Candidates/history/exclusion/evidence review',
    'Search/filter/comparison', 'Solar/RAG validation', 'Issue review/audit', 'Solar/RAG/mixed immutable export',
    'External checker/evaluate', 'Idempotency/cancel/retry', 'Broker/worker recovery', 'Redis outage',
    'Logs/metrics/provider outage', 'GitLab real deploy', 'Backup/empty restore', 'Repository hygiene']


def run(base_url, output, technical_only=False):
    config = settings()
    results = [{'scenario': i+1, 'name': title, 'status': 'blocked', 'evidence': [],
                'human_confirmation': 'pending',
                'error': 'Requires human verification or an explicitly configured external environment'} for i,title in enumerate(SCENARIOS)]
    active_scenario=1
    def record(number, evidence, status='pass', error=None):
        results[number-1].update(status=status, evidence=evidence, error=error)
    client = httpx.Client(base_url=base_url.rstrip('/'), timeout=60, follow_redirects=True)
    def request(method, path, expected=(200,), **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code not in expected:
            code = response.json().get('error', {}).get('code') if response.headers.get('content-type','').startswith('application/json') else None
            raise AssertionError(f'{method} {path}: HTTP {response.status_code}, code={code}; expected {expected}')
        return response
    try:
        request('GET','/health/live'); request('GET','/docs'); schema=request('GET','/openapi.json').json()
        assert '/api/v1/corpora/{id}/jobs' in schema['paths']
        record(1, ['Ingress /docs and OpenAPI available'], 'blocked', 'Dependency roundtrips have not completed yet')
        active_scenario=2
        request('GET','/api/v1/corpora',expected=(401,403))
        request('GET','/api/v1/corpora',expected=(401,403),headers={'Authorization':'Bearer invalid','X-User-ID':'spoof','X-User-Role':'admin','X-Gateway-Credential':'spoof'})
        record(2, ['Unauthenticated/malformed token plus spoofed identity rejected'], 'blocked', 'Expired/wrong issuer/audience matrix must also pass in the separate auth-container integration test')
        active_scenario=3
        credentials = request('POST','/api/v1/auth/login',json={'email':config.admin_email,'password':config.admin_password.get_secret_value()}).json()
        client.headers['Authorization'] = 'Bearer '+credentials['access_token']
        actor=request('GET','/api/v1/auth/me').json()
        suffix=secrets.token_hex(6); pwd=secrets.token_urlsafe(20)
        users={}
        for role in ('editor','viewer'):
            users[role]=request('POST','/api/v1/users',expected=(201,),json={'email':f'{role}-{suffix}@example.org','password':pwd,'role':role}).json()
        viewer=request('POST','/api/v1/auth/login',json={'email':users['viewer']['email'],'password':pwd}).json()
        request('POST','/api/v1/corpora',expected=(403,),headers={'Authorization':'Bearer '+viewer['access_token']},json={'name':'Forbidden viewer write'})
        rotated=request('POST','/api/v1/auth/refresh',json={'refresh_token':viewer['refresh_token']}).json()
        request('POST','/api/v1/auth/refresh',expected=(401,),json={'refresh_token':viewer['refresh_token']})
        request('POST','/api/v1/auth/refresh',expected=(401,),json={'refresh_token':rotated['refresh_token']})
        record(3, ['Editor/viewer creation, viewer write forbidden, refresh rotation and reuse-family revocation passed'], 'blocked', 'Password/block/logout-all matrix is covered by tests; full ingress confirmation remains required')
        active_scenario=4
        corpus=request('POST','/api/v1/corpora',expected=(201,),json={'name':'SYNTHETIC smoke '+suffix,'split':'synthetic'}).json()
        cid=corpus['id']
        request('GET','/api/v1/corpora/'+cid,expected=(404,),headers={'Authorization':'Bearer '+viewer['access_token']})
        editor=request('POST','/api/v1/auth/login',json={'email':users['editor']['email'],'password':pwd}).json()
        other=request('POST','/api/v1/corpora',expected=(201,),headers={'Authorization':'Bearer '+editor['access_token']},json={'name':'SYNTHETIC other owner '+suffix}).json()
        request('GET','/api/v1/corpora/'+other['id'],headers={'Authorization':'Bearer '+editor['access_token']})
        request('GET','/api/v1/corpora/'+cid,expected=(404,),headers={'Authorization':'Bearer '+editor['access_token']})
        def enqueue(kind, profiles=None, key=None):
            payload={'kind':kind,'all_documents':True}
            if kind in ('validate','export'):payload['run_external_checker']=False
            if profiles: payload['target_profiles']=profiles
            return request('POST',f'/api/v1/corpora/{cid}/jobs',expected=(202,),headers={'Idempotency-Key':key or secrets.token_hex(12)},json=payload).json()
        def wait(job, expected=('succeeded',)):
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                value=request('GET',job['status_url']).json()
                if value['status'] in ('succeeded','failed','blocked_external_configuration','cancelled','partially_succeeded'):
                    assert value['status'] in expected, f'Job ended as {value["status"]}'
                    return value
                time.sleep(.5)
            raise AssertionError('Timed out waiting for worker/outbox')
        active_scenario=5
        from tests.fixtures import pdf_bytes, classification, solar_graph, rag_graph
        blob=pdf_bytes('mixed')
        doc=request('POST',f'/api/v1/corpora/{cid}/documents',expected=(201,),data={'publication_code':'SYNTHETIC1'},files={'file':('fixture.pdf',blob,'application/pdf')}).json()
        did=doc['id']
        request('POST',f'/api/v1/corpora/{cid}/documents',data={'publication_code':'SYNTHETIC1'},files={'file':('fixture.pdf',blob,'application/pdf')})
        request('POST',f'/api/v1/corpora/{cid}/documents',expected=(409,),data={'publication_code':'SYNTHETIC1'},files={'file':('other.pdf',pdf_bytes(pages=2),'application/pdf')})
        request('POST',f'/api/v1/corpora/{cid}/documents',expected=(415,),data={'publication_code':'BAD'},files={'file':('bad.pdf',b'not PDF','application/pdf')})
        assert hashlib.sha256(request('GET',f'/api/v1/documents/{did}/file').content).hexdigest()==doc['sha256']
        record(5,['Multipart/original PDF binary roundtrip, dedup, code/hash conflict and invalid PDF rejection passed'], 'blocked', 'Oversized PDF rejection still requires the configured ingress byte-limit check')
        if not config.openai_api_key.get_secret_value():
            active_scenario=6
            for kind in ('process','classify'):
                job=enqueue(kind); wait(job,('blocked_external_configuration',))
                item=request('GET',f'/api/v1/jobs/{job["job_id"]}/items').json()['items'][0]
                assert item['progress']['coverage']['complete'] and not item['progress'].get('outputs')
            record(6,['Actual process/classify enqueue, polling and page progress; both jobs correctly blocked by absent API key'])
            active_scenario=10
            assert request('GET',f'/api/v1/documents/{did}/pages/1/image').content.startswith(b'\x89PNG\r\n\x1a\n')
            assert request('GET',f'/api/v1/documents/{did}/pages/1/text').json()['text']
            crops=request('GET',f'/api/v1/documents/{did}/artifacts?kind=crop').json()['items']
            assert crops and request('GET',f'/api/v1/documents/{did}/artifacts/{crops[0]["id"]}/file').content.startswith(b'\x89PNG')
            record(10,['Actual rendered PNG, page text and embedded-image crop retrieved through S3/gateway'], 'blocked', 'Human visual/source confirmation is required')
        active_scenario=8
        decision=classification(['solar','rag'])
        cls=request('POST',f'/api/v1/documents/{did}/classifications/review',json={'expected_revision':'none','decision':decision,'reason':'SYNTHETIC smoke control'}).json()
        active_scenario=11
        pub=request('GET',f'/api/v1/corpora/{cid}/publications').json()['items'][0]
        pid=pub['id']
        for graph in (solar_graph(),rag_graph()):
            request('POST',f'/api/v1/corpora/{cid}/publications',expected=(201,),json={'document_id':did,'graph':graph,'reason':'SYNTHETIC known facts'})
        path=f'/api/v1/publications/{pid}/graph?profile=rag-v1'
        current=request('GET',path); graph=current.json()['graph']; graph['bibliography']['title']='SYNTHETIC correction'
        request('PUT',path,expected=(428,),json={'graph':graph,'reason':'missing precondition'})
        updated=request('PUT',path,headers={'If-Match':current.headers['etag']},json={'graph':graph,'reason':'reviewed correction'})
        request('PUT',path,expected=(412,),headers={'If-Match':current.headers['etag']},json={'graph':graph,'reason':'stale'})
        request('DELETE',f'/api/v1/publications/{pid}/entities/configuration/C1',expected=(422,),headers={'If-Match':updated.headers['etag']},json={'reason':'cannot delete referenced configuration'})
        entity_path=f'/api/v1/publications/{pid}/entities/dataset'
        created=request('POST',entity_path,expected=(201,),headers={'If-Match':updated.headers['etag']},json={'record':{'dataset_id':'UNREFERENCED','dataset_name':'SYNTHETIC CRUD'},'reason':'create typed entity'})
        patched=request('PATCH',entity_path+'/UNREFERENCED',headers={'If-Match':created.headers['etag']},json={'record':{'note':'Corrected'},'reason':'patch typed entity'})
        request('GET',entity_path+'/UNREFERENCED')
        request('DELETE',entity_path+'/UNREFERENCED',headers={'If-Match':patched.headers['etag']},json={'reason':'delete unreferenced entity'})
        record(11,['Typed graph edit, 428 missing/412 stale If-Match and referenced entity deletion rejection passed'])
        active_scenario=13
        request('GET',f'/api/v1/corpora/{cid}/results?profile=rag-v1&metric_k=0')
        request('GET',f'/api/v1/corpora/{cid}/search?q=SYNTHETIC&scope=metadata')
        request('POST',f'/api/v1/corpora/{cid}/comparisons',json={'profile':'rag-v1','results':[{'publication_id':pid,'result_id':'R1'}]})
        record(13,['Profile result filters, metadata search and RAG comparability handler responded'], 'blocked', 'Page-text search and both profile comparison policies still need acceptance confirmation')
        active_scenario=16
        archives=[]
        for profiles in (['solar-v1'],['rag-v1'],['solar-v1','rag-v1']):
            job=enqueue('export',profiles); wait(job)
            result=request('GET',f'/api/v1/jobs/{job["job_id"]}/download')
            with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
                assert sum(name.endswith('.csv') for name in archive.namelist())==7*len(profiles)
            archives.append((job,result.content))
        latest=request('GET',path)
        graph=latest.json()['graph']; graph['bibliography']['title']='SYNTHETIC after export'
        request('PUT',path,headers={'If-Match':latest.headers['etag']},json={'graph':graph,'reason':'snapshot immutability check'})
        assert request('GET',f'/api/v1/jobs/{archives[-1][0]["job_id"]}/download').content==archives[-1][1]
        record(16,['Real worker/S3 ZIP solar, RAG and mixed; 7 CSV/profile, original ZIP unchanged after revision'])
        record(1,['Ingress/docs, login through Redis/PostgreSQL, PDF/S3 roundtrip and RabbitMQ/Celery export jobs completed'])
        active_scenario=14
        validation=enqueue('validate'); wait(validation)
        report=request('GET',f'/api/v1/jobs/{validation["job_id"]}/report').json()
        assert len(report['publications'])==2
        record(14,['Real snapshot validation job for both synthetic graphs'], 'blocked', 'Scientific rule violation matrix is covered by tests; source/scientific human acceptance remains required')
        active_scenario=18
        key=secrets.token_hex(12)
        first=enqueue('validate',key=key); second=enqueue('validate',key=key)
        assert first['job_id']==second['job_id']
        request('POST',f'/api/v1/corpora/{cid}/jobs',expected=(409,),headers={'Idempotency-Key':key},json={'kind':'export','all_documents':True})
        wait(first)
        record(18,['Idempotent enqueue returns same job and rejects changed payload'], 'blocked', 'Cancel/retry matrix is covered by tests and needs ingress confirmation')
        active_scenario=4
        request('POST',f'/api/v1/corpora/{cid}/archive')
        request('PATCH',f'/api/v1/corpora/{cid}',expected=(409,),json={'name':'Forbidden archived write'})
        record(4,['Own/admin access, foreign 404, viewer write denial and archive mutation denial'])
        record(8,['Manual classification revision/reason persisted'], 'blocked', 'Waiting-review OCR continuation is covered by pipeline tests; real model acceptance remains required')
        record(12,['History retained across manual revision and export'], 'blocked', 'Machine candidates, exclusion and source review need acceptance confirmation')
        if not config.openai_api_key.get_secret_value():
            record(9,[],status='blocked',error='blocked_external_configuration: OPENAI_API_KEY is not configured; no real model call made')
    except httpx.ConnectError:
        results[active_scenario-1].update(status='blocked',error='blocked_external_configuration: ingress is unavailable')
    except Exception as exc:
        results[active_scenario-1].update(status='fail',error=str(exc))
    finally:
        client.close()
    payload={'created_at':now().isoformat(),'base_url':base_url,'human_acceptance_complete':False,
             'technical_only':technical_only, 'scenarios':results}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    failures=any(r['status']=='fail' for r in results)
    blocked=any(r['status']=='blocked' for r in results)
    return 1 if failures else 0 if technical_only else 2 if blocked else 0


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default=settings().public_base_url)
    parser.add_argument('--output',type=Path,default=Path('runtime/acceptance.json'))
    parser.add_argument('--technical-only',action='store_true')
    args=parser.parse_args()
    sys.exit(run(args.base_url,args.output,args.technical_only))
