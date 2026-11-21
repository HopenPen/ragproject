# Назначение файла: общий image auth/backend/worker/init с OCR eng/rus.
FROM golang:1.24.8-alpine3.22 AS minio-build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2
RUN apk --timeout 30 add --no-cache git ca-certificates
RUN git clone --depth 1 --branch RELEASE.2025-10-15T17-29-55Z https://github.com/minio/minio.git /src/minio && cd /src/minio && test "$(git rev-parse HEAD)" = 9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a && go build -p 2 -trimpath -ldflags='-s -w' -o /go/bin/minio . && cp LICENSE /go/bin/LICENSE.minio && go clean -modcache -cache && cd / && rm -rf /src/minio

FROM alpine:3.22.2 AS minio
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 minio && mkdir /data && chown minio /data
COPY --from=minio-build /go/bin/minio /usr/local/bin/minio
COPY --from=minio-build /go/bin/LICENSE.minio /usr/share/licenses/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a"
USER minio
ENTRYPOINT ["/usr/local/bin/minio"]

FROM python:3.12.10-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus postgresql-client ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home science
COPY . .
RUN mkdir -p /runtime /keys /public-keys /gateway && chown -R science:science /app /runtime /keys /public-keys /gateway
USER science
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
