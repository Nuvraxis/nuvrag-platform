# The ingestion worker reuses the API image verbatim and only swaps the command, so the two
# deployments can never drift apart on dependencies. Build with:
#   docker build -f infra/docker/api.Dockerfile -t rag-api .
#   docker build -f infra/docker/worker.Dockerfile --build-arg BASE_IMAGE=rag-api -t rag-worker .

ARG BASE_IMAGE=rag-api:latest
FROM ${BASE_IMAGE}

# Numeric for the same reason as the API image it is built from: a named user cannot satisfy
# a runAsNonRoot check.
USER 1001:1001

# One queue per workload class: `ingestion` is slow and bursty, `default` carries the
# lightweight background tasks. Concurrency stays low because PDF parsing is CPU-bound and
# the pods are scaled on queue depth rather than CPU.
ENV CELERY_CONCURRENCY=4 \
    CELERY_QUEUES=ingestion,default

CMD ["sh", "-c", "celery -A app.worker.celery_app.celery_app worker \
     --queues=${CELERY_QUEUES} \
     --concurrency=${CELERY_CONCURRENCY} \
     --loglevel=INFO \
     --max-tasks-per-child=200"]
