from fastapi import APIRouter, Depends, Form, File, UploadFile, Response, Query
from app.routes.dependencies import actor, runtime, paging, public_record
from app.schemas.requests import CorpusCreate, CorpusPatch, DocumentPatch
from app.services.catalog import paginate
from app.domain import Error

router = APIRouter(prefix='/api/v1', tags=['Corpora and PDF sources'])


@router.delete('/corpora/{id}', status_code=204)
def delete_corpus(id: str, identity=Depends(actor), rt=Depends(runtime)):
    from app.services.deletion import Deletions
    Deletions(rt.uow).remove(identity, corpus_id=id)
    return Response(status_code=204)


@router.delete('/documents/{id}', status_code=204)
def delete_document(id: str, identity=Depends(actor), rt=Depends(runtime)):
    from app.services.deletion import Deletions
    Deletions(rt.uow).remove(identity, document_id=id)
    return Response(status_code=204)


@router.get('/corpora')
def corpora(identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return paginate(rt.documents.corpora(identity), **pagination)


@router.post('/corpora', status_code=201)
def create_corpus(body: CorpusCreate, identity=Depends(actor), rt=Depends(runtime)):
    return rt.documents.create_corpus(identity, body.model_dump())


@router.get('/corpora/{id}')
def corpus(id: str, identity=Depends(actor), rt=Depends(runtime)):
    return rt.documents.corpus_details(identity, id)


@router.patch('/corpora/{id}')
def patch_corpus(id: str, body: CorpusPatch, identity=Depends(actor), rt=Depends(runtime)):
    return rt.documents.patch_corpus(identity, id, body.model_dump(exclude_none=True))


@router.post('/corpora/{id}/archive')
def archive(id: str, identity=Depends(actor), rt=Depends(runtime)):
    return rt.documents.patch_corpus(identity, id, {'archived': True})


@router.get('/corpora/{id}/documents')
def documents(id: str, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return public_record(paginate(rt.catalog.related(identity, 'corpora', id, 'documents'), **pagination))


@router.post('/corpora/{id}/documents', status_code=201, summary='Upload PDF with an explicit publication code; duplicate is 200')
def upload(id: str, response: Response, publication_code: str = Form(...), file: UploadFile = File(...), identity=Depends(actor), rt=Depends(runtime)):
    rt.catalog.get(identity, 'corpora', id, True)
    data = file.file.read(rt.config.max_pdf_bytes+1)
    result, created = rt.documents.upload(identity, id, publication_code, (file.filename or 'article.pdf').replace('\\', '/').split('/')[-1], data)
    response.status_code = 201 if created else 200
    return public_record(result)


@router.get('/documents/{id}')
def document(id: str, identity=Depends(actor), rt=Depends(runtime)):
    return public_record(rt.catalog.get(identity, 'documents', id))


@router.patch('/documents/{id}')
def patch_document(id: str, body: DocumentPatch, identity=Depends(actor), rt=Depends(runtime)):
    return public_record(rt.catalog.patch_document(identity, id, body.model_dump(exclude_none=True)))


@router.get('/documents/{id}/file', response_class=Response, responses={200:{'content':{'application/pdf':{'schema':{'type':'string','format':'binary'}}}}})
def original(id: str, identity=Depends(actor), rt=Depends(runtime)):
    doc = rt.catalog.get(identity, 'documents', id)
    return Response(rt.storage.get(doc['storage_key']), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{doc["publication_code"]}.pdf"'})


@router.get('/documents/{id}/pages')
def pages(id: str, run: str | None = None, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    rows = rt.catalog.related(identity, 'documents', id, 'pages', run_id=run)
    return public_record(paginate(rows, **pagination))


def get_page(rt, identity, id, page):
    rows = rt.catalog.related(identity, 'documents', id, 'pages', number=page)
    if not rows:
        raise Error(404, 'not_found', 'Page not found')
    return rows[0]


@router.get('/documents/{id}/pages/{page}/image', response_class=Response, responses={200:{'content':{'image/png':{'schema':{'type':'string','format':'binary'}}}},409:{}})
def image(id: str, page: int, identity=Depends(actor), rt=Depends(runtime)):
    p = get_page(rt, identity, id, page)
    if not p['image_key']:
        raise Error(409, 'not_ready', 'Page has not been rendered')
    return Response(rt.storage.get(p['image_key']), media_type='image/png')


@router.get('/documents/{id}/pages/{page}/text')
def text(id: str, page: int, identity=Depends(actor), rt=Depends(runtime)):
    return public_record(get_page(rt, identity, id, page))


@router.get('/documents/{id}/artifacts')
def artifacts(id: str, page: int | None = None, run: str | None = None, kind: str | None = None,
              identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return public_record(paginate(rt.catalog.related(identity, 'documents', id, 'artifacts', page=page, run_id=run, kind=kind), **pagination))


@router.get('/documents/{id}/artifacts/{artifact_id}/file', response_class=Response)
def artifact_file(id: str, artifact_id: str, identity=Depends(actor), rt=Depends(runtime)):
    rt.catalog.get(identity, 'documents', id)
    obj = rt.catalog.get(identity, 'artifacts', artifact_id)
    if obj['document_id'] != id:
        raise Error(404, 'not_found', 'Artifact not found')
    return Response(rt.storage.get(obj['storage_key']), media_type=obj['content_type'])
