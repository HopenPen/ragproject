"""Bounded source-backed test of the production repair step on saved benchmark candidates.

Never updates the database or original benchmark. Does not read dev_gold.
The caller must explicitly opt into paid calls with --max-calls N (default 0).
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
import fitz
from app.config import settings
from app.domain import Error, PIPELINE_VERSION, PROMPT_VERSION
from app.provider import ResponsesModel
from app.services.pipeline import Runner
from tools.audit_model_outputs import read


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


class PageRenders:
    def __init__(self, pdf, pages, dpi):
        self.pdf, self.dpi = pdf, dpi
        self.numbers = {p['image_key']: p['number'] for p in pages}

    def get(self, key):
        return self.pdf[self.numbers[key]-1].get_pixmap(dpi=self.dpi, alpha=False).tobytes('png')


class RepairRunner(Runner):
    def checkpoint(self, item_id, token, progress, stage, check_cancel=True):
        # Standalone repair lab: persist actual raw responses; never impersonate a production job.
        write(self.output / (item_id + '.progress.json'), progress)

    def model_call(self, item_id, token, progress, key, purpose, schema, pages, context):
        if key not in progress.get('outputs', {}):
            if self.calls >= self.max_calls:
                raise Error(422, 'repair_call_budget', 'Explicit standalone model-call budget exhausted')
            self.calls += 1
            print(json.dumps({'article': item_id, 'call': key, 'new_call': self.calls}), flush=True)
        return super().model_call(item_id, token, progress, key, purpose, schema, pages, context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-calls', type=int, default=0)
    parser.add_argument('--articles', nargs='*')
    args = parser.parse_args()
    if not 0 <= args.max_calls <= 16:
        parser.error('max-calls must be 0..16')
    if args.output.resolve() == args.baseline.resolve() or args.baseline.resolve() in args.output.resolve().parents:
        parser.error('output must be separate from the baseline')
    state, audit = read(args.baseline / 'state.json'), read(args.audit / 'audit.json')
    entries = {}
    for area in state['areas'].values():
        for e in read(args.baseline / 'raw' / (area['export']['job_id'] + '.json'))['job']['input']['snapshot']['entries']:
            entries[e['document']['id']] = e
    paths = {(area['profile'], pdf['code']): pdf for area in state['inputs'] for pdf in area['pdfs']}
    config = settings()
    runner = RepairRunner(None, None, ResponsesModel(config), config)
    runner.output, runner.calls, runner.max_calls = args.output, 0, args.max_calls
    result = {'kind': 'targeted_repair_validation_not_new_accuracy_benchmark', 'model': config.model_id,
              'pipeline_version': PIPELINE_VERSION, 'prompt_version': PROMPT_VERSION,
              'code_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in
                  ('app/services/pipeline.py', 'app/services/model_candidates.py', 'app/provider.py', 'tools/repair_saved_candidates.py')},
              'articles': []}
    for record in audit['records']:
        profile, code = record['profile'], record['code']
        name = profile + '_' + code
        if args.articles and profile + ':' + code not in args.articles:
            continue
        if not record['remaining_findings']:
            continue
        pdf = paths[(profile, code)]
        data = Path(pdf['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != pdf['sha256']:
            raise ValueError('Original PDF changed after baseline')
        entry = entries[state['areas'][profile]['documents'][code]['document_id']]
        # Public API snapshots redact S3 keys. Render the verified original PDF locally.
        for page in entry['pages']:
            page['image_key'] = str(page['number'])
        saved = read(args.audit / 'candidates' / profile / (code + '.json'))
        progress_file = args.output / (name + '.progress.json')
        progress = read(progress_file) if progress_file.exists() else {}
        started = time.perf_counter()
        outcome = {'profile': profile, 'code': code, 'pdf_sha256': pdf['sha256'], 'original_results': len(saved['graph']['results'])}
        with fitz.open(stream=data, filetype='pdf') as document:
            runner.storage = PageRenders(document, entry['pages'], config.render_dpi)
            try:
                graph = runner.repair_candidate(name, 'standalone-no-database', progress, profile, saved['graph'], saved['classification'], entry['pages'], entry['artifacts'])
                write(args.output / (name + '.graph.json'), graph)
                outcome.update(status='valid_candidate', results=len(graph['results']))
            except Error as exc:
                outcome.update(status='failed', error=exc.code, details=exc.details)
            except Exception as exc:
                # Do not log response bodies, HTTP headers or settings.
                outcome.update(status='failed', error=type(exc).__name__)
        outcome.update(elapsed_seconds=time.perf_counter()-started, calls_recorded=len(progress.get('outputs', {})),
                       usage=progress.get('usage', {}), repairs=progress.get('repairs', {}))
        result['articles'].append(outcome)
        write(args.output / 'repair_report.json', result)
        print(json.dumps({k: v for k, v in outcome.items() if k not in ('details', 'repairs')}, ensure_ascii=True), flush=True)
    print(json.dumps({'new_calls': runner.calls, 'valid_candidates': sum(a['status'] == 'valid_candidate' for a in result['articles']),
                      'tested_candidates': len(result['articles'])}), flush=True)


if __name__ == '__main__':
    main()
