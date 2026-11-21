from datetime import timezone
from fastapi import APIRouter, Depends, Header, Response
from app.routes.dependencies import actor, runtime, paging, public_record
from app.schemas.requests import JobCreate, ClassificationReview
from app.services.catalog import paginate
from app.domain import Error, now, PIPELINE_VERSION, RULES_VERSION

router = APIRouter(prefix='/api/v1', tags=['Processing and immutable snapshot jobs'])


@router.get('/processing/configuration')
def configuration(identity=Depends(actor), rt=Depends(runtime)):
    return {'model_id': rt.config.model_id, 'configured': bool(rt.config.openai_api_key.get_secret_value()),
            'classification_confidence_threshold': rt.config.classification_confidence_threshold,
            'pipeline_version': PIPELINE_VERSION, 'rules_version': RULES_VERSION,
            'limits': {'max_pdf_bytes': rt.config.max_pdf_bytes, 'max_pdf_pages': rt.config.max_pdf_pages, 'model_max_calls': rt.config.model_max_calls}}


@router.get('/corpora/{id}/jobs')
def jobs(id: str, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    result = paginate(rt.catalog.related(identity, 'corpora', id, 'jobs'), **pagination)
    result['items'] = [rt.catalog.job_details(identity, job['id']) for job in result['items']]
    return public_record(result)


def accepted(job, response):
    response.headers['Idempotency-Key'] = job['idempotency_key']
    return {'job_id': job['id'], 'status': job['status'], 'status_url': '/api/v1/jobs/'+job['id']}


@router.post('/corpora/{id}/jobs', status_code=202, summary='Process/classify or validate/export a fixed revision snapshot')
def enqueue(id: str, body: JobCreate, response: Response, idempotency_key: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    return accepted(rt.jobs.enqueue(identity, id, body.model_dump(), idempotency_key), response)


@router.get('/jobs/{id}')
def job(id: str, identity=Depends(actor), rt=Depends(runtime)):
    return public_record(rt.catalog.job_details(identity, id))


@router.get('/jobs/{id}/items')
def items(id: str, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return public_record(paginate(rt.catalog.related(identity, 'jobs', id, 'job_items'), **pagination))


@router.post('/jobs/{id}/cancel')
def cancel(id: str, identity=Depends(actor), rt=Depends(runtime)):
    return public_record(rt.jobs.cancel(identity, id))


@router.post('/jobs/{id}/retry', status_code=202)
def retry(id: str, response: Response, idempotency_key: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    return accepted(rt.jobs.retry(identity, id, idempotency_key), response)


@router.post('/jobs/{id}/pause')
def pause(id: str, identity=Depends(actor), rt=Depends(runtime)):
    return public_record(rt.jobs.pause(identity, id))


@router.post('/jobs/{id}/resume')
def resume(id: str, identity=Depends(actor), rt=Depends(runtime)):
    return public_record(rt.jobs.resume(identity, id))


@router.get('/jobs/{id}/report')
def report(id: str, identity=Depends(actor), rt=Depends(runtime)):
    job = rt.catalog.job_details(identity, id)
    if job['result'].get('report'):
        return job['result']['report']
    if job['kind'] in ('process', 'classify') and job['status'] in ('succeeded', 'partially_succeeded', 'waiting_review', 'failed', 'blocked_external_configuration'):
        return public_record({'status': job['status'], 'items': rt.catalog.related(identity, 'jobs', id, 'job_items')})
    raise Error(409, 'not_ready', 'Report is not ready')


@router.get('/jobs/{id}/download', response_class=Response, responses={200:{'content':{'application/zip':{'schema':{'type':'string','format':'binary'}}}},409:{},410:{}})
def download(id: str, identity=Depends(actor), rt=Depends(runtime)):
    job = rt.catalog.get(identity, 'jobs', id)
    key = job['result'].get('storage_key')
    if not key or job['status'] != 'succeeded':
        raise Error(409, 'not_ready', 'Export is not ready')
    if job['expires_at'] and job['expires_at'].replace(tzinfo=timezone.utc) <= now():
        raise Error(410, 'export_expired', 'Export retention expired')
    return Response(rt.storage.get(key), media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="science-extract-{id}.zip"'})


@router.get('/jobs/{id}/passport')
def passport(id: str, identity=Depends(actor), rt=Depends(runtime)):
    result = rt.catalog.get(identity, 'jobs', id)['result']
    if 'passport' not in result:
        raise Error(409, 'not_ready', 'Passport is not ready')
    return result['passport']


@router.get('/documents/{id}/classifications')
def classifications(id: str, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    doc = rt.catalog.get(identity, 'documents', id)
    return {'current_revision_id': doc['classification_id'], **paginate(rt.catalog.related(identity, 'documents', id, 'classification_revisions'), **pagination)}


@router.post('/documents/{id}/classifications/review')
def review(id: str, body: ClassificationReview, identity=Depends(actor), rt=Depends(runtime)):
    return rt.jobs.review(identity, id, body.expected_revision, body.decision.model_dump(mode='json'), body.reason, body.replace_reviewed)
