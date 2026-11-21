from typing import Literal
from fastapi import APIRouter, Depends, Header, Query, Response
from app.routes.dependencies import actor, runtime, paging
from app.schemas.requests import PublicationCreate, GraphWrite, MetadataPatch, Reason, Review, EntityWrite, Comparison
from app.schemas.graphs import Evidence
from app.domain import Error, PROFILES
from app.profiles import ENTITIES, GRAPHS, passport, rules
from app.services.catalog import paginate

Profile = Literal['solar-v1', 'rag-v1']
router = APIRouter(prefix='/api/v1', tags=['Scientific catalog and review'])


def etag(response, result):
    response.headers['ETag'] = '"'+result['revision_id']+'"'
    return result


@router.get('/corpora/{id}/publications')
def publications(id: str, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return paginate(rt.catalog.related(identity, 'corpora', id, 'publications'), **pagination)


@router.post('/corpora/{id}/publications', status_code=201)
def create(id: str, body: PublicationCreate, response: Response, identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.create(identity, id, body.document_id, body.graph.model_dump(mode='json'), body.reason))


@router.get('/publications/{id}')
def publication(id: str, identity=Depends(actor), rt=Depends(runtime)):
    pub = rt.catalog.get(identity, 'publications', id)
    revisions = rt.catalog.related(identity, 'publications', id, 'publication_revisions')
    return {**pub, 'profiles': [{'domain_profile': r['profile'], 'revision_id': r['id'], 'bibliography': r['graph']['bibliography'], 'scope': r['graph']['scope']} for r in revisions if r['id'] in pub['current'].values()]}


@router.patch('/publications/{id}')
def metadata(id: str, body: MetadataPatch, response: Response, profile: Profile | None = None, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    def change(graph):
        for field in ('bibliography', 'scope'):
            value = getattr(body, field)
            if value is not None:
                graph[field] = {**graph[field], **value.model_dump(exclude_unset=True, mode='json')}
    return etag(response, rt.catalog.mutate(identity, id, profile, if_match, body.reason, change))


@router.get('/publications/{id}/graph')
def graph(id: str, response: Response, profile: Profile | None = None, revision: str | None = None, identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.read(identity, id, profile, revision))


@router.put('/publications/{id}/graph', summary='Replace typed graph with If-Match revision and correction reason', responses={412: {}, 422: {}, 428: {}})
def replace(id: str, body: GraphWrite, response: Response, profile: Profile | None = None, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.mutate(identity, id, profile, if_match, body.reason, lambda g: body.graph.model_dump(mode='json')))


@router.post('/publications/{id}/exclude')
def exclude(id: str, body: Reason, response: Response, profile: Profile | None = None, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    def change(g):
        return GRAPHS[g['domain_profile']](domain_profile=g['domain_profile'], bibliography=g['bibliography'],
            scope={'in_scope': False, 'exclusion_reason': body.reason or 'Исключено пользователем'}, evidence=g['evidence'] and [e for e in g['evidence'] if e['entity_id'] is None]).model_dump(mode='json')
    return etag(response, rt.catalog.mutate(identity, id, profile, if_match, body.reason, change))


@router.get('/publications/{id}/versions')
def versions(id: str, profile: Profile | None = None, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    pub = rt.catalog.get(identity, 'publications', id)
    rows = rt.catalog.related(identity, 'publications', id, 'publication_revisions', profile=profile)
    return paginate([{**r, 'domain_profile': r['profile'], 'revision_id': r['id'], 'active': r['id'] in pub['current'].values()} for r in rows], **pagination)


@router.post('/publications/{id}/versions/{revision_id}/activate')
def activate(id: str, revision_id: str, body: Reason, response: Response, profile: Profile, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.activate(identity, id, revision_id, profile, if_match, body.reason))


@router.get('/publications/{id}/audit')
def audit(id: str, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return paginate(rt.catalog.related(identity, 'publications', id, 'audit_entries'), **pagination)


@router.get('/publications/{id}/evidence')
def evidence(id: str, response: Response, profile: Profile | None = None, revision: str | None = None, entity: str | None = None,
             field: str | None = None, page: int | None = None, review: str | None = None, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    result = rt.catalog.read(identity, id, profile, revision)
    rows = [e for e in result['graph']['evidence'] if all(v is None or e[k] == v for k,v in {'entity_id': entity, 'field_path': field, 'source_page': page, 'review': review}.items())]
    return etag(response, {k:v for k,v in result.items() if k != 'graph'} | paginate(rows, **pagination))


@router.post('/publications/{id}/evidence', status_code=201)
def add_evidence(id: str, body: Evidence, response: Response, reason: str = Query(''), profile: Profile | None = None,
                 if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    def change(g):
        g['evidence'].append(body.model_dump(mode='json'))
    return etag(response, rt.catalog.mutate(identity, id, profile, if_match, reason, change))


@router.post('/publications/{id}/evidence/{evidence_id}/review')
def review_source(id: str, evidence_id: str, body: Review, response: Response, profile: Profile | None = None,
                  if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    if body.review not in ('confirmed', 'rejected'):
        raise Error(422, 'invalid_review', 'Evidence review is confirmed/rejected')
    def change(g):
        row = next((e for e in g['evidence'] if e['evidence_id'] == evidence_id), None)
        if row is None:
            raise Error(404, 'not_found', 'Evidence not found')
        row.update(review=body.review, review_reason=body.reason)
    return etag(response, rt.catalog.mutate(identity, id, profile, if_match, body.reason, change))


@router.get('/publications/{id}/entities/{entity_type}')
def entities(id: str, entity_type: str, response: Response, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    result = rt.catalog.entity(identity, id, entity_type)
    rows = result.pop('items')
    return etag(response, result | paginate(rows, **pagination))


@router.post('/publications/{id}/entities/{entity_type}', status_code=201)
def add_entity(id: str, entity_type: str, body: EntityWrite, response: Response, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.entity(identity, id, entity_type, operation='create', record=body.record, expected=if_match, reason=body.reason))


@router.get('/publications/{id}/entities/{entity_type}/{entity_id}')
def entity(id: str, entity_type: str, entity_id: str, response: Response, identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.entity(identity, id, entity_type, entity_id))


@router.patch('/publications/{id}/entities/{entity_type}/{entity_id}')
def patch_entity(id: str, entity_type: str, entity_id: str, body: EntityWrite, response: Response, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.entity(identity, id, entity_type, entity_id, 'patch', body.record, if_match, body.reason))


@router.delete('/publications/{id}/entities/{entity_type}/{entity_id}')
def delete_entity(id: str, entity_type: str, entity_id: str, body: Reason, response: Response, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    return etag(response, rt.catalog.entity(identity, id, entity_type, entity_id, 'delete', expected=if_match, reason=body.reason))


@router.get('/corpora/{id}/results')
def results(id: str, profile: Profile | None = None, metric: str | None = None, year: int | None = None, value_min: str | None = None,
            value_max: str | None = None, origin: str | None = None, issues: bool | None = None, aggregation: str | None = None,
            device_id: str | None = None, measurement_id: str | None = None, material_id: str | None = None,
            material_class: str | None = None, device_type: str | None = None, architecture: str | None = None,
            scan_direction: str | None = None, certified: bool | None = None,
            config_id: str | None = None, dataset_id: str | None = None, task_id: str | None = None, experiment_id: str | None = None,
            rag_variant: str | None = None, retrieval_method: str | None = None, embedding_model: str | None = None,
            generator_model: str | None = None, top_k: int | None = Query(None, ge=0), dataset_name: str | None = None,
            dataset_version: str | None = None, data_split: str | None = None, task_type: str | None = None,
            metric_k: int | None = Query(None, ge=0), sort: Literal['result_id', 'metric_value', 'year'] = 'result_id',
            identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    solar_filters = [device_id, measurement_id, material_id, material_class, device_type, architecture, scan_direction, certified]
    rag_filters = [config_id, dataset_id, task_id, experiment_id, metric_k, rag_variant, retrieval_method, embedding_model, generator_model, top_k, dataset_name, dataset_version, data_split, task_type]
    if (any(v is not None for v in solar_filters) and profile != 'solar-v1') or (any(v is not None for v in rag_filters) and profile != 'rag-v1'):
        raise Error(422, 'profile_filter_mismatch', 'Profile-specific filters require their explicit profile')
    from app.domain import decimal_value
    if any(v is not None and decimal_value(v) is None for v in (value_min, value_max)):
        raise Error(422, 'invalid_number', 'Filter values must be finite decimals')
    rows = rt.catalog.results(identity, id, profile, metric_name=metric, year=year, value_min=value_min, value_max=value_max,
        result_origin=origin, has_issues=issues, aggregation=aggregation, device_id=device_id, measurement_id=measurement_id,
        material_id=material_id, material_class=material_class, device_type=device_type, architecture=architecture, scan_direction=scan_direction,
        certified=certified, config_id=config_id, dataset_id=dataset_id, task_id=task_id, experiment_id=experiment_id, metric_k=metric_k,
        rag_variant=rag_variant,retrieval_method=retrieval_method,embedding_model=embedding_model,generator_model=generator_model,
        top_k=top_k,dataset_name=dataset_name,dataset_version=dataset_version,data_split=data_split,task_type=task_type)
    rows.sort(key=lambda r: (r.get(sort) is None, decimal_value(r[sort]) if sort == 'metric_value' and r[sort] is not None else r.get(sort) or '', r['publication_id'], r['result_id']))
    return paginate(rows, **pagination)


@router.get('/corpora/{id}/search')
def search(id: str, q: str = Query(..., min_length=1, max_length=500), scope: Literal['metadata', 'text', 'all'] = 'all',
           profile: Profile | None = None, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return paginate(rt.catalog.search(identity, id, q, scope, profile), **pagination)


@router.post('/corpora/{id}/comparisons')
def compare(id: str, body: Comparison, identity=Depends(actor), rt=Depends(runtime)):
    return rt.catalog.comparisons(identity, id, body.profile, body.results, body.area_tolerance)


@router.get('/corpora/{id}/issues')
def issues(id: str, rule: str | None = None, severity: str | None = None, profile: Profile | None = None, publication: str | None = None,
           review: str | None = None, run: str | None = None, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return paginate(rt.catalog.related(identity, 'corpora', id, 'issues', rule=rule, severity=severity, profile=profile,
                    publication_id=publication, review=review, run_id=run), **pagination)


@router.get('/issues/{id}')
def issue(id: str, response: Response, identity=Depends(actor), rt=Depends(runtime)):
    obj = rt.catalog.get(identity, 'issues', id)
    response.headers['ETag'] = '"'+obj['details'].get('review_revision', id)+'"'
    return obj


@router.patch('/issues/{id}')
def issue_review(id: str, body: Review, response: Response, if_match: str | None = Header(None), identity=Depends(actor), rt=Depends(runtime)):
    obj = rt.catalog.review_issue(identity, id, body.review, body.reason, if_match)
    response.headers['ETag'] = '"'+obj['details']['review_revision']+'"'
    return obj


@router.get('/corpora/{id}/review-items')
def review_queue(id: str, identity=Depends(actor), pagination=Depends(paging), rt=Depends(runtime)):
    return paginate(rt.catalog.review_items(identity, id), **pagination)


@router.get('/domain-profiles')
def profiles(identity=Depends(actor)):
    return {'items': [{'domain_profile': p, 'schema_version': '1.0.0', 'status': passport(p)['status']} for p in PROFILES], 'total': 2, 'page': 1, 'page_size': 2}


@router.get('/domain-profiles/{profile}')
def profile_info(profile: Profile, identity=Depends(actor)):
    return passport(profile)


@router.get('/domain-profiles/{profile}/rules')
def profile_rules(profile: Profile, identity=Depends(actor)):
    return rules(profile)
