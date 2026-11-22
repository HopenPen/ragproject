"""Offline regression audit of saved provider outputs; no model calls and no gold access.

This diagnoses technical validity, NOT new processing success or extraction accuracy.
Usage: python -m tools.audit_model_outputs --baseline runtime/benchmarks/RUN --output runtime/audit/RUN
"""
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from app.domain import Error, PIPELINE_VERSION, PROMPT_VERSION
from app.profiles import GRAPHS
from app.services.classification import machine_classification
from app.services.model_candidates import machine_sources, repair_duplicate_links
from app.services.pipeline import merge_extraction_graph, normalize_results, machine_evidence
from app.services.validation import machine_graph, structural, source_checks


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def audit(baseline, output):
    baseline, output = baseline.resolve(), output.resolve()
    if output == baseline or baseline in output.parents:
        raise ValueError('Use a separate output directory; baseline must remain unchanged')
    state = read(baseline / 'state.json')
    sources, source_hashes = {}, {}
    for area in state['areas'].values():
        raw = baseline / 'raw' / (area['export']['job_id'] + '.json')
        source_hashes[raw.name] = hashlib.sha256(raw.read_bytes()).hexdigest()
        for entry in read(raw)['job']['input']['snapshot']['entries']:
            sources[entry['document']['id']] = entry
    records = []
    for profile, area in state['areas'].items():
        for code, record in area['documents'].items():
            raw = baseline / 'raw' / (record['job_id'] + '.json')
            source_hashes[raw.name] = hashlib.sha256(raw.read_bytes()).hexdigest()
            item = read(raw)['items'][0]
            entry = sources[record['document_id']]
            pages, artifacts = entry['pages'], entry['artifacts']
            changes, class_errors, graph_errors = [], [], []
            outputs = item['progress'].get('outputs', {})
            class_calls = 0
            for key, response in outputs.items():
                if not key.startswith('classify'):
                    continue
                class_calls += 1
                try:
                    machine_classification(machine_sources(response['output'], pages, artifacts, changes))
                except Error as exc:
                    class_errors.append({'call': key, 'code': exc.code, 'details': exc.details})
            graph = None
            calls = sorted((key for key in outputs if re.fullmatch(re.escape(profile) + r'-\d+', key)),
                           key=lambda key: int(key.rsplit('-', 1)[1]))
            for key in calls:
                try:
                    value = machine_sources(outputs[key]['output'], pages, artifacts, changes)
                    updated = machine_graph(value)
                    if graph is None:
                        graph = GRAPHS[profile](domain_profile=profile, bibliography=updated['bibliography'],
                                              scope=updated['scope']).model_dump(mode='json')
                    graph = merge_extraction_graph(graph, updated)
                except Error as exc:
                    graph_errors.append({'call': key, 'code': exc.code, 'details': exc.details})
                    break
            findings = []
            if graph is not None and not graph_errors:
                graph = repair_duplicate_links(machine_evidence(normalize_results(graph)), changes)
                findings = structural(graph, record['pages']) + [f for f in source_checks(graph, pages, artifacts) if f['severity'] == 'error']
                candidate_path = output / 'candidates' / profile / (code + '.json')
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                candidate_path.write_text(json.dumps({'graph': graph, 'document_id': record['document_id'],
                    'classification': entry['classification']['decision'] if entry['classification'] else None}, ensure_ascii=False), encoding='utf-8')
            records.append({'profile': profile, 'code': code, 'baseline_status': item['status'], 'baseline_error': item.get('error'),
                'cached_classification_calls': class_calls, 'classification_errors_after_repairs': class_errors,
                'cached_extraction_calls': len(calls), 'graph_errors_after_repairs': graph_errors,
                'candidate_valid_without_model_repair': graph is not None and not graph_errors and not findings,
                'remaining_findings': findings, 'adjustments': changes})
    result = {'kind': 'offline_technical_audit_not_accuracy_measurement', 'baseline': str(baseline),
              'pipeline_version': PIPELINE_VERSION, 'prompt_version': PROMPT_VERSION,
              'source_sha256': source_hashes, 'records': records}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['ПРОВЕРКА СОХРАНЁННЫХ ОТВЕТОВ МОДЕЛИ',
             'Без вызовов модели и без чтения dev_gold. Это не новый замер точности или успешности заданий.',
             f'Исходный замер: {baseline}', f'Pipeline {PIPELINE_VERSION}; prompt {PROMPT_VERSION}', '']
    for record in records:
        remaining = dict(Counter(f['description'] for f in record['remaining_findings']))
        lines.append(f"{record['profile']} {record['code']}: ранее {record['baseline_status']}/{record['baseline_error']}; "
            f"ответов классификации {record['cached_classification_calls']}, извлечения {record['cached_extraction_calls']}; "
            f"кандидат валиден без нового вызова: {record['candidate_valid_without_model_repair']}; "
            f"ошибок схемы/классификации {len(record['graph_errors_after_repairs'])}/{len(record['classification_errors_after_repairs'])}; "
            f"осталось: {remaining}")
    (output / 'audit.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.baseline, args.output)
    print(json.dumps({'articles': len(result['records']), 'cached_valid_candidates': sum(r['candidate_valid_without_model_repair'] for r in result['records']),
                      'classification_errors_remaining': sum(len(r['classification_errors_after_repairs']) for r in result['records']),
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
