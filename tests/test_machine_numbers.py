import copy
import pytest
from app.db import Uow
from app.domain import Error
from app.services.pipeline import Runner, normalize_results
from app.services.validation import machine_graph, typed_graph, structural
from tests.conftest import ModelDouble
from tests.fixtures import solar_graph, pdf_bytes
from tests.test_pipeline import enqueue


def d001_like_output():
    graph = solar_graph()
    graph['materials'][0]['bandgap_value'] = '∼1.9'
    result = graph['results'][0]
    result.update(raw_value='1,266, 1,278, 1,278, and 1,163 mV', raw_unit='mV',
                  metric_value='1,266, 1,278, 1,278, and 1,163', normalized_value=None,
                  normalized_unit=None, source_fragment='Reported voltage series for four samples')
    return graph


def test_approximate_and_series_values_are_preserved_without_inventing_exact_numbers():
    original = d001_like_output()
    saved = copy.deepcopy(original)
    graph = normalize_results(machine_graph(original))
    assert original == saved
    assert graph['materials'][0]['bandgap_value'] is None
    assert '∼1.9' in graph['materials'][0]['note']
    result = graph['results'][0]
    assert result['raw_value'] == original['results'][0]['raw_value']
    assert result['metric_value'] is None and result['normalized_value'] is None
    assert result['extraction_status'] == 'present_not_extractable'
    assert not structural(graph, 1)
    # Interactive/manual input still rejects text in a numeric field.
    with pytest.raises(Error):
        typed_graph(original)


def test_invalid_required_numbers_and_links_are_still_rejected():
    graph = solar_graph()
    graph['layers'] = [{'layer_id': 'L1', 'device_id': 'D1', 'layer_order': 'one or two'}]
    with pytest.raises(Error):
        machine_graph(graph)
    graph = d001_like_output()
    graph['results'][0]['device_id'] = 'missing-device'
    assert any(error['rule'] == 'links' for error in structural(normalize_results(machine_graph(graph)), 1))


def test_pipeline_finishes_with_preserved_ambiguous_model_numbers(env, corpus):
    class AmbiguousNumbers(ModelDouble):
        def call(self, purpose, schema, pages, context):
            result = super().call(purpose, schema, pages, context)
            if purpose == 'extract' and context['domain_profile'] == 'solar-v1':
                result['output'] = d001_like_output()
            return result
    job, items = enqueue(env, corpus)
    model = AmbiguousNumbers()
    Runner(Uow, env.storage, model, env.config).run(items[0]['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'
        item = u.repo.get('job_items', items[0]['id'])
        assert item['progress']['outputs']['solar-v1-0']['output']['materials'][0]['bandgap_value'] == '∼1.9'
        revision = u.repo.find('publication_revisions', publication_id=corpus.pub['id'], profile='solar-v1')[0]
        assert revision['graph']['results'][0]['extraction_status'] == 'present_not_extractable'


def test_later_page_batch_preserves_previous_records_and_evidence(env):
    actor = env.actors['editor']
    corpus = env.rt.documents.create_corpus(actor, {'name': 'Incremental extraction', 'split': 'synthetic'})
    doc, _ = env.rt.documents.upload(actor, corpus['id'], 'P001', 'four-pages.pdf', pdf_bytes(pages=4))
    from app.schemas.requests import JobCreate
    job = env.rt.jobs.enqueue(actor, corpus['id'], JobCreate(kind='process', all_documents=True).model_dump())
    with Uow() as u:
        item = u.repo.find('job_items', job_id=job['id'])[0]
    class IncrementalModel(ModelDouble):
        def call(self, purpose, schema, pages, context):
            result = super().call(purpose, schema, pages, context)
            if purpose == 'extract' and context['domain_profile'] == 'solar-v1':
                graph = solar_graph()
                if pages[0]['number'] == 4:
                    new = copy.deepcopy(graph['results'][-1])
                    new.update(result_id='R5', source_page=4)
                    graph.update(materials=[], devices=[], layers=[], measurements=[], results=[new])
                else:
                    graph['evidence'] = [{'evidence_id': 'old-source', 'entity_id': 'R1', 'field_path': 'metric_value',
                                          'source_page': 1, 'fragment': 'Voc = 1.0 V', 'method': 'text'}]
                result['output'] = graph
            return result
    Runner(Uow, env.storage, IncrementalModel(), env.config).run(item['id'])
    with Uow() as u:
        assert u.repo.get('jobs', job['id'])['status'] == 'succeeded'
        pub = u.repo.find('publications', document_id=doc['id'])[0]
        graph = u.repo.get('publication_revisions', pub['current']['solar-v1'])['graph']
        assert {row['result_id'] for row in graph['results']} == {'R1', 'R2', 'R3', 'R4', 'R5'}
        assert graph['devices'] and graph['measurements'] and graph['evidence'][0]['evidence_id'] == 'old-source'
