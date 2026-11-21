# Назначение файла: init/keys/gateway/import/evaluate и согласованный backup/empty restore.
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import zipfile
from decimal import Decimal
from app.config import settings
from app.domain import now, decimal_value, Error


def render_gateway(config, output):
    from app.routes import auth, documents, jobs, catalog
    template = json.loads(Path('infra/krakend.json.tmpl').read_text())
    secret = config.gateway_secret.get_secret_value()
    if len(secret) < 32:
        raise ValueError('GATEWAY_SECRET must have at least 32 characters')
    endpoints = []
    public = {'/api/v1/auth/login', '/api/v1/auth/refresh', '/api/v1/auth/logout'}
    def query_params(dependency):
        return [p.alias for p in dependency.query_params] + [p for d in dependency.dependencies for p in query_params(d)]
    for router in (auth.router, documents.router, jobs.router, catalog.router):
        for route in router.routes:
            for method in sorted(route.methods):
                if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                    continue
                backend = 'auth' if router is auth.router else 'backend'
                entry = {'endpoint': route.path, 'method': method, 'output_encoding': 'no-op',
                    'input_headers': ['Authorization', 'Content-Type', 'Accept', 'If-Match', 'Idempotency-Key', 'X-Request-ID', 'X-Real-IP', 'X-User-ID', 'X-User-Role'],
                    'input_query_strings': sorted(set(query_params(route.dependant))),
                    'backend': [{'host': [f'http://{backend}:8000'], 'url_pattern': route.path, 'method': method, 'encoding': 'no-op',
                       'extra_config': {'modifier/martian': {'header.Modifier': {'scope': ['request'], 'name': 'X-Gateway-Credential', 'value': secret}}}}]}
                if route.path not in public:
                    roles = ['viewer', 'editor', 'admin']
                    if route.path.startswith('/api/v1/users'):
                        roles = ['admin']
                    elif backend == 'backend' and method != 'GET' and not route.path.endswith('/comparisons'):
                        roles = ['editor', 'admin']
                    entry['extra_config'] = {'auth/validator': {'alg': 'RS256', 'jwk_local_path': '/public-keys/jwks.json',
                        # KrakenD 2.9 requires this flag for a mounted local JWK too; no HTTP key URL is configured.
                        'disable_jwk_security': True,
                        'issuer': config.jwt_issuer, 'audience': [config.jwt_audience], 'roles_key': 'roles', 'roles': roles,
                        'cache': False, 'propagate_claims': [['sub', 'X-User-ID'], ['role', 'X-User-Role']]}}
                endpoints.append(entry)
    template['endpoints'] = endpoints
    if config.allowed_origins:
        template['extra_config'] = {'security/cors': {'allow_origins': config.allowed_origins,
            'allow_methods': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
            'allow_headers': ['Authorization', 'Content-Type', 'If-Match', 'Idempotency-Key'],
            'expose_headers': ['ETag', 'Idempotency-Key', 'Content-Disposition', 'X-Request-ID'], 'allow_credentials': False}}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = output.with_suffix('.new')
    temp.write_text(json.dumps(template), encoding='utf-8')
    temp.chmod(0o640)
    temp.replace(output)
    return len(endpoints)


def bootstrap(path):
    if path.exists():
        raise ValueError('Refusing to overwrite an existing .env')
    db, rabbit = secrets.token_hex(24), secrets.token_hex(24)
    values = {'POSTGRES_PASSWORD': db, 'DATABASE_URL': f'postgresql+psycopg://science:{db}@postgres:5432/science',
              'RABBITMQ_DEFAULT_PASS': rabbit, 'RABBITMQ_URL': f'amqp://science:{rabbit}@rabbitmq:5672/science',
              'S3_ACCESS_KEY': secrets.token_hex(10), 'S3_SECRET_KEY': secrets.token_hex(24),
              'GATEWAY_SECRET': secrets.token_hex(32), 'ADMIN_EMAIL': 'admin@example.org', 'ADMIN_PASSWORD': secrets.token_urlsafe(24)}
    lines = Path('.env.example').read_text(encoding='utf-8').splitlines()
    path.write_text('\n'.join(k+'='+values[k] if (k:=line.split('=',1)[0]) in values else line for line in lines)+'\n', encoding='utf-8')
    path.chmod(0o600)


def initialize_broker(config):
    from kombu import Connection, Exchange, Queue
    definitions = json.loads(Path('infra/rabbitmq.json').read_text())
    with Connection(config.rabbitmq_url.get_secret_value(), connect_timeout=5,
                    transport_options={'confirm_publish': True}) as connection:
        for value in definitions['exchanges']:
            Exchange(value['name'], type=value['type'], durable=value['durable'],
                     auto_delete=value['auto_delete'])(connection).declare()
        for value in definitions['queues']:
            Queue(value['name'], durable=value['durable'], auto_delete=value['auto_delete'],
                  queue_arguments=value['arguments'])(connection).declare()
        for value in definitions['bindings']:
            Queue(value['destination'])(connection).bind_to(value['source'], value['routing_key'], value['arguments'])


def initialize(config):
    from alembic.config import Config
    from alembic import command
    from app.db import Uow
    from app.security import create_keys, Hasher
    from app.storage import Storage
    if not config.admin_email or len(config.admin_password.get_secret_value()) < 12:
        raise ValueError('ADMIN_EMAIL and a secret ADMIN_PASSWORD of at least 12 characters are required')
    command.upgrade(Config('alembic.ini'), 'head')
    create_keys(config)
    with Uow() as u:
        u.repo.lock_admins()
        if not u.repo.find('users', role='admin', is_active=True):
            u.repo.add('users', email=config.admin_email.casefold(), password_hash=Hasher().hash(config.admin_password.get_secret_value()),
                       role='admin', display_name='Administrator')
        u.commit()
    storage = Storage(config)
    for attempt in range(20):
        try:
            storage.initialize()
            break
        except Exception:
            if attempt == 19:
                raise
            time.sleep(2)
    initialize_broker(config)
    render_gateway(config, Path('/gateway/krakend.json'))


def import_directory(config, directory, corpus_id, aliases=None):
    from app.db import Uow
    from app.storage import Storage
    from app.services.catalog import Documents
    manifest = json.loads(aliases.read_text(encoding='utf-8')) if aliases else {}
    with Uow() as u:
        corpus = u.repo.get('corpora', corpus_id)
        if not corpus:
            raise ValueError('Corpus not found')
        user = u.repo.get('users', corpus['owner_id'])
        actor = {'id': user['id'], 'role': user['role']}
    results = []
    service = Documents(Uow, Storage(config))
    for file in sorted(directory.glob('*.pdf')):
        code = manifest.get(file.name, file.stem)
        doc, created = service.upload(actor, corpus_id, code, file.name, file.read_bytes())
        results.append({'original_filename': file.name, 'code': code, 'document_id': doc['id'], 'created': created})
    return results


def load_csv(directory, table):
    path = directory/(table+'.csv')
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def semantic_rows(directory, profile):
    from app.profiles import ENTITIES
    lookups = {}
    for p, collection, key, _ in ENTITIES.values():
        if p == profile and collection != 'results':
            lookups[collection] = {(r['publication_id'], r[key]): r for r in load_csv(directory, collection)}
    def linked(r, collection, field):
        entity = lookups.get(collection, {}).get((r['publication_id'], r.get(field)), {})
        if collection == 'devices':
            material = lookups.get('materials', {}).get((r['publication_id'], entity.get('absorber_material_id')), {})
            return tuple(entity.get(k) for k in ('device_label', 'device_type', 'architecture', 'active_area', 'area_definition')) + tuple(material.get(k) for k in ('material_name_raw', 'formula_normalized', 'material_class'))
        return tuple((k,v) for k,v in entity.items() if not k.endswith('_id') and k not in ('publication_id','note'))
    result = []
    for r in load_csv(directory, 'results'):
        if profile == 'solar-v1':
            relations = (linked(r,'devices','device_id'), linked(r,'measurements','measurement_id'), linked(r,'materials','material_id'))
            semantic_fields = ('aggregation', 'time_point', 'time_unit')
        else:
            relations = tuple(linked(r,c,f) for c,f in [('configurations','config_id'), ('datasets','dataset_id'), ('tasks','task_id'), ('experiments','experiment_id')])
            semantic_fields = ('aggregation', 'metric_variant', 'metric_k')
        key = (r['publication_id'], r['metric_name'], r.get('normalized_unit') or r.get('metric_unit'), r['result_origin'], *relations,
               *(r.get(f,'') for f in semantic_fields))
        result.append((key, decimal_value(r.get('normalized_value') or r.get('metric_value')), r.get('raw_value', '')))
    return result


def evaluate(predicted, gold, profile, tolerance=Decimal(0)):
    pred, truth = semantic_rows(predicted, profile), semantic_rows(gold, profile)
    unmatched, matches = set(range(len(truth))), 0
    for key, value, raw in pred:
        match = next((i for i in sorted(unmatched) if truth[i][0] == key and
            ((value is not None and truth[i][1] is not None and abs(value-truth[i][1]) <= tolerance) or
             (value is None and truth[i][1] is None and raw == truth[i][2]))), None)
        if match is not None:
            matches += 1; unmatched.remove(match)
    precision = matches/len(pred) if pred else None
    recall = matches/len(truth) if truth else None
    f1 = 2*precision*recall/(precision+recall) if precision is not None and recall is not None and precision+recall else 0 if truth or pred else None
    ppub = {r['publication_id']: r for r in load_csv(predicted, 'publications')}
    gpub = {r['publication_id']: r for r in load_csv(gold, 'publications')}
    shared = ppub.keys() & gpub.keys()
    return {'evaluator': 'project_defined_one_to_one_semantic_results', 'profile': profile,
            'comparison_type': 'self_comparison_sanity_only' if predicted.resolve()==gold.resolve() else 'predicted_against_supplied_gold',
            'true_positives': matches, 'predicted': len(pred), 'gold': len(truth), 'precision': precision, 'recall': recall, 'f1': f1,
            'scope': {'correct': sum(ppub[k]['in_scope'] == gpub[k]['in_scope'] for k in shared), 'compared': len(shared)},
            'classification': {'status': 'not_available_in_csv', 'reason': 'CSV scope is not topic classification'},
            'value_absolute_tolerance': str(tolerance), 'official_scorer': False}


def pg_connection(config):
    from sqlalchemy.engine import make_url
    url = make_url(config.database_url)
    if not url.drivername.startswith('postgresql'):
        raise ValueError('Backup/restore requires PostgreSQL')
    env = dict(os.environ, PGPASSWORD=url.password or '')
    args = ['--host', url.host or 'postgres', '--port', str(url.port or 5432), '--username', url.username or 'science', '--dbname', url.database]
    return args, env


def backup(config, output):
    from app.db import engine
    from app.storage import Storage
    from sqlalchemy import text
    from app.repositories.data import TABLES
    if output.exists():
        raise ValueError('Backup destination exists')
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage = Storage(config)
    args, env = pg_connection(config)
    temp_output = output.with_suffix('.partial')
    with temp_output.open('xb'):
        temp_output.chmod(0o600)
    with tempfile.TemporaryDirectory() as temp, engine().connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with conn.begin():
            conn.execute(text('LOCK TABLE '+','.join(TABLES)+' IN SHARE MODE'))
            snapshot_id = conn.execute(text('SELECT pg_export_snapshot()')).scalar_one()
            dump = Path(temp)/'database.dump'
            subprocess.run(['pg_dump', *args, '--format=custom', '--snapshot', snapshot_id, '--file', str(dump)], env=env, check=True, timeout=300)
            manifest = {'created_at': now().isoformat(), 'database_sha256': hashlib.sha256(dump.read_bytes()).hexdigest(), 'objects': []}
            with zipfile.ZipFile(temp_output, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(dump, 'database.dump')
                paginator = storage.client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=config.s3_bucket):
                    for obj in page.get('Contents', []):
                        key = obj['Key']; blob = storage.get(key)
                        name = 'objects/'+hashlib.sha256(key.encode()).hexdigest()
                        archive.writestr(name, blob)
                        content_type=storage.client.head_object(Bucket=config.s3_bucket,Key=key).get('ContentType','application/octet-stream')
                        manifest['objects'].append({'key': key, 'entry': name, 'sha256': hashlib.sha256(blob).hexdigest(), 'content_type':content_type})
                archive.writestr('manifest.json', json.dumps(manifest))
    temp_output.chmod(0o600)
    temp_output.replace(output)
    return {'status': 'backup_created', 'objects': len(manifest['objects'])}


def restore(config, source):
    from app.db import engine
    from app.storage import Storage
    from sqlalchemy import inspect
    from sqlalchemy.engine import make_url
    url = make_url(config.database_url)
    if config.environment != 'restore-test' or not (url.database or '').endswith('_restore_test'):
        raise ValueError('Restore requires ENVIRONMENT=restore-test and an empty *_restore_test database')
    if inspect(engine()).get_table_names():
        raise ValueError('Restore target database is not empty')
    storage = Storage(config)
    storage.initialize()
    if storage.client.list_objects_v2(Bucket=config.s3_bucket, MaxKeys=1).get('KeyCount',0):
        raise ValueError('Restore target object bucket is not empty')
    args, env = pg_connection(config)
    with zipfile.ZipFile(source) as archive, tempfile.TemporaryDirectory() as temp:
        manifest = json.loads(archive.read('manifest.json'))
        dump = archive.read('database.dump')
        if hashlib.sha256(dump).hexdigest() != manifest['database_sha256']:
            raise ValueError('Database checksum mismatch')
        for item in manifest['objects']:
            if hashlib.sha256(archive.read(item['entry'])).hexdigest() != item['sha256']:
                raise ValueError('Object checksum mismatch')
        path = Path(temp)/'database.dump'; path.write_bytes(dump)
        subprocess.run(['pg_restore', *args, '--no-owner', '--no-privileges', '--single-transaction', str(path)], env=env, check=True, timeout=300)
        for item in manifest['objects']:
            storage.put(item['key'], archive.read(item['entry']), item.get('content_type','application/octet-stream'))
        # Read every restored object back before declaring success.
        for item in manifest['objects']:
            if hashlib.sha256(storage.get(item['key'])).hexdigest() != item['sha256']:
                raise ValueError('Restored object checksum mismatch')
    return {'status': 'restored_to_empty_test_environment', 'objects': len(manifest['objects'])}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('bootstrap')
    commands.add_parser('reconsider-classifications')
    keys = commands.add_parser('keys'); keys.add_argument('--rotate', action='store_true'); keys.add_argument('--prune-old', action='store_true')
    gateway = commands.add_parser('gateway'); gateway.add_argument('--output', type=Path, default=Path('infra/krakend.json'))
    gateway.add_argument('--production', action='store_true')
    importer = commands.add_parser('import'); importer.add_argument('--directory', type=Path, required=True); importer.add_argument('--corpus', required=True); importer.add_argument('--aliases', type=Path)
    evaluator = commands.add_parser('evaluate'); evaluator.add_argument('--predicted', type=Path, required=True); evaluator.add_argument('--gold', type=Path, required=True); evaluator.add_argument('--profile', choices=['solar-v1','rag-v1'], required=True); evaluator.add_argument('--tolerance', type=Decimal, default=Decimal(0))
    evaluator.add_argument('--output', type=Path)
    for name in ('backup','restore'):
        command = commands.add_parser(name); command.add_argument('--output' if name == 'backup' else '--source', type=Path, required=True)
        if name == 'backup':
            command.add_argument('--daily', action='store_true')
    args = parser.parse_args()
    config = settings()
    result = None
    if args.command == 'bootstrap':
        bootstrap(Path('.env')); result = {'status': 'created', 'credentials_file': '.env'}
    elif args.command == 'init':
        initialize(config); result = {'status': 'initialized'}
    elif args.command == 'reconsider-classifications':
        from app.db import Uow
        from app.services.classification import reconsider_pending
        result = reconsider_pending(Uow, config.classification_confidence_threshold)
    elif args.command == 'keys':
        from app.security import create_keys
        create_keys(config, args.rotate)
        if args.prune_old:
            # Refuse pruning while any old access token can still be alive.
            if time.time()-config.jwt_key_path.stat().st_mtime < 960:
                raise ValueError('Wait at least 16 minutes after key rotation before pruning overlap')
            value = json.loads(config.jwt_public_path.read_text()); value['keys'] = value['keys'][:1]
            config.jwt_public_path.write_text(json.dumps(value))
        result = {'status': 'keys_updated', 'restart_gateway': True}
    elif args.command == 'gateway':
        result = {'endpoints': render_gateway(config, args.output)}
        if args.production:
            nginx = Path('infra/nginx.conf').read_text()
            nginx = nginx.replace('listen 80;', 'listen 443 ssl;\n    ssl_certificate /etc/nginx/tls/fullchain.pem;\n    ssl_certificate_key /etc/nginx/tls/privkey.pem;\n    ssl_protocols TLSv1.2 TLSv1.3;')
            nginx = nginx.replace('server {\n    listen 443', 'server { listen 80; return 308 https://$host$request_uri; }\n  server {\n    listen 443')
            Path('infra/nginx.production.conf').write_text(nginx)
    elif args.command == 'import':
        result = import_directory(config, args.directory, args.corpus, args.aliases)
    elif args.command == 'evaluate':
        result = evaluate(args.predicted, args.gold, args.profile, args.tolerance)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    elif args.command == 'backup':
        output = args.output / ('backup-'+now().strftime('%Y%m%dT%H%M%SZ')+'.zip') if args.daily else args.output
        result = backup(config, output)
    elif args.command == 'restore':
        result = restore(config, args.source)
    print(json.dumps(result, ensure_ascii=True, default=str))


if __name__ == '__main__':
    main()
