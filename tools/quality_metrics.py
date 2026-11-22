"""Offline, one-to-one scoring of benchmark exports. No network or model calls.

Strict score uses the project's existing semantic keys (linked scientific context, not IDs).
The separate source-value diagnostic omits entity context and must not be called semantic accuracy.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import statistics
import time
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

VERSION = 'dev-benchmark-1.2'
SOLAR_TARGET_METRICS = {'pce', 'voc', 'jsc', 'ff', 'rs', 'rsh', 'hi', 'jsceqe', 'stabilizedpce', 'retainedpce', 't80'}
METRIC_ALIASES = {
    'pce': 'pce', 'powerconversionefficiency': 'pce',
    'voc': 'voc', 'opencircuitvoltage': 'voc',
    'jsc': 'jsc', 'shortcircuitcurrentdensity': 'jsc',
    'ff': 'ff', 'fillfactor': 'ff',
    'rs': 'rs', 'seriesresistance': 'rs',
    'rsh': 'rsh', 'shuntresistance': 'rsh',
    'hi': 'hi', 'hysteresisindex': 'hi',
    'stabilizedpce': 'stabilizedpce', 'stabilizedpowerconversionefficiency': 'stabilizedpce',
    'retainedpce': 'retainedpce', 'retainedpowerconversionefficiency': 'retainedpce',
    'em': 'em', 'exactmatch': 'em', 'f1': 'f1', 'f1score': 'f1',
}
UNIT_ALIASES_EXTRA = {'mAcm-2': 'mA/cm2', 'mAcm−2': 'mA/cm2', 'Acm-2': 'A/cm2',
                      'Ohmcm2': 'Ohm*cm2', 'Ωcm2': 'Ohm*cm2'}


def read(directory, table):
    path = directory / (table + '.csv')
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def text(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').split()).casefold()


def number(value):
    try:
        result = Decimal(value)
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def semantic_rows(directory, profile):
    """Frozen semantic key policy from tools.manage; independent of future app/schema changes."""
    collections = ({'materials': 'material_id', 'devices': 'device_id', 'layers': 'layer_id',
                    'measurements': 'measurement_id'} if profile == 'solar-v1' else
                   {'configurations': 'config_id', 'datasets': 'dataset_id', 'tasks': 'task_id',
                    'experiments': 'experiment_id'})
    lookups = {name: {(r['publication_id'], r[key]): r for r in read(directory, name)}
               for name, key in collections.items()}

    def linked(row, collection, field):
        entity = lookups[collection].get((row['publication_id'], row.get(field)), {})
        if collection == 'devices':
            material = lookups['materials'].get((row['publication_id'], entity.get('absorber_material_id')), {})
            return tuple(entity.get(k) for k in ('device_label', 'device_type', 'architecture', 'active_area',
                                                  'area_definition')) + tuple(material.get(k) for k in (
                                                      'material_name_raw', 'formula_normalized', 'material_class'))
        return tuple((k, v) for k, v in entity.items() if not k.endswith('_id') and k not in ('publication_id', 'note'))

    result = []
    for row in read(directory, 'results'):
        if profile == 'solar-v1':
            relations = tuple(linked(row, c, f) for c, f in (
                ('devices', 'device_id'), ('measurements', 'measurement_id'), ('materials', 'material_id')))
            fields = ('aggregation', 'time_point', 'time_unit')
        else:
            relations = tuple(linked(row, c, f) for c, f in (
                ('configurations', 'config_id'), ('datasets', 'dataset_id'), ('tasks', 'task_id'),
                ('experiments', 'experiment_id')))
            fields = ('aggregation', 'metric_variant', 'metric_k')
        key = (row['publication_id'], row['metric_name'], row.get('normalized_unit') or row.get('metric_unit'),
               row['result_origin'], *relations, *(row.get(f, '') for f in fields))
        result.append((key, number(row.get('normalized_value') or row.get('metric_value')), row.get('raw_value', '')))
    return result


def counts(tp, predicted, gold):
    # Empty-empty extraction is undefined, not an artificial perfect article.
    precision = tp / predicted if predicted else (0. if gold else None)
    recall = tp / gold if gold else None
    f1 = 2 * tp / (predicted + gold) if predicted + gold else None
    return {'tp': tp, 'fp': predicted - tp, 'fn': gold - tp, 'predicted': predicted, 'gold': gold,
            'precision': precision, 'recall': recall, 'f1': f1}


def match_keys(predicted, gold, pred_keys, gold_keys):
    available = defaultdict(deque)
    for i, key in enumerate(gold_keys):
        available[key].append(i)
    pairs, fp = [], []
    for i, key in enumerate(pred_keys):
        if available[key]:
            pairs.append((i, available[key].popleft()))
        else:
            fp.append(i)
    fn = sorted(i for remaining in available.values() for i in remaining)
    return pairs, fp, fn


def unit_and_value(row):
    value = number(row.get('normalized_value') or row.get('metric_value'))
    unit = unicodedata.normalize('NFKC', row.get('normalized_unit') or row.get('metric_unit') or '')
    unit = unit.replace(' ', '').replace('^', '').replace('−', '-')
    # This finite list is declared in the report; no guessed units or guessed scales.
    aliases = {'percent': '%', 'percentage': '%', 'cm-2': '1/cm2'}
    unit = aliases.get(unit, unit)
    conversions = {'mV': ('V', Decimal('.001')), 'A/cm2': ('mA/cm2', Decimal('1000')),
                   'fraction': ('%', Decimal('100'))}
    if value is not None and unit in conversions:
        unit, factor = conversions[unit]
        value *= factor
    return unit, value


def source_key(row):
    unit, value = unit_and_value(row)
    return (row['publication_id'], text(row.get('metric_name')), row.get('result_origin', ''),
            text(row.get('source_page')), unit,
            ('number', value) if value is not None else ('raw', text(row.get('raw_value'))),
            text(row.get('aggregation')), text(row.get('metric_k')),
            text(row.get('time_point')), text(row.get('time_unit')), row.get('extraction_status', ''))


def canonical_value_key(row):
    """Broad value recovery diagnostic ONLY: ignores scientific conditions, never the main F1."""
    unit = unicodedata.normalize('NFKC', row.get('normalized_unit') or row.get('metric_unit') or '')
    unit = unit.replace(' ', '').replace('^', '')
    unit = UNIT_ALIASES_EXTRA.get(unit, unit)
    key = source_key({**row, 'normalized_unit': unit})
    compact = re.sub(r'[^a-z0-9]', '', text(row.get('metric_name')))
    metric = METRIC_ALIASES.get(compact, text(row.get('metric_name')))
    return (key[0], metric, key[2], key[3], key[4], key[5], key[10])


def score_scope(predicted, gold):
    by_id = {r['publication_id']: text(r.get('in_scope')) for r in predicted}
    matrix = Counter()
    for row in gold:
        expected = text(row['in_scope'])
        actual = by_id.get(row['publication_id'], '')
        if actual not in ('true', 'false'):
            actual = 'unknown'
        matrix[expected + '->' + actual] += 1
    correct = matrix['true->true'] + matrix['false->false']
    by_class = {}
    for label in ('true', 'false'):
        tp = matrix[label + '->' + label]
        actual = sum(v for k, v in matrix.items() if k.endswith('->' + label))
        expected = sum(v for k, v in matrix.items() if k.startswith(label + '->'))
        by_class[label] = counts(tp, actual, expected)
    recalls = [c['recall'] for c in by_class.values() if c['gold']]
    return {'accuracy': correct / len(gold) if gold else None, 'correct': correct, 'total': len(gold),
            'unknown': sum(v for k, v in matrix.items() if k.endswith('->unknown')),
            'confusion': dict(matrix), 'by_class': by_class,
            'balanced_accuracy_observed_classes': statistics.mean(recalls) if recalls else None,
            'note': 'Profile scope, not separate topic-label evaluation; unknown counts as incorrect.'}


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(values):
    return {'n': len(values), 'sum': sum(values), 'mean': statistics.mean(values) if values else None,
            'median': statistics.median(values) if values else None, 'p95': percentile(values, .95),
            'min': min(values) if values else None, 'max': max(values) if values else None}


def timings(area, sources, worker_events=()):
    documents = list(area['documents'].values())
    complete = [d for d in documents if d.get('status') == 'succeeded']
    latency = [d['elapsed_seconds'] for d in documents if 'elapsed_seconds' in d]
    active = []
    queue = []
    for d in documents:
        if d.get('running_first_observed_at') and d.get('observed_finished_at'):
            start = datetime.fromisoformat(d['submitted_at'])
            running = datetime.fromisoformat(d['running_first_observed_at'])
            finish = datetime.fromisoformat(d['observed_finished_at'])
            active.append((finish - running).total_seconds())
            queue.append((running - start).total_seconds())
    wall = ((datetime.fromisoformat(area['finished_at']) - datetime.fromisoformat(area['started_at'])).total_seconds()
            if area.get('finished_at') else None)
    statuses = dict(Counter(d.get('status', 'unfinished') for d in documents))
    successful_pages = sum(d['pages'] for d in complete)
    usage = Counter()
    calls = 0
    prepared = 0
    errors = []
    models = Counter()
    worker_by_job = defaultdict(float)
    for event in worker_events:
        worker_by_job[event['job_id']] += event['elapsed_ms'] / 1000
    worker_times = [worker_by_job[d['job_id']] for d in documents if d.get('job_id') in worker_by_job]
    worker_success_times = [worker_by_job[d['job_id']] for d in complete if d.get('job_id') in worker_by_job]
    for d in documents:
        for item in d.get('items', []):
            calls += item.get('successful_model_calls', 0)
            if item.get('progress', {}).get('model'):
                models[item['progress']['model']] += 1
            usage.update(item.get('progress', {}).get('usage', {}))
            progress = item.get('progress', {})
            prepared += max(progress.get('coverage', {}).get('prepared', 0),
                            sum(p.get('status') == 'complete' for p in progress.get('pages', {}).values()))
            if item.get('error'):
                errors.append({'publication_id': d['code'], 'error': item['error'],
                               'diagnostic': item.get('progress', {}).get('diagnostic')})
    return {'status_counts': statuses, 'requested_articles': len(sources), 'succeeded_articles': len(complete),
            'success_rate': len(complete) / len(sources) if sources else None,
            'input_pages': sum(d['pages'] for d in sources), 'prepared_pages': prepared,
            'pages_in_successful_articles': successful_pages, 'corpus_wall_seconds': wall,
            'article_end_to_end_seconds': distribution(latency),
            'successful_article_end_to_end_seconds': distribution([d['elapsed_seconds'] for d in complete]),
            'running_to_finish_observed_seconds': distribution(active),
            'submit_to_running_observed_seconds': distribution(queue),
            'worker_service_seconds': distribution(worker_times),
            'successful_worker_service_seconds': distribution(worker_success_times),
            'worker_export_seconds': worker_by_job.get(area.get('export', {}).get('job_id')),
            'worker_events_matched': sum(e['job_id'] in {d.get('job_id') for d in documents} for e in worker_events),
            'upload_seconds': sum(d.get('upload_seconds', 0) for d in documents),
            'export_end_to_end_seconds': area.get('export', {}).get('elapsed_seconds'),
            'download_seconds': area.get('export', {}).get('download_seconds'),
            'successful_articles_per_minute': len(complete) * 60 / wall if wall else None,
            'successful_article_pages_per_minute': successful_pages * 60 / wall if wall else None,
            'successful_model_calls_recorded': calls, 'recorded_token_usage': dict(usage), 'errors': errors,
            'error_counts': dict(Counter(e['error'] for e in errors)),
            'last_response_model_per_article': dict(models),
            'resumed_observation': any(d.get('resumed_observation') for d in documents),
            'note': 'Client wall time includes queue, preparation/OCR, model retries, validation, HTTP and polling. '
                    'Observed running time is not exact worker CPU time or isolated LLM latency. '
                    'Token/call counts cover cached successful responses only; failed/unreturned responses may be billed.'}


def write_csv(path, fields, values):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(values)


def snapshot_provenance(snapshot, area, inputs):
    """Check the actual exported revisions, rather than assuming no one edited the UI during a run."""
    expected = {d['document_id']: d for d in area['documents'].values()}
    hashes = {d['code']: d['sha256'] for d in inputs['pdfs']}
    seen, findings = set(), []
    for entry in snapshot['entries']:
        document = entry['document']
        identifier, code = document['id'], document['publication_code']
        seen.add(identifier)
        record = expected.get(identifier)
        if not record or record['code'] != code or document.get('sha256') != hashes.get(code):
            findings.append({'publication_id': code, 'problem': 'unexpected_document_or_source_hash'})
            continue
        # PublicationRevision.run_id and ClassificationRevision.run_id are JOB ITEM IDs in this app.
        runs = {item['id'] for item in record.get('items', [])}
        classification = entry.get('classification')
        if classification and (classification.get('reviewed') or classification.get('run_id') not in runs):
            findings.append({'publication_id': code, 'problem': 'classification_reviewed_or_from_another_run'})
        for profile, revision in entry['graphs'].items():
            if revision.get('origin') != 'machine' or revision.get('run_id') not in runs:
                findings.append({'publication_id': code, 'profile': profile, 'problem': 'graph_edited_or_from_another_run'})
    if seen != set(expected):
        findings.append({'problem': 'export_document_set_differs_from_benchmark'})
    return {'verified': not findings, 'documents': len(seen), 'findings': findings}


def evaluate_area(predicted, gold, profile, output):
    p_all, g_all = read(predicted, 'results'), read(gold, 'results')
    def in_metric_scope(row):
        compact = re.sub(r'[^a-z0-9]', '', text(row['metric_name']))
        return profile != 'solar-v1' or METRIC_ALIASES.get(compact, compact) in SOLAR_TARGET_METRICS
    p_indices = [i for i, r in enumerate(p_all) if r['extraction_status'] != 'absent' and in_metric_scope(r)]
    g_indices = [i for i, r in enumerate(g_all) if r['extraction_status'] != 'absent' and in_metric_scope(r)]
    pred, truth = [p_all[i] for i in p_indices], [g_all[i] for i in g_indices]
    p_semantic, g_semantic = semantic_rows(predicted, profile), semantic_rows(gold, profile)

    def strict_key(value, row):
        key, numeric, raw = value
        return key, ('number', numeric) if numeric is not None else ('raw', raw), row['extraction_status']

    comparisons = {
        'strict_semantic': ([strict_key(p_semantic[i], p_all[i]) for i in p_indices],
                            [strict_key(g_semantic[i], g_all[i]) for i in g_indices]),
        'source_value_diagnostic': ([source_key(r) for r in pred], [source_key(r) for r in truth])}
    comparisons['canonical_value_recovery_diagnostic'] = ([canonical_value_key(r) for r in pred],
                                                          [canonical_value_key(r) for r in truth])
    result = {'profile': profile, 'scope': score_scope(read(predicted, 'publications'), read(gold, 'publications')),
              'absent_rows_excluded': {'predicted': sum(r['extraction_status'] == 'absent' for r in p_all), 'gold': sum(r['extraction_status'] == 'absent' for r in g_all)},
              'outside_metric_scope_excluded': {'predicted': dict(Counter(r['metric_name'] for r in p_all if r['extraction_status'] != 'absent' and not in_metric_scope(r))),
                                                'gold': dict(Counter(r['metric_name'] for r in g_all if r['extraction_status'] != 'absent' and not in_metric_scope(r)))}}
    result['gold_facts_by_article'] = dict(Counter(r['publication_id'] for r in truth))
    codes = sorted({r['publication_id'] for r in read(gold, 'publications')} | {r['publication_id'] for r in pred})
    trace = []
    per_article = []
    for comparison, (pkeys, gkeys) in comparisons.items():
        pairs, fp, fn = match_keys(pred, truth, pkeys, gkeys)
        summary = counts(len(pairs), len(pred), len(truth))
        article_scores = []
        for code in codes:
            score = counts(sum(pred[i]['publication_id'] == code for i, _ in pairs),
                           sum(r['publication_id'] == code for r in pred),
                           sum(r['publication_id'] == code for r in truth))
            per_article.append({'comparison': comparison, 'publication_id': code, **score})
            # Macro over articles with at least one gold fact. Negative controls are scored via scope.
            if score['gold']:
                article_scores.append(score)
        summary['macro_f1_gold_positive_articles'] = statistics.mean(s['f1'] for s in article_scores) if article_scores else None
        summary['macro_articles'] = len(article_scores)
        result[comparison] = summary
        for status, indices in (('TP', pairs), ('FP', [(i, None) for i in fp]), ('FN', [(None, j) for j in fn])):
            for i, j in indices:
                p, g = pred[i] if i is not None else {}, truth[j] if j is not None else {}
                trace.append({'comparison': comparison, 'status': status,
                              'publication_id': (p or g)['publication_id'],
                              'predicted_id': p.get('result_id'), 'gold_id': g.get('result_id'),
                              'metric_name': (p or g)['metric_name'],
                              'predicted_value': p.get('normalized_value') or p.get('metric_value') or p.get('raw_value'),
                              'gold_value': g.get('normalized_value') or g.get('metric_value') or g.get('raw_value'),
                              'predicted_unit': p.get('normalized_unit') or p.get('metric_unit'),
                              'gold_unit': g.get('normalized_unit') or g.get('metric_unit'),
                              'predicted_page': p.get('source_page'), 'gold_page': g.get('source_page')})
    output.mkdir(exist_ok=True)
    write_csv(output / 'result_matches.csv', ['comparison', 'status', 'publication_id', 'predicted_id', 'gold_id',
              'metric_name', 'predicted_value', 'gold_value', 'predicted_unit', 'gold_unit', 'predicted_page', 'gold_page'], trace)
    write_csv(output / 'quality_by_article.csv', ['comparison', 'publication_id', 'tp', 'fp', 'fn', 'predicted',
              'gold', 'precision', 'recall', 'f1'], per_article)
    table_counts = []
    for path in sorted(gold.glob('*.csv')):
        table = path.stem
        table_counts.append({'table': table, 'predicted': len(read(predicted, table)), 'gold': len(read(gold, table))})
    result['table_counts_not_accuracy'] = table_counts
    result['result_status_counts'] = {'predicted': dict(Counter(r['extraction_status'] for r in p_all)),
                                      'gold': dict(Counter(r['extraction_status'] for r in g_all))}
    return result


def report(output):
    from tools.benchmark import sha, write_json
    start = time.perf_counter()
    state = json.loads((output / 'state.json').read_text(encoding='utf-8'))
    worker_events = (json.loads((output / 'worker_events.json').read_text(encoding='utf-8'))
                     if (output / 'worker_events.json').exists() else [])
    result = {'evaluator': VERSION, 'official_scorer': False, 'run_id': state['run_id'],
              'model': state['configuration']['model_id'], 'areas': {},
              'definitions': {
                  'strict_semantic': 'One-to-one exact project semantic result key + exact numeric value (Decimal) '
                      '+ extraction_status; local IDs ignored and scientific entities dereferenced. '
                      'Linked free-text context must match exactly. Absolute numeric tolerance = 0.',
                  'source_value_diagnostic': 'One-to-one publication + page + metric name (NFKC/whitespace/case) '
                      '+ origin + numeric value/unit or normalized raw text + aggregation + metric_k + time + status. '
                      'Ignores linked devices/configurations/datasets/tasks/experiments and metric_variant; '
                      'can produce accidental matches and cannot establish scientific correctness.',
                  'canonical_value_recovery_diagnostic': 'One-to-one publication + page + explicit canonical metric alias '
                      '+ origin + value/unit + status. Ignores entity links AND aggregation/time/k/variant. '
                      'Broad candidate-value recovery only; not semantic accuracy. Added after inspection of the solar '
                      'intermediate report revealed expanded metric names; original strict metrics are unchanged.',
                  'metric_aliases_canonical_diagnostic_only': METRIC_ALIASES,
                  'extra_unit_aliases_canonical_diagnostic_only': UNIT_ALIASES_EXTRA,
                  'unit_conversion_diagnostic_only': 'NFKC, strip spaces and ^; mV->V, A/cm2->mA/cm2, fraction->%; '
                      'percent/percentage->%. No guessed units, numeric tolerance, aliases for metric names or fuzzy matching.',
                  'absence': 'extraction_status=absent rows excluded from extraction P/R/F1; counts reported separately. '
                      'present_not_extractable retained and compared by raw text when no numeric value exists.',
                  'metric_scope': 'Version 1.2: Solar template README explicitly excludes additional metric names from extraction evaluation. '
                      'Only the 11 target metrics and their explicit aliases enter Solar denominators; excluded names/counts are recorded. RAG names remain open.',
                  'precision': 'TP/(TP+FP)', 'recall': 'TP/(TP+FN)', 'f1': '2TP/(2TP+FP+FN)',
                  'macro': 'Unweighted mean of article F1 over articles with gold facts; micro pools all result rows.',
                  'failure': 'Failed/waiting articles stay in gold denominator; no manual decisions or fabricated rows.',
                  'p95': 'Linear interpolation at sorted index (n-1)*0.95; one run, not a confidence interval.'}}
    result['experiment_wall_seconds_after_preflight'] = (
        (datetime.fromisoformat(state['finished_at']) - datetime.fromisoformat(state['started_at'])).total_seconds()
        if state.get('finished_at') else None)
    lines = ['ЗАМЕР КАЧЕСТВА И ВРЕМЕНИ ОБРАБОТКИ DEV',
             f'Запуск: {state["run_id"]}', f'Модель: {result["model"]}',
             f'Начало (UTC): {state["started_at"]}', f'Конец (UTC): {state.get("finished_at", "не завершён")}',
             f'Commit: {state["source"]["commit"]}', f'Оценщик: {VERSION}; собственная методика, не официальный scorer.',
             'Это замер всего конвейера с указанной моделью, включая классификацию, OCR и проверки.',
             'Скрипт выполняет автоматический прогон; происхождение экспортированных ревизий дополнительно проверяется ниже.',
             'Эталон не передавался модели. Один прогон без оценки разброса.',
             'Precision=TP/(TP+FP); Recall=TP/(TP+FN); F1=2TP/(2TP+FP+FN).',
             'P/R/F1 относятся к строкам results.csv. Связанные таблицы используются как контекст сопоставления;',
             'для остальных таблиц показаны количества строк, полная точность каждого их поля отдельно не оценивалась.',
             'TP: совпадение 1:1; FP: лишняя строка; FN: не найденная эталонная строка. Дубликаты не дают дополнительных TP.',
             'Если нет предсказаний при непустом эталоне, P/R/F1 приняты равными 0; пусто-пусто — н/д.',
             'Строгое совпадение: метрика, единица, происхождение, значение и связанные условия по текущему оценщику проекта.',
             'ID строк игнорируются. Сравнение чисел точное (Decimal, допуск 0); текст связанных условий должен совпадать.',
             'Диагностика чисел: та же статья/страница/метрика/единица/значение/происхождение/агрегация/k/время/статус.',
             'Она допускает только перечисленные в metrics.json преобразования единиц; не проверяет связи с прибором/конфигурацией.',
             'Диагностический F1 не заменяет научную оценку. Низкий строгий F1 может отражать различия текстовых описаний условий.',
             'Дополнительная диагностика значений со словарём имён объединяет, например, PCE и power conversion efficiency.',
             'Она добавлена после разбора первого солнечного отчёта; исходные две метрики не изменены.',
             'В ней также не проверяются агрегация, время, k и связанные условия: совпадение числа может быть случайным.',
             'absent не является извлечённым фактом и исключён из P/R/F1; present_not_extractable остаётся в сравнении.',
             'Ошибки и ожидание решения не удаляются из эталона. Неизвестная область считается ошибкой классификации.',
             f'Интервал опроса: {state["poll_seconds"]} с; границы времени наблюдаемые, погрешность до интервала + задержек HTTP.',
             'Время статьи — от отправки задания до наблюдения конца: очередь + подготовка/OCR + модель/повторы + проверки.',
             'Статьи подавались последовательно, по одной в задании. Медиана: центральное время; p95: 95-й процентиль.',
             'Отдельная чистая задержка модели и CPU-время не измерялись. Платные неуспешные ответы могут отсутствовать в usage.', '']
    if (output / 'worker_environment.json').exists():
        deployed = json.loads((output / 'worker_environment.json').read_text(encoding='utf-8'))
        normalize = lambda mapping: {k.replace('\\', '/'): v for k, v in mapping.items()}
        result['deployed_environment'] = deployed
        result['source_matches_deployed'] = normalize(deployed['app_sha256']) == normalize(state['source']['app_sha256'])
        lines += [f'Image worker: {deployed["image_id"]}; SHA-256 кода совпадает с локальным: {result["source_matches_deployed"]}',
                  f'Реальные настройки worker: {json.dumps(deployed["settings"], ensure_ascii=False)}',
                  f'Команда worker: {json.dumps(deployed.get("worker_command"), ensure_ascii=False)}',
                  'Сервисное время worker взято из job_item_finished.elapsed_ms (монотонный таймер сервера).',
                  'Оно исключает ожидание очереди/опрос клиента и включает подготовку, модель и проверки; при повторах суммируется.', '']

    def fmt(value):
        return 'н/д' if value is None else f'{value:.6f}'

    for data in state['inputs']:
        profile = data['profile']
        if profile not in state['areas'] or not (output / profile / 'submission').exists():
            lines.append(f'{profile}: экспорт ещё не готов; метрики не рассчитаны.')
            continue
        # Re-scoring a changed gold would silently redefine the experiment.
        frozen = output / 'gold' / profile
        gold = frozen if frozen.exists() else Path(data['root']) / 'dev_gold'
        for entry in data['gold']:
            if sha(gold / entry['name']) != entry['sha256']:
                raise ValueError(f'Gold changed since measurement: {entry["path"]}')
        predicted = output / profile / 'submission'
        score = evaluate_area(predicted, gold, profile, output / profile)
        export_raw = output / 'raw' / (state['areas'][profile].get('export', {}).get('job_id', '') + '.json')
        if export_raw.exists():
            exported = json.loads(export_raw.read_text(encoding='utf-8'))
            score['snapshot_provenance'] = snapshot_provenance(exported['job']['input']['snapshot'], state['areas'][profile], data)
        else:
            score['snapshot_provenance'] = {'verified': False, 'findings': ['export snapshot unavailable']}
        timing = timings(state['areas'][profile], data['pdfs'], worker_events)
        score['timing'] = timing
        result['areas'][profile] = score
        worker_seconds = Counter()
        for event in worker_events:
            worker_seconds[event['job_id']] += event['elapsed_ms'] / 1000
        article_times = [{**d, 'worker_service_seconds': worker_seconds.get(d.get('job_id'))}
                         for d in state['areas'][profile]['documents'].values()]
        write_csv(output / profile / 'timing_by_article.csv', [
            'code', 'document_id', 'job_id', 'pages', 'status', 'upload_seconds', 'submitted_at',
            'running_first_observed_at', 'observed_finished_at', 'elapsed_seconds', 'worker_service_seconds',
            'resumed_observation'], article_times)
        lines += [f'ПРОФИЛЬ: {profile}', f'PDF: {data["root"]}\\dev; эталон: {gold}',
                  f'Корпус: {state["areas"][profile]["corpus_id"]}',
                  f'Проверка происхождения выгрузки (PDF-хэши, исходные элементы заданий, отсутствие ручных ревизий): {json.dumps(score["snapshot_provenance"], ensure_ascii=False)}',
                  f'Статусы статей: {json.dumps(timing["status_counts"], ensure_ascii=False)}',
                  f'Успешно: {timing["succeeded_articles"]}/{timing["requested_articles"]}; доля {fmt(timing["success_rate"])}',
                  f'Страниц входных: {timing["input_pages"]}; подготовлено: {timing["prepared_pages"]}; в успешных статьях: {timing["pages_in_successful_articles"]}',
                  f'Scope accuracy: {fmt(score["scope"]["accuracy"])} ({score["scope"]["correct"]}/{score["scope"]["total"]}); unknown={score["scope"]["unknown"]}',
                  f'Scope balanced accuracy по имеющимся классам: {fmt(score["scope"]["balanced_accuracy_observed_classes"])}',
                  'Это оценка включения в профиль, отдельного эталона тематических labels в CSV нет.',
                  f'Матрица scope: {json.dumps(score["scope"]["confusion"], ensure_ascii=False)}']
        for label, label_score in score['scope']['by_class'].items():
            lines.append(f'  Класс in_scope={label}: gold={label_score["gold"]}; P={fmt(label_score["precision"])}; '
                         f'R={fmt(label_score["recall"])}; F1={fmt(label_score["f1"])}')
        for label, key in (('Строгое семантическое сравнение', 'strict_semantic'),
                           ('Диагностика совпадения чисел по страницам', 'source_value_diagnostic'),
                           ('Дополнительная диагностика значений со словарём имён, без проверки условий',
                            'canonical_value_recovery_diagnostic')):
            s = score[key]
            lines += [label + ':', f'  TP={s["tp"]}; FP={s["fp"]}; FN={s["fn"]}; predicted={s["predicted"]}; gold={s["gold"]}',
                      f'  Precision={fmt(s["precision"])}; Recall={fmt(s["recall"])}; micro-F1={fmt(s["f1"])}',
                      f'  macro-F1={fmt(s["macro_f1_gold_positive_articles"])}; статей с эталонными фактами={s["macro_articles"]}']
        lines += [f'Статусы результатов: {json.dumps(score["result_status_counts"], ensure_ascii=False)}',
                  f'Фактов по статьям в эталоне: {json.dumps(score["gold_facts_by_article"], ensure_ascii=False)}',
                  'Количество строк по таблицам (само по себе не оценка правильности):']
        lines += [f'  {t["table"]}: predicted={t["predicted"]}; gold={t["gold"]}' for t in score['table_counts_not_accuracy']]
        lines += [f'Время корпуса с загрузкой/выгрузкой, с: {fmt(timing["corpus_wall_seconds"])}',
                  f'Сумма загрузок PDF, с: {fmt(timing["upload_seconds"])}',
                  f'Выгрузка с проверками, с: {fmt(timing["export_end_to_end_seconds"])}',
                  f'Скачивание ZIP, с: {fmt(timing["download_seconds"])}']
        lines += [f'Сервисных событий worker по статьям: {timing["worker_events_matched"]}',
                  f'Экспорт на worker, с: {fmt(timing["worker_export_seconds"])}']
        for label, key in (('Все статьи', 'article_end_to_end_seconds'),
                           ('Только успешные', 'successful_article_end_to_end_seconds'),
                           ('От первого наблюдаемого running', 'running_to_finish_observed_seconds'),
                           ('От отправки до наблюдаемого running', 'submit_to_running_observed_seconds'),
                           ('Сервисное время worker, все статьи', 'worker_service_seconds'),
                           ('Сервисное время worker, успешные статьи', 'successful_worker_service_seconds')):
            d = timing[key]
            lines.append(f'{label}, с: n={d["n"]}; sum={fmt(d["sum"])}; mean={fmt(d["mean"])}; '
                         f'median={fmt(d["median"])}; p95={fmt(d["p95"])}; min={fmt(d["min"])}; max={fmt(d["max"])}')
        lines += [f'Пропускная способность успешных статей/мин: {fmt(timing["successful_articles_per_minute"])}',
                  f'Страниц успешных статей/мин: {fmt(timing["successful_article_pages_per_minute"])}',
                  f'Сохранено успешных ответов модели: {timing["successful_model_calls_recorded"]}',
                  f'Модель последнего сохранённого ответа по статьям: {json.dumps(timing["last_response_model_per_article"])}',
                  f'Учтённые токены (не полный биллинг): {json.dumps(timing["recorded_token_usage"])}',
                  f'Наблюдение возобновлялось: {timing["resumed_observation"]}',
                  f'Количество ошибок по кодам: {json.dumps(timing["error_counts"], ensure_ascii=False)}',
                  'Ошибки по статьям (полная диагностика в metrics.json и raw/*.json):']
        for error in timing['errors']:
            diagnostic = error.get('diagnostic') or {}
            message = str(diagnostic.get('message', '')).replace('\n', ' ')[:220]
            lines.append(f'  {error["publication_id"]}: {error["error"]}; {message}')
        lines.append('')
        lines.append('Время каждой статьи: код; статус; страницы; клиент, с; worker, с')
        for d in article_times:
            lines.append(f'  {d["code"]}; {d.get("status", "unfinished")}; {d["pages"]}; '
                         f'{fmt(d.get("elapsed_seconds"))}; {fmt(d["worker_service_seconds"])}')
        lines.append('')
    result['scoring_seconds'] = time.perf_counter() - start
    overview = ['КРАТКАЯ СВОДКА',
                'P/R/F1 ниже — строгий критерий для results.csv; объяснение и диагностика следуют далее.']
    for profile, score in result['areas'].items():
        t, q = score['timing'], score['strict_semantic']
        d = t['worker_service_seconds']
        overview += [f'{profile}: успешно {t["succeeded_articles"]}/{t["requested_articles"]}; '
                     f'P={fmt(q["precision"])}; R={fmt(q["recall"])}; F1={fmt(q["f1"])}; '
                     f'scope accuracy={fmt(score["scope"]["accuracy"])}',
                     f'  Корпус, мин: {fmt(t["corpus_wall_seconds"] / 60 if t["corpus_wall_seconds"] is not None else None)}; '
                     f'worker всех попыток, с: mean={fmt(d["mean"])}; median={fmt(d["median"])}; p95={fmt(d["p95"])}']
    overview += ['Точное сравнение описаний условий чувствительно к свободным названиям и формулировкам.',
                 'Числовая диагностика со словарём имён приведена отдельно и не подтверждает правильность связанных условий.', '']
    lines[7:7] = overview
    lines += [f'Общее время эксперимента после проверки входов, с: {fmt(result["experiment_wall_seconds_after_preflight"])}',
              f'Локальный расчёт метрик, с: {fmt(result["scoring_seconds"])}',
              'Подтверждения: state.json (SHA-256 входов/настройки/ID), events.jsonl (ход запуска), raw/*.json (ответы API),',
              '<profile>/export.zip и submission/*.csv (таблицы), result_matches.csv (все TP/FP/FN),',
              'quality_by_article.csv, timing_by_article.csv, metrics.json (полные значения и определения).',
              'gold/<profile>/*.csv — неизменяемая копия эталона с проверкой SHA-256, используется только локальным оценщиком.',
              'Скрипт запускается из корня science-extract; зависимости — requirements.txt.',
              'Пересчёт без обращений к модели:',
              f'python -m tools.benchmark --output "{output}" --score-only',
              'Новый эксперимент: та же команда без --score-only, с новым --output и --root E:\\RAG.',
              'После прерывания: --resume с прежним --output. Незавершённые задания продолжаются без повторного создания.',
              'Изменение модели/настроек/кода требует нового каталога запуска; воспроизводимость LLM не означает детерминизм.']
    write_json(output / 'metrics.json', result)
    (output / 'metrics.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    (output / 'reproduce').mkdir(exist_ok=True)
    shutil.copy2(__file__, output / 'reproduce' / 'quality_metrics.py')
    # Keep both the orchestrator initially used and the current version with optional Docker evidence.
    original = output / 'reproduce' / 'benchmark_started.py'
    benchmark_copy = output / 'reproduce' / 'benchmark.py'
    if benchmark_copy.exists() and not original.exists():
        shutil.copy2(benchmark_copy, original)
    shutil.copy2(Path(__file__).with_name('benchmark.py'), benchmark_copy)
    write_json(output / 'script_hashes.json', {p.name: sha(p) for p in (output / 'reproduce').glob('*.py')})
    return result
