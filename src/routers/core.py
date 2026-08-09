from fastapi import APIRouter, Request, Depends
from routers.generic import render
from auth import auth
from schemas import LoginSchema, MTMSchema
import kutils
from exceptions import AuthenticationError
from backend.minio import MINIO

router = APIRouter(prefix="/api/v1/system", tags=["System Operations"])


@router.get("/ping")
@render()
def ping(request: Request):
    return "pong"


@router.get("/info")
@render()
def info(request: Request):
    from main import config

    return {
        "service": "WiseFood Data Catalog API",
        "version": "0.0.1",
        "docs": "/docs",
        "keycloak": config.settings["KEYCLOAK_EXT_URL"],
        "minio": config.settings["MINIO_EXT_URL_CONSOLE"],
    }


@router.get(
    "/health",
    summary="Backing-service health",
    description=(
        "Reachability of Elasticsearch, Redis and MinIO. Unlike /ping, this "
        "actually touches each dependency."
    ),
)
@render()
def health(request: Request):
    from backend.elastic import ELASTIC_CLIENT
    from backend.embedding_queue import EMBEDDING_QUEUE

    elasticsearch = ELASTIC_CLIENT.cluster_state()
    queue_depth = EMBEDDING_QUEUE.depth()

    try:
        storage = MINIO.health_check()
    except Exception as exc:
        storage = {"healthy": False, "error": str(exc)}

    return {
        "elasticsearch": elasticsearch,
        # depth() returns None when Redis is unreachable, which is not the same
        # as an empty queue and must not be reported as healthy.
        "redis": {"reachable": queue_depth is not None},
        "storage": storage,
        "healthy": bool(
            elasticsearch.get("reachable")
            and queue_depth is not None
            and storage.get("healthy")
        ),
    }


@router.get(
    "/indices",
    dependencies=[Depends(auth(("admin",)))],
    summary="Elasticsearch index state",
    description=(
        "Per-index document counts, size, result window, and any mapping fields "
        "the code defines that the live index is missing. Admin only."
    ),
)
@render()
def index_state(request: Request):
    from backend.elastic import ELASTIC_CLIENT

    indices = ELASTIC_CLIENT.index_state()
    return {
        "cluster": ELASTIC_CLIENT.cluster_state(),
        "indices": indices,
        "drifted": [
            entry["index"] for entry in indices if entry.get("missing_fields")
        ],
    }


@router.get(
    "/embeddings",
    dependencies=[Depends(auth(("admin",)))],
    summary="Embedding coverage and queue state",
    description=(
        "How many documents per index carry a semantic vector, plus the depth of "
        "the embedding job queue.\n\n"
        "`missing` is documents that were never embedded. `stale` is documents "
        "embedded from text that has since been edited — they still count "
        "toward `embedded` and `coverage`, but their vector describes the "
        "previous wording, so `current` (embedded minus stale) is the figure "
        "that says whether semantic retrieval can be trusted. A backfill "
        "processes both. `stale` absent means the measurement could not run, "
        "which is not the same as zero.\n\n"
        "Admin only."
    ),
)
@render()
def embedding_state(request: Request):
    from backend.elastic import ELASTIC_CLIENT
    from backend.embedding_queue import EMBEDDING_QUEUE

    return {
        "queue": {
            "key": EMBEDDING_QUEUE.queue_key,
            "pending": EMBEDDING_QUEUE.depth(),
        },
        "indices": ELASTIC_CLIENT.embedding_state(),
    }


@router.post("/login")
@render()
def login(request: Request, creds: LoginSchema):
    return kutils.get_token(username=creds.username, password=creds.password)


@router.post("/mtm")
@render()
def login(request: Request, creds: MTMSchema):
    return kutils.get_client_token(
        client_id=creds.client_id, client_secret=creds.client_secret
    )