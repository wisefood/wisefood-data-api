import logging
import os
import time
from datetime import datetime
from typing import Any, Dict

from sentence_transformers import SentenceTransformer

from backend.embedding_queue import EMBEDDING_QUEUE
from backend.elastic import ELASTIC_CLIENT

logger = logging.getLogger(__name__)


class EmbeddingWorker:
    """
    Simple long-running worker that consumes embedding jobs from Redis,
    computes vectors, and writes them back to Elasticsearch.
    """

    def __init__(self):
        model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.model = SentenceTransformer(model_name)

    def run_forever(self, sleep_when_idle: int = 1, stop_event=None):
        while True:
            if stop_event and stop_event.is_set():
                return
            job = EMBEDDING_QUEUE.pop(timeout=5)
            if not job:
                time.sleep(sleep_when_idle)
                continue
            self._process_job(job)

    def _process_job(self, job: Dict[str, Any]):
        job_id = job.get("job_id")
        urn = job.get("urn")
        try:
            EMBEDDING_QUEUE.mark_started(job_id)
            text = job.get("text")
            if not text:
                raise ValueError("Job payload missing 'text'")
           
            # Compute embedding vector
            vector = self.model.encode(text).tolist()
            document = {
                "urn": urn,
                job.get("vector_field", "embedding"): vector,
                "embedded_at": datetime.now().isoformat(),
            }
            index_name = job.get("index_name")
            if not index_name:
                raise ValueError("Job payload missing 'index_name'")
            
            ELASTIC_CLIENT.update_entity(index_name=index_name, document=document)
            
            EMBEDDING_QUEUE.mark_completed(
                job_id,
                metadata={"urn": urn, "index_name": index_name},
            )
            logger.info("Completed embedding job %s for %s", job_id, urn)
        except Exception as e:
            logger.error("Embedding job %s failed: %s", job_id, e)
            EMBEDDING_QUEUE.mark_failed(job_id, str(e))


if __name__ == "__main__":
    worker = EmbeddingWorker()
    worker.run_forever()
