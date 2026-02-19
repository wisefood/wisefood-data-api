import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from backend.redis import REDIS

logger = logging.getLogger(__name__)


class EmbeddingQueue:
    """
    Lightweight Redis-backed queue for embedding jobs.
    Keeps API nodes stateless: all coordination and status lives in Redis.
    """

    def __init__(
        self,
        queue_key: str = "embedding:queue",
        status_prefix: str = "embedding:job:",
        status_ttl_seconds: int = 60 * 60 * 24,
        db: Optional[int] = None,
    ):
        self.queue_key = queue_key
        self.status_prefix = status_prefix
        self.status_ttl_seconds = status_ttl_seconds
        self.db = db if db is not None else int(os.getenv("REDIS_QUEUE_DB", os.getenv("REDIS_DB", 1)))

    def _status_key(self, job_id: str) -> str:
        return f"{self.status_prefix}{job_id}"

    def enqueue(self, job: Dict[str, Any]) -> str:
        job_id = job.get("job_id") or str(uuid.uuid4())
        job["job_id"] = job_id
        enqueued_at = datetime.now().isoformat()
        status_doc = {
            "job_id": job_id,
            "status": "queued",
            "enqueued_at": enqueued_at,
            "updated_at": enqueued_at,
            "error": None,
        }
        # Persist status and push job to queue
        REDIS.set(self._status_key(job_id), status_doc, db=self.db)
        REDIS.expire(self._status_key(job_id), self.status_ttl_seconds, db=self.db)
        REDIS.lpush(self.queue_key, json.dumps(job), db=self.db)
        return job_id

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        return REDIS.get(self._status_key(job_id), db=self.db)

    def pop(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """Blocking pop for workers; returns a dict or None on timeout."""
        item = REDIS.brpop(self.queue_key, timeout=timeout, db=self.db)
        if not item:
            return None
        try:
            payload = item[1] if isinstance(item, (list, tuple)) else item
            return json.loads(payload)
        except Exception as e:
            logger.error("Failed to decode embedding job: %s", e)
            return None

    def mark_started(self, job_id: str):
        status = self.get_status(job_id) or {}
        status.update({"status": "processing", "started_at": datetime.utcnow().isoformat(), "updated_at": datetime.utcnow().isoformat()})
        REDIS.set(self._status_key(job_id), status, db=self.db)
        REDIS.expire(self._status_key(job_id), self.status_ttl_seconds, db=self.db)

    def mark_completed(self, job_id: str, metadata: Optional[Dict[str, Any]] = None):
        status = self.get_status(job_id) or {}
        status.update(
            {
                "status": "completed",
                "finished_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "metadata": metadata or {},
                "error": None,
            }
        )
        REDIS.set(self._status_key(job_id), status, db=self.db)
        REDIS.expire(self._status_key(job_id), self.status_ttl_seconds, db=self.db)

    def mark_failed(self, job_id: str, error: str):
        status = self.get_status(job_id) or {}
        status.update(
            {
                "status": "failed",
                "finished_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "error": error,
            }
        )
        REDIS.set(self._status_key(job_id), status, db=self.db)
        REDIS.expire(self._status_key(job_id), self.status_ttl_seconds, db=self.db)


EMBEDDING_QUEUE = EmbeddingQueue()
