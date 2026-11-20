import json
from fastapi import APIRouter, Depends, Response
from app.routes.dependencies import runtime

router = APIRouter(include_in_schema=False)


@router.get('/health/live')
def live():
    return {'status': 'live'}


@router.get('/health/ready')
def ready(rt=Depends(runtime)):
    checks = {}
    try:
        with rt.uow() as u:
            u.repo.find('users')
        checks['database'] = True
    except Exception:
        checks['database'] = False
    if rt.config.app_mode == 'auth':
        checks['signing_key'] = rt.config.jwt_key_path.is_file()
        checks['jwks'] = rt.config.jwt_public_path.is_file()
    else:
        try:
            rt.storage.client.head_bucket(Bucket=rt.config.s3_bucket)
            checks['storage'] = True
        except Exception:
            checks['storage'] = False
    # Broker/Redis outages do not make the persisted scientific catalogue unreadable.
    return Response(json.dumps({'status': 'ready' if all(checks.values()) else 'not_ready', 'checks': checks}),
                    media_type='application/json', status_code=200 if all(checks.values()) else 503)


@router.get('/metrics')
def metrics(rt=Depends(runtime)):
    from app.main import counters
    lines = ['# TYPE science_api_requests_total counter', f'science_api_requests_total {counters["requests"]}',
             '# TYPE science_api_errors_total counter', f'science_api_errors_total {counters["errors"]}']
    try:
        with rt.uow() as u:
            jobs = u.repo.find('jobs')
        lines += ['# TYPE science_jobs gauge'] + [f'science_jobs{{status="{state}"}} {sum(j["status"] == state for j in jobs)}' for state in sorted({j['status'] for j in jobs})]
    except Exception:
        lines.append('science_database_available 0')
    return Response('\n'.join(lines)+'\n', media_type='text/plain')
