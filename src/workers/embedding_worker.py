import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List

from sentence_transformers import SentenceTransformer
from elasticsearch import helpers

from backend.embedding_queue import EMBEDDING_QUEUE
from backend.elastic import ELASTIC_CLIENT

logger = logging.getLogger(__name__)


def _split_into_paragraphs(text: str) -> List[str]:
    """
    Split raw text into logical paragraphs for chunking.

    Paragraphs are defined as blocks of non-empty text separated by one or
    more blank lines (two or more consecutive newlines).

    This keeps chunks aligned to human-readable units instead of arbitrary
    character windows.
    """
    paras = re.split(r"\n{2,}", text or "")
    return [p.strip() for p in paras if p.strip()]


def _group_paragraphs(
    paragraphs: List[str], max_paras_per_chunk: int = 3
) -> List[Dict[str, Any]]:
    """
    Group a list of paragraphs into coarse-grained chunks.

    Each chunk contains up to `max_paras_per_chunk` consecutive paragraphs and
    tracks their start/end indices. These indices can later be used for
    deep-linking and highlighting in the frontend.

    Returns a list of dicts with:
    - paragraph_start (int)
    - paragraph_end (int, inclusive)
    - paragraphs (List[str])
    """
    chunks: List[Dict[str, Any]] = []
    i = 0
    while i < len(paragraphs):
        start = i
        end = min(i + max_paras_per_chunk, len(paragraphs))  # exclusive
        chunks.append(
            {
                "paragraph_start": start,
                "paragraph_end": end - 1,
                "paragraphs": paragraphs[start:end],
            }
        )
        i = end
    return chunks


class EmbeddingWorker:
    """
    Long-running worker that consumes embedding jobs from a queue and writes
    results back to Elasticsearch.

    Supported job types:
    - entity_embedding: compute a single vector for an entity and store it in
      the entity's own index (e.g. article_index.embedding).
    - rag_chunks: build RAG-friendly chunks for an entity (currently articles),
      embed each chunk, and index them into the rag_chunk_index.
    """

    def __init__(self) -> None:
        model_name = os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        logger.info("Loading embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name)

    def run_forever(self, sleep_when_idle: int = 1, stop_event=None) -> None:
        """
        Main loop: pull jobs from the queue, process them, and block until stopped.

        :param sleep_when_idle: Seconds to sleep when the queue is empty before
                                polling again.
        :param stop_event: Optional threading.Event to allow clean shutdown.
        """
        while True:
            if stop_event and stop_event.is_set():
                logger.info("Stop event received; shutting down embedding worker.")
                return

            job = EMBEDDING_QUEUE.pop(timeout=5)
            if not job:
                time.sleep(sleep_when_idle)
                continue

            self._process_job(job)

    def _process_job(self, job: Dict[str, Any]) -> None:
        """
        Dispatch a job based on its job_type and update queue status accordingly.

        Expected job payload keys:
        - job_id (str)
        - job_type (str): "entity_embedding" | "rag_chunks" (default: entity_embedding)
        - urn (str): URN of the entity this job refers to
        """
        job_id = job.get("job_id")
        job_type = job.get("job_type", "entity_embedding")
        urn = job.get("urn")

        try:
            EMBEDDING_QUEUE.mark_started(job_id)

            if job_type == "entity_embedding":
                self._process_entity_embedding(job)
            elif job_type == "rag_chunks":
                self._process_rag_chunks(job)
            else:
                raise ValueError(f"Unknown job_type: {job_type}")

            EMBEDDING_QUEUE.mark_completed(
                job_id, metadata={"urn": urn, "job_type": job_type}
            )
            logger.info("Completed %s job %s for %s", job_type, job_id, urn)

        except Exception as e:
            logger.error("%s job %s for %s failed: %s", job_type, job_id, urn, e)
            EMBEDDING_QUEUE.mark_failed(job_id, str(e))

    def _process_entity_embedding(self, job: Dict[str, Any]) -> None:
        """
        Handle an entity_embedding job.

        Computes a single embedding vector for the provided text and patches the
        target entity document in its own index with:
        - <vector_field>: embedding vector
        - embedded_at: ISO timestamp
        """
        urn = job.get("urn")
        text = job.get("text")
        if not text:
            raise ValueError("Job payload missing 'text' for entity_embedding")

        # Compute embedding vector
        vector = self.model.encode(text).tolist()

        document = {
            "urn": urn,
            job.get("vector_field", "embedding"): vector,
            "embedded_at": datetime.now().isoformat(),
        }
        index_name = job.get("index_name")
        if not index_name:
            raise ValueError("Job payload missing 'index_name' for entity_embedding")

        ELASTIC_CLIENT.update_entity(index_name=index_name, document=document)

    def _process_rag_chunks(self, job: Dict[str, Any]) -> None:
        """
        Handle a rag_chunks job.

        For the given entity (currently assuming an article):
        - Fetch the latest entity document from its source index.
        - Split its content into paragraphs and group into chunks.
        - For each chunk, build a RAG-friendly text template and compute an embedding.
        - Delete any existing chunks for this entity from the rag_chunk_index.
        - Bulk index the new chunk documents into the rag_chunk_index.

        Expected job payload keys:
        - urn (str): base entity URN
        - source_index (str): index of the base entity (e.g. "articles")
        - rag_index (str): name of the RAG chunk index
        """
        urn = job.get("urn")
        source_index = job.get("source_index")
        rag_index = job.get("rag_index")
        if not source_index or not rag_index:
            raise ValueError("rag_chunks job requires 'source_index' and 'rag_index'")

        # 1) Fetch fresh entity doc from ES
        article = ELASTIC_CLIENT.get_entity(index_name=source_index, urn=urn)
        if not article:
            raise ValueError(f"Entity with URN {urn} not found in index {source_index}")

        title = article.get("title", "")
        content = article.get("content", "") or ""
        language = article.get("language", "en")
        region = article.get("region")
        organization_urn = article.get("organization_urn")
        url = article.get("url")
        base_type = "article"  # This handler currently assumes article semantics

        # 2) Chunk content
        paragraphs = _split_into_paragraphs(content)
        para_groups = _group_paragraphs(paragraphs, max_paras_per_chunk=3)

        now = datetime.utcnow().isoformat()
        chunk_docs: List[Dict[str, Any]] = []

        if not para_groups:
            # Edge case: no content, create one small "meta" chunk
            chunk_id = f"{urn}::chunk-0"
            chunk_text = (
                f"Article title: {title}\n\n{article.get('description', '') or ''}"
            )
            snippet = (article.get("description") or "")[:300]

            chunk_docs.append(
                {
                    "_op_type": "index",
                    "_index": rag_index,
                    "_id": chunk_id,
                    "_source": {
                        "chunk_id": chunk_id,
                        "base_urn": urn,
                        "base_type": base_type,
                        "organization_urn": organization_urn,
                        "title": title,
                        "url": url,
                        "section": None,
                        "paragraph_start": 0,
                        "paragraph_end": 0,
                        "anchor_start": "",
                        "language": language,
                        "region": region,
                        "text": chunk_text,
                        "snippet": snippet,
                        "embedding": self.model.encode(chunk_text).tolist(),
                        "created_at": now,
                        "updated_at": now,
                    },
                }
            )
        else:
            for idx, group in enumerate(para_groups):
                p_start = group["paragraph_start"]
                p_end = group["paragraph_end"]
                paras = group["paragraphs"]

                anchor_start = " ".join(paras[0].split()[:20]) if paras else ""

                chunk_text = (
                    f"Article title: {title}\n"
                    f"Type: article\n"
                    f"Language: {language}\n\n"
                    f"Content:\n" + "\n\n".join(paras)
                )
                snippet = paras[0][:300] if paras else ""

                chunk_id = f"{urn}::chunk-{idx}"

                vector = self.model.encode(chunk_text).tolist()

                chunk_docs.append(
                    {
                        "_op_type": "index",
                        "_index": rag_index,
                        "_id": chunk_id,
                        "_source": {
                            "chunk_id": chunk_id,
                            "base_urn": urn,
                            "base_type": base_type,
                            "organization_urn": organization_urn,
                            "title": title,
                            "url": url,
                            "section": None,  # can be populated if you parse headings
                            "paragraph_start": p_start,
                            "paragraph_end": p_end,
                            "anchor_start": anchor_start,
                            "language": language,
                            "region": region,
                            "text": chunk_text,
                            "snippet": snippet,
                            "embedding": vector,
                            "created_at": now,
                            "updated_at": now,
                        },
                    }
                )

        # 3) Delete existing chunks for this URN to avoid duplicates
        ELASTIC_CLIENT.delete_by_query(
            index_name=rag_index,
            query={"term": {"base_urn": urn}},
        )

        # 4) Bulk index new chunks
        if chunk_docs:
            helpers.bulk(ELASTIC_CLIENT.client, chunk_docs)


if __name__ == "__main__":
    worker = EmbeddingWorker()
    worker.run_forever()
