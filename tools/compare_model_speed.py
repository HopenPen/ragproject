"""Time four fresh, serial PDF processing jobs through the deployed application.

Example (from repository root, Docker and application must be running):
    python -m tools.compare_model_speed --pdf "E:/RAG/Предметная область 1/dev/D001.pdf" \
        --output runtime/benchmarks/model-speed-20261122

Temporarily overrides MODEL_ID for backend/worker, never edits .env. Restores the
original Compose configuration in finally. --resume observes the same job IDs;
--report-only rebuilds the report offline, without Docker or paid model calls.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

from tools.benchmark import (Api, STOP, collect_worker_metrics, sha, utc,
                             wait_job, write_json)


MODELS = ('openai/gpt-6-luna', 'deepseek/deepseek-v4.1-flash')
ORDER = ((0, 1), (1, 1), (1, 2), (0, 2))
REPO = Path(__file__).resolve().parents[1]
ACTIVE = ('queued', 'running', 'cancel_requested', 'pause_requested')


def docker(*args):
    result = subprocess.run(['docker', *args], cwd=REPO, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=180)
    if result.returncode:
        # Do not dump Docker configuration, environment or credentials.
        raise RuntimeError('Docker command failed: ' + ' '.join(args[:5]) +
                           '\n' + result.stderr[-1800:])
    return result.stdout


def worker_settings():
    fields = ('model_id', 'openai_base_url', 'page_batch_size', 'render_dpi',
              'classification_confidence_threshold', 'model_timeout', 'max_retries',
              'model_max_output_tokens', 'model_max_calls')
    code = ('import json; from app.config import settings; c=settings(); '
            f'print(json.dumps({{k:getattr(c,k) for k in {fields!r}}}))')
    return json.loads(docker('compose', 'exec', '-T', 'worker', 'python', '-c', code))


def assert_idle():
    code = ("import json; from app.db import Uow; from app.models.data import Job; "
            "from sqlalchemy import select; u=Uow(); u.__enter__(); "
            f"print(json.dumps([str(j.id) for j in u.session.scalars(select(Job).where(Job.status.in_({ACTIVE!r})))])); "
            "u.__exit__(None,None,None)")
    active = json.loads(docker('compose', 'exec', '-T', 'backend', 'python', '-c', code))
    if active:
        raise RuntimeError('Active processing jobs exist; refusing to restart services: ' + str(active))


def switch(api, model, overlay, original):
    assert_idle()
    overlay.write_text('services:\n  backend:\n    environment:\n      MODEL_ID: ' +
                       json.dumps(model) + '\n  worker:\n    environment:\n      MODEL_ID: ' +
                       json.dumps(model) + '\n', encoding='utf-8')
    docker('compose', '-f', str(REPO / 'compose.yaml'), '-f', str(overlay),
           'up', '-d', '--no-deps', '--no-build', 'backend', 'worker')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            config = api.json('GET', '/processing/configuration')
            if config['model_id'] == model:
                current = worker_settings()
                assert current == {**original, 'model_id': model}, 'Unexpected processing settings'
                return config
        except (RuntimeError, OSError, httpx.RequestError):
            pass
        time.sleep(2)
    raise TimeoutError('Services did not become ready with model ' + model)


def capture(output, job_id):
    # The API can expose final status just before Celery writes its final event.
    for _ in range(10):
        collect_worker_metrics(output)
        events = json.loads((output / 'worker_events.json').read_text(encoding='utf-8'))
        if any(e['job_id'] == job_id and e.get('status') in STOP for e in events):
            return
        time.sleep(1)
    raise RuntimeError('Missing worker timing event for ' + job_id)


def collect_published(api, folder, record):
    document = api.json('GET', '/documents/' + record['document_id'])
    publications = api.all('/corpora/' + record['corpus_id'] + '/publications')
    graphs = [api.json('GET', '/publications/' + pub['id'] + '/graph', params={'profile': 'solar-v1'})
              for pub in publications if 'solar-v1' in pub.get('current', {})]
    write_json(folder / 'published.json', {'document': document, 'publications': publications, 'graphs': graphs})


def report(output):
    state = json.loads((output / 'comparison.json').read_text(encoding='utf-8'))
    samples = []
    for sample in state['runs']:
        folder = output / sample['folder']
        if not (folder / 'state.json').exists():
            continue
        local = json.loads((folder / 'state.json').read_text(encoding='utf-8'))
        record = local['areas']['solar-v1']['documents']['D001']
        raw_path = folder / 'raw' / (record.get('job_id', '') + '.json')
        if not raw_path.exists():
            continue
        raw = json.loads(raw_path.read_text(encoding='utf-8'))
        calls, failures, result_ids = [], [], set()
        for item in raw['items']:
            progress = item['progress']
            calls += [{'key': key, **{k: v for k, v in call.items() if k != 'output'}}
                      for key, call in progress.get('outputs', {}).items()]
            failures += [{'key': key, **call} for key, call in progress.get('failed_calls', {}).items()]
            for call in progress.get('outputs', {}).values():
                graph = call.get('output', {})
                graph = graph.get('graph', graph)
                result_ids.update(r['result_id'] for r in graph.get('results', []))
        events_path = folder / 'worker_events.json'
        events = json.loads(events_path.read_text(encoding='utf-8')) if events_path.exists() else []
        item_ids = {i['id'] for i in raw['items']}
        events = [e for e in events if e['job_id'] == record['job_id'] and e['item_id'] in item_ids]
        worker_seconds = sum(e['elapsed_ms'] for e in events) / 1000 if events else None
        published_path = folder / 'published.json'
        published = json.loads(published_path.read_text(encoding='utf-8')) if published_path.exists() else None
        value = {**sample, 'job_id': record['job_id'], 'corpus_id': record['corpus_id'],
                 'status': record.get('status'), 'client_seconds': record.get('elapsed_seconds'),
                 'worker_seconds': worker_seconds,
                 'successful_model_calls': len(calls), 'failed_model_calls_with_usage': len(failures),
                 'model_seconds': sum(c.get('elapsed_ms', 0) for c in calls + failures) / 1000,
                 'classification_seconds': sum(c.get('elapsed_ms', 0) for c in calls + failures if c['key'].startswith('classify-')) / 1000,
                 'extraction_and_repair_seconds': sum(c.get('elapsed_ms', 0) for c in calls + failures if not c['key'].startswith('classify-')) / 1000,
                 'response_models': sorted({c.get('model', '') for c in calls + failures}),
                 'calls': calls, 'failed_calls': failures,
                 'result_ids_in_raw_outputs': len(result_ids),
                 'published_results': sum(len(g['graph']['results']) for g in published['graphs']) if published else None,
                 'published_solar_in_scope': [g['graph']['scope']['in_scope'] for g in published['graphs']] if published else None,
                 'uploaded_pdf': {k: published['document'][k] for k in ('sha256', 'page_count', 'byte_size')} if published else None,
                 'errors': [i.get('error') for i in raw['items'] if i.get('error')],
                 'classification': [i['progress'].get('outputs', {}).get('classify-final', {}).get('output') for i in raw['items']],
                 'versions': [{k: i['progress'].get(k) for k in ('model', 'pipeline_version', 'prompt_version', 'schema_version', 'rules_version')} for i in raw['items']],
                 'cached_application_outputs': sum(bool(c.get('reused_from_item')) for c in calls),
                 'reused_prepared_pages': sum(bool(p.get('reused')) for i in raw['items'] for p in i['progress'].get('pages', {}).values()),
                 'page_coverage': [i['progress'].get('coverage') for i in raw['items']],
                 'usage': {field: sum(c.get('usage', {}).get(field, 0) for c in calls + failures)
                           for field in ('input_tokens', 'output_tokens', 'total_tokens')},
                 'cached_input_tokens': sum(c.get('usage', {}).get('input_tokens_details', {}).get('cached_tokens', 0) for c in calls + failures),
                 'reasoning_tokens': sum(c.get('usage', {}).get('output_tokens_details', {}).get('reasoning_tokens', 0) for c in calls + failures)}
        samples.append(value)
    response_ids = [c['response_id'] for s in samples for c in s['calls'] + s['failed_calls'] if c.get('response_id')]
    environments = [json.loads((output / s['folder'] / 'worker_environment.json').read_text(encoding='utf-8')) for s in samples]
    verification = {
        'completed_samples': len(samples),
        'all_expected_samples_present': len(samples) == len(ORDER),
        'unique_response_ids': len(response_ids) == len(set(response_ids)),
        'no_application_output_replay': all(s['cached_application_outputs'] == 0 for s in samples),
        'fresh_prepared_pages': all(s['reused_prepared_pages'] == 0 for s in samples),
        'same_deployed_app': bool(environments) and all(e['app_sha256'] == environments[0]['app_sha256'] for e in environments),
        'same_image': bool(environments) and len({e['image_id'] for e in environments}) == 1,
        'same_processing_settings_except_model': all({k: v for k, v in e['settings'].items() if k != 'model_id'} ==
            {k: v for k, v in state['original_worker_settings'].items() if k != 'model_id'} for e in environments),
        'worker_models_match_requested': all(e['settings']['model_id'] == s['model'] for e, s in zip(environments, samples)),
        'same_uploaded_pdf': bool(samples) and all(s['uploaded_pdf'] and s['uploaded_pdf']['sha256'] == state['sha256'] and
            s['uploaded_pdf']['page_count'] == state['pages'] for s in samples),
    }
    aggregates = []
    for model in MODELS:
        group = [s for s in samples if s['model'] == model]
        succeeded = [s for s in group if s['status'] == 'succeeded']
        aggregates.append({'model': model, 'attempts': len(group), 'succeeded': len(succeeded),
                           'successful_mean_worker_seconds': statistics.mean(s['worker_seconds'] for s in succeeded)
                           if succeeded and all(s['worker_seconds'] is not None for s in succeeded) else None,
                           'successful_mean_model_seconds': statistics.mean(s['model_seconds'] for s in succeeded) if succeeded else None})
    metrics = {'pdf': state['pdf'], 'sha256': state['sha256'], 'pages': state['pages'],
               'samples': samples, 'aggregates': aggregates, 'verification': verification, 'restoration': state.get('restoration')}
    write_json(output / 'metrics.json', metrics)
    write_json(output / 'verification.json', verification)
    lines = ['СРАВНЕНИЕ СКОРОСТИ ОБРАБОТКИ PDF', '', f"PDF: {state['pdf']}",
             f"SHA-256: {state['sha256']}", f"Страниц: {state['pages']}",
             f"Начало (UTC): {state['started_at']}",
             'Порядок: Luna 1, DeepSeek 1, DeepSeek 2, Luna 2.',
             'Одинаковый конвейер, текст + изображения всех страниц, strict JSON.',
             'Каждая обработка: новый корпус и документ; сохранённые ответы приложения не использованы.',
             'Кеш провайдера не отключён; сведения о cached_tokens сохранены в raw ответах.',
             'Экспорт и перезапуск сервисов не входят во время обработки.',
             'Настройки рассуждений не заданы: используются значения провайдера по умолчанию.',
             'Предварительные короткие проверки совместимости исключены из этих времён.', '']
    lines.extend(['Настройки worker (кроме временно меняемой модели): ' + json.dumps(
        {k: v for k, v in state['original_worker_settings'].items() if k != 'model_id'}, ensure_ascii=False), ''])
    for s in samples:
        lines.extend([f"{s['model']} — запуск {s['repeat']}: {s['status']}",
                      f"  Worker: {s['worker_seconds']} с; от постановки до наблюдения завершения: {s['client_seconds']} с",
                      f"  Вызовы модели: {s['model_seconds']} с; успешных: {s['successful_model_calls']}; неуспешных с usage: {s['failed_model_calls_with_usage']}",
                      f"  Классификация: {s['classification_seconds']} с; извлечение и исправления: {s['extraction_and_repair_seconds']} с",
                      f"  Ошибки: {s['errors']}; уникальных result ID в сырых ответах: {s['result_ids_in_raw_outputs']}",
                      f"  Опубликованных результатов: {s['published_results']}; статья в профиле Solar: {s['published_solar_in_scope']}",
                      f"  Покрытие страниц: {s['page_coverage']}",
                      f"  Модель в ответах: {s['response_models']}",
                      f"  Токены: {s['usage']}", f"  Job ID: {s['job_id']}", ''])
        for failed in s['failed_calls']:
            lines.append(f"  Незавершённый вызов {failed['key']}: {failed.get('error')}; причина провайдера: {failed.get('reason')}; "
                         f"output_tokens={failed.get('usage', {}).get('output_tokens')}; "
                         f"reasoning_tokens={failed.get('usage', {}).get('output_tokens_details', {}).get('reasoning_tokens')}; "
                         f"elapsed_ms={failed.get('elapsed_ms')}; response_id={failed.get('response_id')}")
    lines.extend(['СРЕДНИЕ ТОЛЬКО ПО УСПЕШНЫМ ОБРАБОТКАМ'])
    for a in aggregates:
        lines.append(f"{a['model']}: успешных {a['succeeded']}/{a['attempts']}; среднее worker {a['successful_mean_worker_seconds']} с; модель {a['successful_mean_model_seconds']} с")
    if all(a['succeeded'] == 2 and a['successful_mean_worker_seconds'] for a in aggregates) and all(s['published_solar_in_scope'] == [True] and s['published_results'] for s in samples):
        luna, deepseek = [a['successful_mean_worker_seconds'] for a in aggregates]
        lines.append(f'Отношение среднего времени Luna / DeepSeek: {luna/deepseek:.3f}.')
    else:
        lines.append('Для сравнения полного извлечения нужны два успешных запуска каждой модели с опубликованными результатами в профиле Solar; время до ошибки или пропуска извлечения не считается ускорением.')
    lines.extend(['', 'Два запуска на одном PDF — локальное наблюдение, не статистически надёжный рейтинг моделей.',
                  'Число результатов — диагностика объёма; точность относительно dev_gold здесь не измеряется.',
                  'elapsed_ms вызова включает сериализацию, сеть, очередь провайдера, генерацию и внутренние повторы.',
                  'Worker elapsed — фактический интервал выполнения Celery task из структурированных логов.',
                  'Client elapsed включает ожидание очереди и погрешность опроса до 2 с.',
                  'Учёт токенов включает сохранённые успешные ответы и ошибки с usage; транспортные ошибки могут быть не учтены.',
                  f'Проверки сопоставимости: {verification}',
                  f"Восстановление конфигурации: {state.get('restoration', 'ещё не завершено')}"])
    (output / 'comparison.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    return metrics


def run(args):
    output = args.output.resolve()
    if args.report_only:
        report(output)
        return
    if args.collect_published:
        api = Api(args.url)
        try:
            state = json.loads((output / 'comparison.json').read_text(encoding='utf-8'))
            for sample in state['runs']:
                folder = output / sample['folder']
                if (folder / 'state.json').exists():
                    local = json.loads((folder / 'state.json').read_text(encoding='utf-8'))
                    record = local['areas']['solar-v1']['documents']['D001']
                    if record.get('status') in STOP:
                        collect_published(api, folder, record)
            report(output)
        finally:
            api.client.close()
        return
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / 'comparison.json'
    api = Api(args.url)
    overlay = output / 'compose.models.yaml'
    changed = False
    try:
        if state_path.exists():
            if not args.resume:
                raise ValueError('Existing comparison: use --resume or --report-only')
            state = json.loads(state_path.read_text(encoding='utf-8'))
            assert sha(args.pdf) == state['sha256'], 'PDF changed'
        else:
            import fitz
            from app.config import settings
            original = worker_settings()
            config = api.json('GET', '/processing/configuration')
            assert original['model_id'] == config['model_id'] == settings().model_id, 'Unexpected pre-existing model override'
            assert_idle()
            with fitz.open(args.pdf) as pdf:
                pages = len(pdf)
            state = {'started_at': utc(), 'id': uuid4().hex, 'pdf': str(args.pdf.resolve()),
                     'sha256': sha(args.pdf), 'pages': pages, 'original_configuration': config,
                     'original_worker_settings': original,
                     'runs': [{'model': MODELS[m], 'repeat': n, 'folder': f'{i+1:02d}-{MODELS[m].split("/")[-1]}-{n}'}
                              for i, (m, n) in enumerate(ORDER)]}
            write_json(state_path, state)
        for sample in state['runs']:
            folder = output / sample['folder']
            local_file = folder / 'state.json'
            if local_file.exists():
                local = json.loads(local_file.read_text(encoding='utf-8'))
                record = local['areas']['solar-v1']['documents']['D001']
                if record.get('status') in STOP and (folder / 'worker_events.json').exists():
                    continue
            else:
                local = {'started_at': utc(), 'areas': {'solar-v1': {'documents': {'D001': {}}}}}
                record = local['areas']['solar-v1']['documents']['D001']
            if worker_settings()['model_id'] != sample['model']:
                changed = True
                local['configuration'] = switch(api, sample['model'], overlay, state['original_worker_settings'])
            else:
                local['configuration'] = api.json('GET', '/processing/configuration')
            if not record.get('corpus_id'):
                corpus = api.json('POST', '/corpora', json={'name': f"Сравнение скорости {sample['model']} #{sample['repeat']} {state['id'][:8]}", 'split': 'dev'})
                record['corpus_id'] = corpus['id']
                write_json(local_file, local)
            if not record.get('document_id'):
                assert sha(args.pdf) == state['sha256'], 'PDF changed between runs'
                with args.pdf.open('rb') as stream:
                    doc = api.json('POST', f"/corpora/{record['corpus_id']}/documents",
                                   data={'publication_code': 'D001'}, files={'file': (args.pdf.name, stream, 'application/pdf')})
                assert doc['sha256'] == state['sha256'] and doc['page_count'] == state['pages'], 'Uploaded PDF differs'
                record.update(document_id=doc['id'], sha256=state['sha256'], pages=doc['page_count'])
                write_json(local_file, local)
            if not record.get('job_id'):
                record['submitted_at'] = utc()
                write_json(local_file, local)
                record['job_id'] = api.json('POST', f"/corpora/{record['corpus_id']}/jobs", json={'kind': 'process', 'all_documents': True},
                                           headers={'Idempotency-Key': state['id'] + '-' + sample['folder']})['job_id']
                write_json(local_file, local)
            print(json.dumps({'event': 'run_started', **sample, 'job_id': record['job_id']}), flush=True)
            wait_job(api, record, folder, local, 2, args.timeout)
            capture(folder, record['job_id'])  # Must happen BEFORE restarting the worker.
            collect_published(api, folder, record)
            sample['status'] = record['status']
            write_json(state_path, state)
            report(output)
            print(json.dumps({'event': 'run_finished', **sample, 'seconds': record['elapsed_seconds']}), flush=True)
        state['finished_at'] = utc()
        write_json(state_path, state)
    finally:
        if changed or (state_path.exists() and args.resume):
            # Never interrupt an in-flight scientific processing job on restoration.
            assert_idle()
            docker('compose', 'up', '-d', '--no-deps', '--no-build', 'backend', 'worker')
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    if api.json('GET', '/processing/configuration')['model_id'] == state['original_configuration']['model_id']:
                        assert worker_settings() == state['original_worker_settings']
                        state['restoration'] = {'at': utc(), 'model_id': state['original_configuration']['model_id'], 'verified': True}
                        write_json(state_path, state)
                        break
                except (RuntimeError, OSError, httpx.RequestError):
                    pass
                time.sleep(2)
            else:
                raise TimeoutError('Original model was not restored')
        api.client.close()
        if state_path.exists():
            report(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, default=Path('E:/RAG/Предметная область 1/dev/D001.pdf'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='http://localhost')
    parser.add_argument('--timeout', type=float, default=2400)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--collect-published', action='store_true', help='Read final graphs and PDF hashes via API; no model calls or Docker restarts')
    run(parser.parse_args())
