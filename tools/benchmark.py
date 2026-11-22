r"""Reproducible dev benchmark against the running application (never sends gold to the model).

Run: python -m tools.benchmark --root E:\RAG --output runtime/benchmarks/luna-dev
Resume after interruption: add --resume. Recompute reports without LLM calls: add --score-only.
Authentication is read from ADMIN_EMAIL / ADMIN_PASSWORD or the local .env, never recorded.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx


STOP = {'succeeded', 'partially_succeeded', 'failed', 'cancelled',
        'blocked_external_configuration', 'waiting_review', 'paused'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def collect_worker_metrics(output):
    """Optional Docker evidence, read only; stores only our job events and whitelisted settings."""
    state = json.loads((output / 'state.json').read_text(encoding='utf-8'))
    job_ids = {d['job_id'] for area in state['areas'].values()
               for d in [*area['documents'].values(), area.get('export', {})] if 'job_id' in d}
    logs = subprocess.run(['docker', 'compose', 'logs', '--no-color', '--no-log-prefix', '--timestamps',
                           '--since', state['started_at'], 'worker'], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', check=True, timeout=120)
    events = []
    for line in logs.stdout.splitlines():
        begin = line.find('{')
        if begin < 0:
            continue
        try:
            event = json.loads(line[begin:])
        except ValueError:
            continue
        if event.get('event') == 'job_item_finished' and event.get('job_id') in job_ids:
            events.append({'docker_timestamp': line[:begin].strip(), **event})
    write_json(output / 'worker_events.json', events)
    snippet = (
        "import json,sys,platform,hashlib; from pathlib import Path; from app.config import settings; "
        "c=settings(); print(json.dumps({'python':sys.version,'platform':platform.platform(),"
        "'settings':{k:getattr(c,k) for k in ('model_id','openai_base_url','classification_confidence_threshold',"
        "'page_batch_size','render_dpi','model_timeout','max_retries','model_max_output_tokens','model_max_calls')},"
        "'app_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('app').rglob('*.py'))}}))"
    )
    metadata = subprocess.run(['docker', 'compose', 'exec', '-T', 'worker', 'python', '-c', snippet],
                              capture_output=True, text=True, encoding='utf-8', check=True, timeout=60)
    value = json.loads(metadata.stdout)
    container = subprocess.check_output(['docker', 'compose', 'ps', '-q', 'worker'], text=True).strip()
    image = subprocess.check_output(['docker', 'inspect', '--format',
                                     '{{.Image}} {{.State.StartedAt}}', container], text=True).strip().split()
    command = json.loads(subprocess.check_output(['docker', 'inspect', '--format',
                                                  '{{json .Config.Cmd}}', container], text=True))
    value.update(container_id=container, image_id=image[0], container_started_at=image[1],
                 worker_command=command, collected_at=utc())
    write_json(output / 'worker_environment.json', value)
    log(output, 'worker_evidence_collected', events=len(events))


def inventory(root):
    import fitz
    result = []
    for i, profile in ((1, 'solar-v1'), (2, 'rag-v1')):
        area = root / f'Предметная область {i}'
        pdfs = []
        for path in sorted((area / 'dev').glob('*.pdf')):
            with fitz.open(path) as pdf:
                count = len(pdf)
            pdfs.append({'code': path.stem, 'path': str(path.resolve()), 'sha256': sha(path),
                         'bytes': path.stat().st_size, 'pages': count})
        gold = [{'name': p.name, 'path': str(p.resolve()), 'sha256': sha(p), 'rows': len(rows(p))}
                for p in sorted((area / 'dev_gold').glob('*.csv'))]
        publications = rows(area / 'dev_gold' / 'publications.csv')
        pdf_codes = [p['code'] for p in pdfs]
        gold_codes = [r['publication_id'] for r in publications]
        if not pdfs or len(set(gold_codes)) != len(gold_codes) or set(pdf_codes) != set(gold_codes):
            raise ValueError(f'{profile}: PDF codes and gold publications do not match')
        required = {'publications', 'results', 'issues'} | (
            {'devices', 'materials', 'measurements', 'layers'} if i == 1
            else {'configurations', 'datasets', 'tasks', 'experiments'})
        if required != {Path(p['name']).stem for p in gold}:
            raise ValueError(f'{profile}: incomplete/unexpected gold tables')
        result.append({'profile': profile, 'root': str(area.resolve()), 'pdfs': pdfs, 'gold': gold})
    overlap = {p['sha256'] for p in result[0]['pdfs']} & {p['sha256'] for p in result[1]['pdfs']}
    if overlap:
        raise ValueError('Domains contain duplicate PDFs; verify source folders before measuring')
    return result


def snapshot_gold(output, inputs):
    """Keep the scoring reference reproducible even if the user later updates source folders."""
    for area in inputs:
        target = output / 'gold' / area['profile']
        target.mkdir(parents=True, exist_ok=True)
        for entry in area['gold']:
            path = target / entry['name']
            if not path.exists():
                if sha(Path(entry['path'])) != entry['sha256']:
                    raise ValueError('Gold changed before reference snapshot')
                shutil.copy2(entry['path'], path)
            if sha(path) != entry['sha256']:
                raise ValueError('Frozen gold hash mismatch')


class Api:
    def __init__(self, url):
        from app.config import settings
        config = settings()
        self.email, self.password = config.admin_email, config.admin_password.get_secret_value()
        self.client = httpx.Client(base_url=url, timeout=120, trust_env=False)
        self.login()

    def login(self):
        response = self.client.post('/api/v1/auth/login', json={'email': self.email, 'password': self.password})
        response.raise_for_status()
        self.client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']

    def request(self, method, path, **kwargs):
        response = self.client.request(method, '/api/v1' + path, **kwargs)
        if response.status_code == 401:
            self.login()
            response = self.client.request(method, '/api/v1' + path, **kwargs)
        if response.status_code >= 400:
            # Never include request headers/credentials or uploaded contents in a diagnostic.
            raise RuntimeError(f'{method} {path}: HTTP {response.status_code}: {response.text[:1000]}')
        return response

    def json(self, method, path, **kwargs):
        return self.request(method, path, **kwargs).json()

    def all(self, path):
        result, page = [], 1
        while True:
            data = self.json('GET', path, params={'page': page, 'page_size': 200})
            result.extend(data['items'])
            if len(data['items']) < 200:
                return result
            page += 1


def log(output, kind, **value):
    entry = {'at': utc(), 'event': kind, **value}
    with (output / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    print(json.dumps(entry, ensure_ascii=True), flush=True)


def wait_job(api, record, output, state, poll, timeout):
    started = time.perf_counter()
    previous = None
    while True:
        job = api.json('GET', '/jobs/' + record['job_id'])
        status = job['status']
        if status != previous:
            log(output, 'job_status', job_id=record['job_id'], status=status)
            previous = status
        if status == 'running' and not record.get('running_first_observed_at'):
            record['running_first_observed_at'] = utc()
            write_json(output / 'state.json', state)
        if status in STOP:
            record['status'] = status
            record['observed_finished_at'] = utc()
            # After a process interruption, wall clock includes the interruption; flag it explicitly.
            record['elapsed_seconds'] = (datetime.fromisoformat(record['observed_finished_at']) -
                                         datetime.fromisoformat(record['submitted_at'])).total_seconds()
            record['items'] = api.all('/jobs/' + record['job_id'] + '/items')
            write_json(output / 'raw' / (record['job_id'] + '.json'), {'job': job, 'items': record['items']})
            # Raw outputs belong in the raw evidence file, not the frequently rewritten state.
            record['items'] = [{k: v for k, v in item.items() if k != 'progress'} |
                               {'progress': {k: v for k, v in item['progress'].items() if k != 'outputs'},
                                'successful_model_calls': len(item['progress'].get('outputs', {}))}
                               for item in record['items']]
            write_json(output / 'state.json', state)
            return job
        if time.perf_counter() - started > timeout:
            raise TimeoutError(f'Job {record["job_id"]} still active; resume with --resume (no duplicate calls)')
        time.sleep(poll)


def enqueue_and_wait(api, corpus_id, payload, record, key, output, state, args):
    if record.get('status') in STOP:
        return
    if not record.get('submitted_at'):
        record['submitted_at'] = utc()
        write_json(output / 'state.json', state)
    if 'job_id' not in record:
        job = api.json('POST', f'/corpora/{corpus_id}/jobs', json=payload,
                       headers={'Idempotency-Key': key})
        record['job_id'] = job['job_id']
        write_json(output / 'state.json', state)
    elif args.resume:
        record['resumed_observation'] = True
    wait_job(api, record, output, state, args.poll, args.job_timeout)


def run(args):
    output = args.output.resolve()
    if args.score_only:
        if args.collect_worker_metrics:
            collect_worker_metrics(output)
        from tools.quality_metrics import report
        report(output)
        return
    current_inputs = inventory(args.root.resolve())
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / 'state.json'
    if state_path.exists():
        if not args.resume:
            raise ValueError('Output already contains a run; use --resume, --score-only or a new output directory')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['inputs'] != current_inputs:
            raise ValueError('Source/gold changed since run started; use a new output directory')
    else:
        state = {'version': 1, 'run_id': uuid4().hex, 'started_at': utc(), 'inputs': current_inputs,
                 'base_url': args.url, 'poll_seconds': args.poll, 'areas': {}, 'manual_changes': False}
        state['source'] = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                           'working_tree': subprocess.check_output(['git', 'status', '--short'], text=True).strip(),
                           'app_sha256': {str(p): sha(p) for p in sorted(Path('app').rglob('*.py'))}}
        from app.config import settings
        c = settings()
        state['local_settings'] = {k: getattr(c, k) for k in (
            'model_id', 'openai_base_url', 'classification_confidence_threshold', 'page_batch_size',
            'render_dpi', 'model_timeout', 'max_retries', 'model_max_output_tokens', 'model_max_calls')}
        write_json(state_path, state)
        (output / 'reproduce').mkdir(exist_ok=True)
        shutil.copy2(__file__, output / 'reproduce' / 'benchmark.py')
    api = Api(args.url)
    snapshot_gold(output, state['inputs'])
    config = api.json('GET', '/processing/configuration')
    if not config['configured']:
        raise ValueError('Model is not configured')
    if state.get('configuration') and config != state['configuration']:
        raise ValueError('Running service settings changed; do not mix experiments')
    state['configuration'] = config
    write_json(state_path, state)
    for data in current_inputs:
        profile = data['profile']
        area = state['areas'].setdefault(profile, {'documents': {}, 'started_at': utc()})
        area_dir = output / profile
        area_dir.mkdir(exist_ok=True)
        name = f'benchmark_{profile}_{state["run_id"][:10]}'
        if 'corpus_id' not in area:
            # Recover an acknowledged POST if the client was interrupted before saving its response.
            existing = [c for c in api.all('/corpora') if c['name'] == name]
            corpus = existing[0] if existing else api.json('POST', '/corpora', json={
                'name': name, 'split': 'dev',
                'description': 'Automatic benchmark; no gold supplied to model; run ' + state['run_id']})
            area['corpus_id'] = corpus['id']
            write_json(state_path, state)
        for source in data['pdfs']:
            code = source['code']
            record = area['documents'].setdefault(code, {'code': code, 'pages': source['pages']})
            if 'document_id' not in record:
                start = time.perf_counter()
                with Path(source['path']).open('rb') as stream:
                    doc = api.json('POST', f'/corpora/{area["corpus_id"]}/documents',
                                   data={'publication_code': code}, files={'file': (code + '.pdf', stream, 'application/pdf')})
                if doc['sha256'] != source['sha256']:
                    raise ValueError('Uploaded PDF hash mismatch')
                record.update(document_id=doc['id'], upload_seconds=time.perf_counter() - start)
                write_json(state_path, state)
            log(output, 'article', profile=profile, code=code)
            enqueue_and_wait(api, area['corpus_id'], {'kind': 'process', 'document_ids': [record['document_id']]},
                             record, state['run_id'] + ':' + profile + ':' + code, output, state, args)
            log(output, 'article_finished', profile=profile, code=code, status=record['status'],
                seconds=round(record['elapsed_seconds'], 3))
        export = area.setdefault('export', {})
        enqueue_and_wait(api, area['corpus_id'], {'kind': 'export', 'all_documents': True,
                         'target_profiles': [profile], 'allow_incomplete': True,
                         'check_sources': True, 'run_external_checker': False}, export,
                         state['run_id'] + ':' + profile + ':export', output, state, args)
        if export['status'] != 'succeeded':
            raise RuntimeError(f'{profile}: export failed; diagnostics in raw/{export["job_id"]}.json')
        archive = area_dir / 'export.zip'
        if not archive.exists():
            start = time.perf_counter()
            archive.write_bytes(api.request('GET', '/jobs/' + export['job_id'] + '/download').content)
            export['download_seconds'] = time.perf_counter() - start
        # Extract only the known CSV/JSON leaf names from the application's immutable export.
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                path = Path(name)
                if len(path.parts) == 2 and path.parts[0] == 'submission' and path.suffix in ('.csv', '.json'):
                    target = area_dir / 'submission' / path.name
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(bundle.read(name))
        area['finished_at'] = utc()
        write_json(state_path, state)
    state['finished_at'] = utc()
    write_json(state_path, state)
    if args.collect_worker_metrics:
        collect_worker_metrics(output)
    from tools.quality_metrics import report
    report(output)
    log(output, 'finished', report=str(output / 'metrics.txt'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd().parent)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='http://localhost')
    parser.add_argument('--poll', type=float, default=2.)
    parser.add_argument('--job-timeout', type=float, default=7200.)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--score-only', action='store_true')
    parser.add_argument('--collect-worker-metrics', action='store_true',
                        help='Read Docker worker duration events and safe deployed settings (requires Docker access)')
    args = parser.parse_args()
    if args.poll <= 0 or args.job_timeout <= 0:
        parser.error('poll and timeout must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    lock = args.output / '.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode('ascii'))
        run(args)
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
