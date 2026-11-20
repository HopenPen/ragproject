import csv
import io
import json
import tempfile
import zipfile
from pathlib import Path
from app.domain import PROFILES, PIPELINE_VERSION, RULES_VERSION, now
from app.profiles import csv_columns, passport
from app.services.validation import validate


def cell(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return ';'.join(str(v) for v in value)
    return str(value)


def csv_bytes(columns, rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows({k: cell(row.get(k)) for k in columns} for row in rows)
    return output.getvalue().encode('utf-8')


def export_rows(snapshot, profile, validations):
    rows = {table: [] for table in csv_columns(profile)}
    for entry in snapshot['entries']:
        code = entry['document']['publication_code']
        rev = entry['graphs'].get(profile)
        cls = entry['classification']
        graph = rev['graph'] if rev else None
        biblio = graph['bibliography'] if graph else cls['decision']['bibliography'] if cls else {}
        if graph:
            scope = graph['scope']
        elif cls:
            label = profile.split('-')[0]
            scope = cls['decision'][label] if label in cls['decision']['labels'] else {'in_scope': False, 'exclusion_reason': 'not_target_domain'}
        else:
            scope = {'in_scope': None, 'exclusion_reason': None}
        rows['publications'].append({'publication_id': code, **biblio, **scope})
        if graph:
            for table in rows:
                if table not in ('publications', 'issues'):
                    rows[table] += [{'publication_id': code, **r} for r in graph[table]]
            report = validations.get(rev['id'], {})
            rows['issues'] += [{'publication_id': code, 'issue_id': f'I{i+1}', 'record_ids': f.get('record_ids'),
                               'check_name': f['rule'], 'description': f['description'],
                               'source_page': f.get('source_page'), 'source_fragment': f.get('source_fragment')} for i, f in enumerate(report.get('issues', []))]
    return rows


class Exporter:
    def __init__(self, storage, config):
        self.storage, self.config = storage, config

    def run(self, job):
        snapshot = job['input']['snapshot']
        profiles = job['input'].get('target_profiles') or list(PROFILES)
        reports, validations = [], {}
        for entry in snapshot['entries']:
            for profile, rev in entry['graphs'].items():
                result = validate(rev['graph'], entry['document']['page_count'],
                                  entry['pages'] if job['input'].get('check_sources', True) else None, entry['artifacts'])
                validations[rev['id']] = result
                reports.append({'publication_id': entry['publication_id'], 'revision_id': rev['id'], 'profile': profile, 'validation': result})
        report = {'snapshot_created_at': snapshot['created_at'], 'publications': reports, 'omissions': snapshot['omissions'],
                  'external_checkers': {}, 'scientific_review': 'requires_human_confirmation'}
        passports = {p: passport(p) for p in profiles}
        manifest = {'created_at': now().isoformat(), 'snapshot_created_at': snapshot['created_at'],
                    'job_id': job['id'], 'pipeline_version': PIPELINE_VERSION, 'rules_version': RULES_VERSION,
                    'allow_incomplete': job['input'].get('allow_incomplete', False), 'omissions': snapshot['omissions'],
                    'profiles': profiles, 'documents': []}
        for entry in snapshot['entries']:
            doc, cls = entry['document'], entry['classification']
            manifest['documents'].append({'document_id': doc['id'], 'code': doc['publication_code'], 'original_filename': doc['original_filename'],
                                          'sha256': doc['sha256'], 'classification_revision': cls['id'] if cls else None,
                                          'revisions': {p: rev['id'] for p, rev in entry['graphs'].items()},
                                          'runs': {p: rev['run_id'] for p, rev in entry['graphs'].items()},
                                          'coverage': [{'page': p['number'], 'status': p['coverage'], 'engine': p['engine']} for p in entry['pages']],
                                          'model': self.run_model(entry)})
        files = {}
        for profile in profiles:
            tables = export_rows(snapshot, profile, validations)
            columns = csv_columns(profile)
            prefix = 'submission/' if len(profiles) == 1 else profile + '/submission/'
            for table, rows in tables.items():
                files[prefix + table + '.csv'] = csv_bytes(columns[table], rows)
            if profile == 'rag-v1':
                status = {'status': 'not_available_for_profile'}
            elif not job['input'].get('run_external_checker', True):
                status = {'status': 'disabled_by_request'}
            elif not self.config.external_checker_path or not self.config.external_checker_path.is_file():
                status = {'status': 'blocked_external_configuration', 'reason': 'External solar checker mount is missing'}
            else:
                # The original checker is an explicitly configured read-only file.
                from tools.check_submission import run_checker
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    sub, pdf = root/'submission', root/'pdf'
                    sub.mkdir(); pdf.mkdir()
                    for table, rows in tables.items():
                        (sub/(table+'.csv')).write_bytes(csv_bytes(columns[table], rows))
                    for entry in snapshot['entries']:
                        doc = entry['document']
                        (pdf/(doc['publication_code']+'.pdf')).write_bytes(self.storage.get(doc['storage_key']))
                    status = run_checker(self.config.external_checker_path, sub, pdf)
            report['external_checkers'][profile] = status
            files[prefix+'data_passport.json'] = json.dumps(passports[profile], ensure_ascii=False, indent=2).encode()
        manifest['external_checkers'] = report['external_checkers']
        for profile in profiles:
            prefix = 'submission/' if len(profiles) == 1 else profile+'/submission/'
            files[prefix+'manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
            files[prefix+'validation_report.json'] = json.dumps(report, ensure_ascii=False, indent=2).encode()
        if len(profiles) > 1:
            files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        result = {'report': report, 'passport': passports, 'manifest': manifest}
        if job['kind'] == 'export':
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, blob in files.items():
                    archive.writestr(name, blob)
            key = f'jobs/{job["id"]}/export.zip'
            self.storage.put(key, output.getvalue(), 'application/zip')
            result['storage_key'] = key
        return result

    def run_model(self, entry):
        # Source run manifests are registered artifacts, not an invented model name.
        return [{'artifact_id': a['id'], **a['details']} for a in entry['artifacts'] if a['kind'] == 'run_manifest']
