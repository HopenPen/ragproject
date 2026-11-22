import copy
import fitz
import pytest
from pydantic import ValidationError
from app.db import Uow
from app.domain import Error, normalize_value, scalar_number
from app.schemas.graphs import Classification, Evidence
from app.services.classification import automatic_decision, machine_classification
from app.services.model_candidates import machine_sources, repair_duplicate_links, apply_graph_repair
from app.services.pipeline import Runner, normalize_results
from app.services.validation import source_checks, structural
from tests.conftest import ModelDouble
from tests.fixtures import classification, solar_graph, pdf_bytes
from tests.test_pipeline import enqueue


def test_machine_topic_scope_coherence_does_not_relax_manual_validation():
    original = classification(['solar'], scope=False)
    original['outcome'] = 'outside'
    fixed = machine_classification(original)
    assert fixed['labels'] == ['solar'] and fixed['solar']['in_scope'] is False
    assert automatic_decision(fixed, .85)['outcome'] == 'resolved'
    assert original['outcome'] == 'outside'
    with pytest.raises(ValidationError):
        Classification.model_validate(original)
    original['confidence'] = 2
    with pytest.raises(Error) as exc:
        machine_classification(original)
    assert exc.value.code == 'invalid_classification'
    assert exc.value.details[0]['loc'] == ('confidence',)


def test_source_repairs_keep_raw_response_and_require_review():
    value = {'evidence': [{'evidence_id': 'E1', 'entity_id': 'R1', 'field_path': 'raw_value',
        'source_page': 2, 'method': 'vision', 'bbox': [10, 20, 1000, 1400],
        'artifact_ref': 'wrong-document', 'reading_method': 'read table', 'review': 'open'}]}
    saved = copy.deepcopy(value)
    pages = [{'number': 2, 'width': 600, 'height': 800, 'text': ''}]
    artifacts = [{'id': 'actual-page', 'page': 2, 'kind': 'page', 'content_type': 'image/png'}]
    changes = []
    fixed = machine_sources(value, pages, artifacts, changes)
    ev = Evidence.model_validate(fixed['evidence'][0])
    assert value == saved and len(changes) == 3
    assert ev.artifact_ref == 'actual-page' and list(ev.bbox) == [0, 0, 600, 800]
    assert ev.review == 'needs_review'
    assert not [f for f in source_checks({**fixed, 'results': []}, pages, artifacts) if f['severity'] == 'error']
    # A table identifier is valid visual localization; do not pretend it is a plot.
    table = {**fixed['evidence'][0], 'bbox': None, 'table': 'Table 1'}
    assert Evidence.model_validate(table).figure is None
    # A page outside this PDF is never rebound to an arbitrary available page.
    value['evidence'][0]['source_page'] = 99
    assert machine_sources(value, pages, artifacts, []) == value


def test_unique_visual_caption_corrects_batch_boundary_page_and_does_not_invent_quote():
    pages = [{'number': n, 'width': 600, 'height': 800, 'text': text} for n, text in
             [(1, 'Text mentions Fig. 7 elsewhere.'), (2, 'Fig. 7. Accuracy benchmark\n97.67')]]
    artifacts = [{'id': str(n), 'page': n, 'kind': 'page', 'content_type': 'image/png'} for n in (1, 2)]
    value = {'evidence': [{'evidence_id': 'E1', 'entity_id': 'R1', 'field_path': 'metric_value',
        'source_page': 1, 'figure': 'Fig. 7', 'method': 'vision', 'artifact_ref': '1',
        'reading_method': 'Bar label', 'bbox': None, 'review': 'open', 'fragment': 'The bar chart reports an accuracy of 97.67'}],
        'results': [{'result_id': 'R1', 'source_page': 1, 'source_figure': 'Fig. 7', 'source_fragment': None}]}
    assert any(f['severity'] == 'error' for f in source_checks(value, pages, artifacts))
    fixed = machine_sources(value, pages, artifacts, [])
    ev = fixed['evidence'][0]
    assert ev['source_page'] == fixed['results'][0]['source_page'] == 2
    assert ev['artifact_ref'] == '2' and ev['fragment'] is None
    assert 'не цитата' in ev['reading_method']
    assert not [f for f in source_checks(fixed, pages, artifacts) if f['severity'] == 'error']
    assert value['evidence'][0]['source_page'] == 1
    # A literal result quoted in the body keeps the body page even when it cites a later table.
    body = {'evidence': [], 'results': [{'result_id': 'R1', 'source_page': 1, 'source_figure': 'Fig. 7',
                                       'source_fragment': 'Text mentions Fig. 7 elsewhere.'}]}
    assert machine_sources(body, pages, artifacts, [])['results'][0]['source_page'] == 1


def test_bad_duplicate_hint_cannot_discard_measurements():
    graph = solar_graph()
    graph['results'][1]['duplicate_of'] = 'R1'
    changes = []
    fixed = repair_duplicate_links(graph, changes)
    assert len(fixed['results']) == 4 and fixed['results'][1]['duplicate_of'] is None
    assert len(changes) == 1 and not structural(fixed, 1)
    duplicate = {**graph['results'][0], 'result_id': 'R5', 'duplicate_of': 'R1'}
    graph['results'].append(duplicate)
    assert repair_duplicate_links(graph, [])['results'][-1]['duplicate_of'] == 'R1'


def test_canonical_solar_metric_and_unit_preserve_raw_value():
    graph = solar_graph()
    graph['results'][0].update(metric_name='Open-circuit voltage', raw_value='1123', raw_unit='mV')
    graph['results'][1].update(raw_unit='mA/cm²', normalized_unit='mA/cm²')
    result = normalize_results(graph)
    assert result['results'][0]['metric_name'] == 'Voc'
    assert result['results'][0]['normalized_value'] == '1.123'
    assert result['results'][0]['raw_value'] == '1123' and result['results'][0]['raw_unit'] == 'mV'
    assert result['results'][1]['metric_unit'] == 'mA/cm2'
    assert not structural(result, 1)


def test_grouped_english_scalar_numbers_do_not_turn_series_or_ranges_into_values():
    from app.services.validation import machine_graph
    assert normalize_value('1,197', 'mV', 'V') == scalar_number('1.197')
    assert normalize_value('1,266', 'mV', 'V') == scalar_number('1.266')
    for raw in ['1,266, 1,278, 1,278, and 1,163', '0,123', '12,34', '~1,197', '1,197–1,278']:
        assert normalize_value(raw, 'mV', 'V') is None
    graph = solar_graph()
    graph['results'][0].update(raw_value='1,197', raw_unit='mV', normalized_value='1,197', metric_value='1,197')
    result = normalize_results(machine_graph(graph))['results'][0]
    assert result['metric_value'] == '1.197' and result['raw_value'] == '1,197'
    assert result['extraction_status'] == 'extracted'


def test_literal_units_inside_raw_values_and_unknown_rag_scales():
    assert normalize_value('97%', '%', '%') == 97
    assert normalize_value('1,197 mV', 'mV', 'V') == scalar_number('1.197')
    assert normalize_value('\u22122.5%', '%', '%') == scalar_number('-2.5')
    assert normalize_value('0.52', None, None) == scalar_number('0.52')
    assert normalize_value('52', None, '%') is None
    assert normalize_value('97% ± 2%', '%', '%') is None
    assert normalize_value('97% and 92%', '%', '%') is None


def test_saved_response_replay_cannot_make_a_provider_call(env, corpus):
    class NoProvider(ModelDouble):
        def call(self, *args, **kwargs):
            raise AssertionError('Replay must never contact a provider')
    _, items = enqueue(env, corpus)
    runner = Runner(Uow, env.storage, NoProvider(), env.config)
    with pytest.raises(Error) as exc:
        runner.model_call(items[0]['id'], 'unused', {'replay_only': True}, 'missing', 'extract', {}, [], {})
    assert exc.value.code == 'replay_missing_output'


def test_repair_delta_keeps_omitted_facts_and_classification_metadata():
    graph = solar_graph()
    patch = {**graph, 'bibliography': {'title': None, 'authors': [], 'year': None, 'DOI': None},
             'scope': {'in_scope': None, 'exclusion_reason': None}, 'materials': [], 'devices': [], 'measurements': [], 'results': []}
    fixed = apply_graph_repair(graph, {'graph': patch, 'removed_entities': [], 'removed_evidence': []})
    assert fixed == graph
    removed = apply_graph_repair(graph, {'graph': patch, 'removed_entities': [{'id': 'R4', 'reason': 'Not supported by source'}], 'removed_evidence': []})
    assert len(removed['results']) == 3 and len(graph['results']) == 4
    with pytest.raises(Error):
        apply_graph_repair(graph, {'graph': patch, 'removed_entities': [{'id': 'other-document', 'reason': 'bad link'}], 'removed_evidence': []})
    patch['scope']['in_scope'] = False
    with pytest.raises(Error):
        apply_graph_repair(graph, {'graph': patch, 'removed_entities': [], 'removed_evidence': []})


def test_preparing_pdf_sanitizes_nul_without_deleting_words(env, monkeypatch):
    original = fitz.Page.get_text
    def nul_text(page, *args, **kwargs):
        value = original(page, *args, **kwargs)
        if args and args[0] == 'blocks':
            return [(*row[:4], row[4] + 'A\x00B', *row[5:]) for row in value]
        return value + 'A\x00B'
    data = pdf_bytes()
    monkeypatch.setattr(fitz.Page, 'get_text', nul_text)
    prepared = env.storage.prepare_page(data, 1)
    assert prepared['text_replacements'] == 1
    assert 'A\ufffdB' in prepared['text'] and 'A\x00B' in prepared['raw_text']
    assert all('\x00' not in b['text'] for b in prepared['blocks'])


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_final_batch_is_repaired_and_never_published_without_validation(env, corpus, repair_succeeds):
    class BrokenLinks(ModelDouble):
        def call(self, purpose, schema, pages, context):
            result = super().call(purpose, schema, pages, context)
            if purpose == 'extract' and (not context.get('repair') or not repair_succeeds):
                result['output'].get('graph', result['output'])['results'][0]['device_id'] = 'not-in-pdf'
            return result
    job, items = enqueue(env, corpus)
    model = BrokenLinks(classification(['solar']))
    runner = Runner(Uow, env.storage, model, env.config)
    if repair_succeeds:
        runner.run(items[0]['id'])
    else:
        with pytest.raises(Error) as exc:
            runner.run(items[0]['id'])
        assert exc.value.code == 'invalid_candidate'
    with Uow() as u:
        item = u.repo.get('job_items', items[0]['id'])
        pub = u.repo.get('publications', corpus.pub['id'])
        assert item['status'] == ('succeeded' if repair_succeeds else 'failed')
        assert item['progress']['outputs']['solar-v1-0']['output']['results'][0]['device_id'] == 'not-in-pdf'
        assert len([call for call in model.calls if call[2].get('repair')]) == (1 if repair_succeeds else 2)
        if repair_succeeds:
            assert not structural(u.repo.get('publication_revisions', pub['current']['solar-v1'])['graph'], 1)
        else:
            assert not pub['current'] and item['progress']['diagnostic']['details']


def test_repairs_respect_total_model_call_budget(env, corpus):
    class InvalidResult(ModelDouble):
        def call(self, purpose, schema, pages, context):
            result = super().call(purpose, schema, pages, context)
            if purpose == 'extract':
                result['output'].get('graph', result['output'])['results'][0]['device_id'] = 'missing'
            return result
    job, items = enqueue(env, corpus)
    model = InvalidResult(classification(['solar']))
    runner = Runner(Uow, env.storage, model, env.config.model_copy(update={'model_max_calls': 3}))
    with pytest.raises(Error) as exc:
        runner.run(items[0]['id'])
    assert exc.value.code == 'model_budget_exceeded' and len(model.calls) == 3


def test_invalid_repair_envelope_gets_one_bounded_followup(env, corpus):
    class FirstRepairInvalid(ModelDouble):
        def call(self, purpose, schema, pages, context):
            result = super().call(purpose, schema, pages, context)
            if purpose == 'extract' and not context.get('repair'):
                result['output']['results'][0]['device_id'] = 'missing'
            if context.get('repair') and len([c for c in self.calls if c[2].get('repair')]) == 1:
                result['output'] = {'wrong_envelope': True}
            return result
    _, items = enqueue(env, corpus)
    model = FirstRepairInvalid(classification(['solar']))
    Runner(Uow, env.storage, model, env.config).run(items[0]['id'])
    with Uow() as u:
        item = u.repo.get('job_items', items[0]['id'])
        assert item['status'] == 'succeeded' and len(item['progress']['repair_rejections']) == 1
        assert len([c for c in model.calls if c[2].get('repair')]) == 2


def test_incomplete_provider_usage_is_preserved_in_failed_job(env, corpus):
    class Incomplete(ModelDouble):
        def call(self, *args, **kwargs):
            raise Error(502, 'partial_model_output', 'Incomplete response',
                        {'response_id': 'real-provider-response', 'usage': {'input_tokens': 12, 'output_tokens': 34, 'total_tokens': 46}})
    _, items = enqueue(env, corpus)
    with pytest.raises(Error):
        Runner(Uow, env.storage, Incomplete(), env.config).run(items[0]['id'])
    with Uow() as u:
        item = u.repo.get('job_items', items[0]['id'])
        assert item['progress']['usage']['total_tokens'] == 46
        assert item['progress']['failed_calls']['classify-0:0']['response_id'] == 'real-provider-response'
        assert not item['progress'].get('outputs') and item['status'] == 'failed'
