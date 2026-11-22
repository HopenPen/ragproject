from copy import deepcopy
import json

from app.profiles import csv_columns
from app.services.export import csv_bytes
from tests.fixtures import rag_graph, solar_graph
from tools.quality_metrics import canonical_value_key, counts, evaluate_area, percentile, score_scope, source_key, timings, snapshot_provenance


def submission(path, graph, profile='rag-v1'):
    path.mkdir()
    for table, columns in csv_columns(profile).items():
        rows = graph.get(table, []) if table != 'publications' else [{'title': 'fixture', 'in_scope': True}]
        (path / (table + '.csv')).write_bytes(csv_bytes(columns, [{'publication_id': 'D001', **r} for r in rows]))


def test_one_to_one_context_and_duplicates(tmp_path):
    gold, pred = rag_graph(), rag_graph()
    gold['configurations'][0]['config_id'] = 'gold-config'
    gold['results'][0]['config_id'] = 'gold-config'
    gold['results'][0]['result_id'] = 'gold-result'
    pred['results'].append(deepcopy(pred['results'][0]))
    pred['results'][1]['result_id'] = 'duplicate'
    submission(tmp_path / 'gold', gold)
    submission(tmp_path / 'pred', pred)
    result = evaluate_area(tmp_path / 'pred', tmp_path / 'gold', 'rag-v1', tmp_path / 'details')
    assert result['strict_semantic']['tp'] == 1
    assert result['strict_semantic']['fp'] == 1
    assert result['strict_semantic']['fn'] == 0
    assert result['strict_semantic']['precision'] == .5


def test_solar_extra_metrics_are_unscored_as_required_by_template(tmp_path):
    gold, pred = solar_graph(), solar_graph()
    extra = {**pred['results'][0], 'result_id': 'extra', 'metric_name': 'conductivity'}
    pred['results'].append(extra)
    submission(tmp_path / 'gold', gold, 'solar-v1')
    submission(tmp_path / 'pred', pred, 'solar-v1')
    result = evaluate_area(tmp_path / 'pred', tmp_path / 'gold', 'solar-v1', tmp_path / 'details')
    assert result['strict_semantic']['tp'] == 4 and result['strict_semantic']['fp'] == 0
    assert result['outside_metric_scope_excluded']['predicted'] == {'conductivity': 1}
    assert result['absent_rows_excluded'] == {'predicted': 0, 'gold': 0}


def test_weak_diagnostic_does_not_establish_context_match(tmp_path):
    gold, pred = rag_graph(), rag_graph()
    pred['configurations'][0]['generator_model'] = 'different-model'
    submission(tmp_path / 'gold', gold)
    submission(tmp_path / 'pred', pred)
    result = evaluate_area(tmp_path / 'pred', tmp_path / 'gold', 'rag-v1', tmp_path / 'details')
    assert result['strict_semantic']['tp'] == 0
    assert result['strict_semantic']['fp'] == result['strict_semantic']['fn'] == 1
    assert result['source_value_diagnostic']['tp'] == 1


def test_empty_prediction_counts_missing_gold_and_unknown_scope(tmp_path):
    gold, pred = rag_graph(), rag_graph()
    pred['results'] = []
    submission(tmp_path / 'gold', gold)
    submission(tmp_path / 'pred', pred)
    result = evaluate_area(tmp_path / 'pred', tmp_path / 'gold', 'rag-v1', tmp_path / 'details')
    assert result['strict_semantic']['fn'] == 1
    assert result['strict_semantic']['f1'] == 0
    scope = score_scope([{'publication_id': 'D001', 'in_scope': ''}], [
        {'publication_id': 'D001', 'in_scope': 'true'}, {'publication_id': 'D002', 'in_scope': 'false'}])
    assert scope['accuracy'] == 0 and scope['unknown'] == scope['total'] == 2


def test_source_diagnostic_units_pages_and_ambiguous_values():
    base = {'publication_id': 'D001', 'metric_name': 'Voc', 'metric_value': '1000',
            'metric_unit': 'mV', 'source_page': '2', 'extraction_status': 'extracted'}
    assert source_key(base) == source_key({**base, 'metric_value': '1.000', 'metric_unit': 'V'})
    assert source_key(base) != source_key({**base, 'source_page': '3'})
    uncertain = {**base, 'metric_value': '', 'raw_value': '~1000', 'extraction_status': 'present_not_extractable'}
    assert source_key(base) != source_key(uncertain)
    assert source_key(uncertain) != source_key({**uncertain, 'raw_value': '1000-1100'})


def test_absent_rows_excluded_not_rewarded_as_facts(tmp_path):
    gold, pred = rag_graph(), rag_graph()
    absent = {**gold['results'][0], 'result_id': 'absent', 'metric_value': None, 'normalized_value': None,
              'raw_value': None, 'extraction_status': 'absent'}
    gold['results'].append(absent)
    submission(tmp_path / 'gold', gold)
    submission(tmp_path / 'pred', pred)
    result = evaluate_area(tmp_path / 'pred', tmp_path / 'gold', 'rag-v1', tmp_path / 'details')
    assert result['strict_semantic']['f1'] == 1
    assert result['absent_rows_excluded'] == {'gold': 1, 'predicted': 0}


def test_denominators_and_percentile():
    assert counts(0, 0, 2)['precision'] == 0
    assert counts(0, 0, 0)['f1'] is None
    assert percentile([1, 2, 3, 4, 5], .95) == 4.8


def test_canonical_diagnostic_explicit_aliases_and_weaker_context():
    base = {'publication_id': 'D001', 'metric_name': 'PCE', 'metric_value': '23.05',
            'metric_unit': '%', 'source_page': '6', 'extraction_status': 'extracted', 'aggregation': 'champion'}
    expanded = {**base, 'metric_name': 'power conversion efficiency', 'aggregation': ''}
    assert source_key(base) != source_key(expanded)
    assert canonical_value_key(base) == canonical_value_key(expanded)
    assert canonical_value_key(base) != canonical_value_key({**expanded, 'metric_name': 'efficiency'})
    assert canonical_value_key(base) != canonical_value_key({**expanded, 'source_page': '5'})


def test_worker_attempt_durations_are_summed_without_dropping_failures():
    area = {'started_at': '2026-01-01T00:00:00+00:00', 'finished_at': '2026-01-01T00:01:00+00:00',
            'documents': {
                'D001': {'code': 'D001', 'job_id': 'a', 'pages': 2, 'status': 'succeeded', 'elapsed_seconds': 5},
                'D002': {'code': 'D002', 'job_id': 'b', 'pages': 3, 'status': 'failed', 'elapsed_seconds': 7}}}
    events = [{'job_id': 'a', 'elapsed_ms': 1000}, {'job_id': 'a', 'elapsed_ms': 2000},
              {'job_id': 'b', 'elapsed_ms': 6000}, {'job_id': 'unrelated', 'elapsed_ms': 99999}]
    result = timings(area, [{'pages': 2}, {'pages': 3}], events)
    assert result['worker_service_seconds']['sum'] == 9
    assert result['worker_service_seconds']['mean'] == 4.5
    assert result['successful_worker_service_seconds']['sum'] == 3
    assert result['success_rate'] == .5
    assert result['pages_in_successful_articles'] == 2
    assert result['article_end_to_end_seconds']['sum'] == 12


def test_export_provenance_detects_manual_changes_and_other_generation():
    area = {'documents': {'D001': {'document_id': 'doc', 'code': 'D001', 'job_id': 'parent-job',
                                  'items': [{'id': 'original'}]}}}
    inputs = {'pdfs': [{'code': 'D001', 'sha256': 'source-hash'}]}
    snapshot = {'entries': [{'document': {'id': 'doc', 'publication_code': 'D001', 'sha256': 'source-hash'},
                            'classification': {'reviewed': False, 'run_id': 'original'},
                            'graphs': {'rag-v1': {'origin': 'machine', 'run_id': 'original'}}}]}
    assert snapshot_provenance(snapshot, area, inputs)['verified']
    modified = deepcopy(snapshot)
    modified['entries'][0]['graphs']['rag-v1']['run_id'] = 'later-retry'
    assert not snapshot_provenance(modified, area, inputs)['verified']
    modified = deepcopy(snapshot)
    modified['entries'][0]['classification']['reviewed'] = True
    assert not snapshot_provenance(modified, area, inputs)['verified']


def test_offline_report_writes_trace_and_real_timing_fields(tmp_path):
    from tools.benchmark import sha, write_json
    from tools.quality_metrics import report
    frozen, predicted = tmp_path / 'gold' / 'rag-v1', tmp_path / 'rag-v1' / 'submission'
    frozen.parent.mkdir()
    predicted.parent.mkdir()
    submission(frozen, rag_graph())
    submission(predicted, rag_graph())
    start, end = '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:10+00:00'
    state = {'run_id': 'unit-test-only', 'started_at': start, 'finished_at': end,
             'configuration': {'model_id': 'SYNTHETIC TEST ONLY'}, 'source': {'commit': 'test'},
             'poll_seconds': 2, 'inputs': [{'profile': 'rag-v1', 'root': str(tmp_path / 'source'),
                'pdfs': [{'code': 'D001', 'pages': 1}],
                'gold': [{'name': p.name, 'path': str(p), 'sha256': sha(p)} for p in frozen.glob('*.csv')]}],
             'areas': {'rag-v1': {'corpus_id': 'test', 'started_at': start, 'finished_at': end,
                'documents': {'D001': {'code': 'D001', 'pages': 1, 'job_id': 'test-job',
                    'status': 'succeeded', 'elapsed_seconds': 5, 'submitted_at': start, 'observed_finished_at': end}}}}}
    write_json(tmp_path / 'state.json', state)
    write_json(tmp_path / 'worker_events.json', [{'job_id': 'test-job', 'elapsed_ms': 4123}])
    result = report(tmp_path)
    assert result['areas']['rag-v1']['strict_semantic']['f1'] == 1
    assert result['areas']['rag-v1']['timing']['worker_service_seconds']['mean'] == 4.123
    assert (tmp_path / 'metrics.txt').read_text(encoding='utf-8-sig').startswith('ЗАМЕР')
    assert '4.123000' in (tmp_path / 'metrics.txt').read_text(encoding='utf-8-sig')
    assert json.loads((tmp_path / 'metrics.json').read_text(encoding='utf-8'))['run_id'] == 'unit-test-only'
    assert (tmp_path / 'rag-v1' / 'result_matches.csv').is_file()
    assert 'worker_service_seconds' in (tmp_path / 'rag-v1' / 'timing_by_article.csv').read_text(encoding='utf-8-sig')
