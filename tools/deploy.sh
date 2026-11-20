# Назначение файла: digest release, migrate/init, readiness/smoke и rollback image без DB downgrade.
#!/bin/sh
set -eu
cd "$(dirname "$0")"
test -f compose.yaml || cd ..
image=${1:?immutable image digest is required}
case "$image" in *@sha256:*) ;; *) echo 'Image digest is required' >&2; exit 2;; esac
test -f .env
test -d secrets
previous=$(cat .release-image 2>/dev/null || true)
export APP_IMAGE="$image"
export MINIO_IMAGE=${2:?immutable MinIO image digest is required}
compose() { docker compose -f compose.yaml -f compose.production.yaml "$@"; }
compose pull
# A single init owns migration/admin/key/gateway generation; the app image has its template.
compose run --rm init
compose run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD/infra:/output" --entrypoint python backend -c 'from pathlib import Path; p=Path("infra/nginx.conf").read_text(); p=p.replace("listen 80;", "listen 443 ssl;\n    ssl_certificate /etc/nginx/tls/fullchain.pem;\n    ssl_certificate_key /etc/nginx/tls/privkey.pem;\n    ssl_protocols TLSv1.2 TLSv1.3;"); p=p.replace("server {\n    listen 443", "server { listen 80; return 308 https://$host$request_uri; }\n  server {\n    listen 443"); Path("/output/nginx.production.conf").write_text(p)'
rollback() {
  if test -n "$previous"; then
    export APP_IMAGE="$previous"
    compose run --rm init
    compose up -d --no-build --wait --wait-timeout 180
  fi
}
if ! compose up -d --no-build --wait --wait-timeout 240; then rollback; exit 1; fi
if ! compose exec -T backend python -m tools.smoke --output /runtime/deploy-smoke.json --technical-only; then
  rollback
  exit 1
fi
printf '%s\n' "$image" > .release-image
