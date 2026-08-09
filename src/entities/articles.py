"""
Article Entity
------------------
The Article entity inherits from the base Entity class and provides
methods to manage organization data, including retrieval, creation,
updating, and deletion of scientific articles. Collection operations such as
LIST, FETCH and SEARCH are implemented in the parent class. This class
consolidates and applies schemas specific to scientific articles for data validation
and serialization. It implements the CRUD operations while leveraging
the underlying infrastructure provided by the Entity base class.
"""

from typing import Any, Dict, List, Optional
from backend.elastic import ELASTIC_CLIENT
from entities.artifacts import ARTIFACT
from datetime import datetime
from exceptions import (
    DataError,
    InternalError,
    NotFoundError,
    ConflictError,
)
import logging
import uuid
from schemas import (
    ArticleCreationSchema,
    ArticleEnhancementSchema,
    ArticleUpdateSchema,
    ArticleSchema,
    SearchSchema,
)

from entity import Entity
from backend.embedding_queue import EMBEDDING_QUEUE
from embedding_policy import (
    EMBEDDED_ARTICLE_FIELDS,
    embedding_is_stale,
    requires_reembedding,
)

logger = logging.getLogger(__name__)


class Article(Entity):
    def __init__(self):
        super().__init__(
            "article",
            "articles",
            ArticleSchema,
            ArticleCreationSchema,
            ArticleUpdateSchema,
        )

    def get(self, urn: str) -> Dict[str, Any]:
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=urn)
        if entity is None:
            raise NotFoundError(f"Article with URN {urn} not found.")
        else:
            # Fetch and attach artifacts
            artifacts = ARTIFACT.fetch(parent_urn=urn)
            entity["artifacts"] = artifacts
        return entity

    def create(self, spec: ArticleCreationSchema, creator=None) -> Dict[str, Any]:
        # Validate input data
        try:
            article_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating article: {e}")

        # Check if article with same URN already exists
        try:
            self.validate_existence("urn:article:" + article_data.urn)

            raise ConflictError(f"Article with URN {article_data.urn} already exists.")
        except NotFoundError:
            pass  # Expected if article does not exist

        # Convert to dict and store in Elasticsearch
        article_dict = article_data.model_dump(mode="json")
        article_dict["creator"] = creator["preferred_username"]
        article_dict = self.upsert_system_fields(article_dict, update=False)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=article_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create article: {e}")
        # Fire-and-forget embedding jobs; do not block article creation
        try:
            # 1) Entity-level embedding (embedding)
            EMBEDDING_QUEUE.enqueue(
                self.embed(article_dict["urn"], article_dict, creator)
            )
            # 2) RAG chunks (rag_chunk_index) NB. Avoid it since we are not working with the content currently.
            # EMBEDDING_QUEUE.enqueue(
            #     self.embed_chunks(article_dict["urn"], article_dict, creator)
            # )
        except Exception as e:
            logger.error(
                "Failed to enqueue embedding for article %s: %s",
                article_dict.get("urn"),
                e,
            )

    def embed(self, urn: str, spec: Dict[str, Any], creator=None) -> Dict[str, Any]:
        """Build an embedding job for the given article."""
        self.validate_existence(urn)
        article = spec or {}
        if not article.get("content"):
            # Fetch article if content not provided in spec
            article = self.get(urn)

        text_parts = [article.get(field) for field in EMBEDDED_ARTICLE_FIELDS]
        text = "\n".join([part for part in text_parts if part])
        if not text:
            raise DataError("No article text available for embedding.")

        return {
            "job_id": str(uuid.uuid4()),
            "job_type": "entity_embedding",
            "entity": self.name,
            "urn": urn,
            "index_name": self.collection_name,
            "vector_field": "embedding",
            "text": text,
            "metadata": {
                "source": "article.embed",
                "requested_by": creator.get("preferred_username") if creator else None,
            },
        }
    
    def embed_chunks(self, urn: str, spec: Dict[str, Any], creator=None) -> Dict[str, Any]:
        """
        Build a job that will create RAG chunks for this article and index them into rag_chunk_index.
        """
        self.validate_existence(urn)

        # we don't strictly need spec here; worker can fetch fresh from ES
        return {
            "job_id": str(uuid.uuid4()),
            "job_type": "rag_chunks",
            "entity": self.name,
            "urn": urn,
            "source_index": self.collection_name,
            "rag_index": "rag_chunks", 
            "metadata": {
                "source": "article.embed_rag",
                "requested_by": creator.get("preferred_username") if creator else None,
            },
        }

    def enhance(self, urn: str, spec: ArticleEnhancementSchema, enhancer=None) -> Dict[str, Any]:

        self.validate_existence(urn)
        current = self.get_entity(urn)

        before = {}
        after = {}

        for field, new_value in spec.fields.items():
            before[field] = current.get(field)
            after[field] = new_value

        id = str(uuid.uuid4())
        enhancement_event = {
            "agent": spec.agent,
            "run_id": id,
            "enhanced_at": datetime.now().isoformat(),
            "fields": list(spec.fields.keys()),
            "before": before,
            "after": after,
        }

        ELASTIC_CLIENT.enhance_entity(
            index_name=self.collection_name,
            urn=urn,
            fields=spec.fields,
            enhancement_event=enhancement_event,
        )

        # Re-embed if semantic fields changed
        if requires_reembedding(spec.fields, EMBEDDED_ARTICLE_FIELDS):
            EMBEDDING_QUEUE.enqueue(
                self.embed(urn, None, enhancer)
            )
            # EMBEDDING_QUEUE.enqueue(
            #     self.embed_chunks(urn, None, enhancer)
            # )

        # Invalidate cache, so next miss retrieves fresh data
        self.invalidate_cache(urn)
        return {
            "urn": current["urn"],
            "run_id": id,
            "enhanced_fields": list(spec.fields.keys()),
            "agent": spec.agent,
        }


    EMBEDDING_BACKFILL_MAX_DOCS = 10000
    EMBEDDING_BACKFILL_MAX_SCAN = 200000

    def backfill_embeddings(
        self,
        *,
        only_missing: bool = True,
        max_docs: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Queue existing articles for embedding.

        Articles are embedded on create, enhance and patch, so anything ingested
        before those paths existed — or written while Redis was down, since the
        enqueue is deliberately fire-and-forget — has no vector.

        ``only_missing`` skips documents that are already embedded *and* whose
        vector is still current. A document edited after it was embedded is
        re-queued: its `embedded_at` is set, so presence alone would skip it
        forever, and the stale vector would go on matching text that is no
        longer there. Pass ``only_missing=False`` to re-embed everything.
        """
        # Deliberately not filtered on `embedded_at`: the worker sets it
        # asynchronously, so filtering on it would shift the result set under
        # the paging cursor mid-run — skipping pages, or re-queueing the same
        # unprocessed documents forever if the cursor were reset to compensate.
        fq = ["NOT status:deleted"]

        limit = min(
            int(max_docs or self.EMBEDDING_BACKFILL_MAX_DOCS),
            self.EMBEDDING_BACKFILL_MAX_DOCS,
        )

        queued = 0
        failed = 0
        skipped = 0
        scanned = 0
        offset = 0
        page_size = 500
        seen: set = set()

        while queued + failed < limit and scanned < self.EMBEDDING_BACKFILL_MAX_SCAN:
            qspec = SearchSchema.model_validate(
                {
                    "limit": page_size,
                    "offset": offset,
                    "fq": list(fq),
                    "sort": "urn asc",
                    "fl": [
                        "urn",
                        "title",
                        "abstract",
                        "content",
                        "embedded_at",
                        # Needed to tell a current vector from a stale one.
                        "updated_at",
                    ],
                }
            )
            try:
                response = ELASTIC_CLIENT.search_entities(
                    index_name=self.collection_name, qspec=qspec
                )
            except Exception as e:
                raise InternalError(f"Failed to scan articles for embedding: {e}")

            results = response.get("results", [])
            if not results:
                break

            scanned += len(results)

            for article in results:
                if queued + failed >= limit:
                    break
                urn = article.get("urn")
                if not urn or urn in seen:
                    continue
                seen.add(urn)

                if (
                    only_missing
                    and article.get("embedded_at")
                    and not embedding_is_stale(
                        article.get("updated_at"), article.get("embedded_at")
                    )
                ):
                    skipped += 1
                    continue
                if dry_run:
                    queued += 1
                    continue
                try:
                    EMBEDDING_QUEUE.enqueue(self.embed(urn, article))
                    queued += 1
                except Exception:
                    failed += 1
                    logger.warning(
                        "Could not queue article %s for embedding", urn, exc_info=True
                    )

            if len(results) < page_size:
                break
            offset += len(results)

        return {
            "dry_run": dry_run,
            "only_missing": only_missing,
            "queued": queued,
            "failed": failed,
            "skipped_already_embedded": skipped,
            "scanned": scanned,
            "max_docs": limit,
        }

    # ------------------------------------------------------------------ #
    # Editorial policy (reader visibility + indexing tier)
    # ------------------------------------------------------------------ #

    # A console click must not be able to rewrite the whole corpus by accident.
    POLICY_MAX_DOCS = 10000
    POLICY_PREVIEW_SIZE = 25

    def _policy_query(
        self,
        *,
        urns: Optional[List[str]] = None,
        q: Optional[str] = None,
        fq: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Build the selection query for a batch policy edit.

        Mirrors the search semantics of ``POST /articles/search`` (``q`` full
        text with AND, ``fq`` query-string filters) so the console can apply an
        edit to exactly the result set the editor is looking at.
        """
        must: List[Dict[str, Any]] = []
        filters: List[Dict[str, Any]] = [{"bool": {"must_not": {"term": {"status": "deleted"}}}}]

        if urns:
            filters.append({"terms": {"urn": list(urns)}})
        if q and q.strip():
            must.append(
                {"multi_match": {"query": q.strip(), "fields": ["*"], "operator": "and"}}
            )
        for clause in fq or []:
            if isinstance(clause, str) and clause.strip():
                filters.append({"query_string": {"query": clause.strip()}})

        return {"bool": {"must": must, "filter": filters}}

    def set_editorial_policy(
        self,
        *,
        urns: Optional[List[str]] = None,
        q: Optional[str] = None,
        fq: Optional[List[str]] = None,
        reader_visibility: Optional[str] = None,
        indexing_tier: Optional[str] = None,
        clear_indexing_tier: bool = False,
        max_docs: Optional[int] = None,
        dry_run: bool = False,
        updater=None,
    ) -> Dict[str, Any]:
        """
        Set reader visibility and/or indexing tier on every matching article.

        Selection is either an explicit URN list, a query, or both. A scripted
        update-by-query applies the change in one pass, so articles indexed
        before these fields existed simply gain them.

        ``dry_run`` reports what would change (count plus a sample) and writes
        nothing — the console should always preview a query-driven edit first.
        """
        if reader_visibility is None and indexing_tier is None and not clear_indexing_tier:
            raise DataError(
                "Specify reader_visibility and/or indexing_tier (or clear_indexing_tier)."
            )

        if not urns and not (q and q.strip()) and not fq:
            raise DataError(
                "Refusing to apply an editorial policy to every article: "
                "provide urns, a query, or filters."
            )

        query = self._policy_query(urns=urns, q=q, fq=fq)

        try:
            matched = ELASTIC_CLIENT.count_by_query(
                index_name=self.collection_name, query=query
            )
        except Exception as e:
            raise InternalError(f"Failed to count matching articles: {e}")

        limit = min(int(max_docs or self.POLICY_MAX_DOCS), self.POLICY_MAX_DOCS)

        # Read the affected documents up front: the head of this list is the
        # console's preview, and the full list is what we must evict from the
        # per-URN read cache once the update lands.
        affected: List[Dict[str, Any]] = []
        if matched:
            try:
                affected = ELASTIC_CLIENT.search_documents(
                    index_name=self.collection_name,
                    query=query,
                    size=min(matched, limit),
                    source_includes=[
                        "urn",
                        "title",
                        "reader_visibility",
                        "indexing_tier",
                        "ai_indexing_tier",
                    ],
                )
            except Exception:
                logger.warning("Could not read articles for policy edit", exc_info=True)

        preview = affected[: self.POLICY_PREVIEW_SIZE]

        if dry_run:
            return {
                "dry_run": True,
                "matched": matched,
                "updated": 0,
                "capped": matched > limit,
                "max_docs": limit,
                "sample": preview,
            }

        assignments: List[str] = ["ctx._source.updated_at = params.now"]
        params: Dict[str, Any] = {"now": datetime.now().isoformat()}

        if reader_visibility is not None:
            assignments.append("ctx._source.reader_visibility = params.reader_visibility")
            params["reader_visibility"] = reader_visibility
        if clear_indexing_tier:
            # Back to whatever the enrichment agent proposed.
            assignments.append("ctx._source.remove('indexing_tier')")
        elif indexing_tier is not None:
            assignments.append("ctx._source.indexing_tier = params.indexing_tier")
            params["indexing_tier"] = indexing_tier

        try:
            result = ELASTIC_CLIENT.update_by_query(
                index_name=self.collection_name,
                query=query,
                script_source="; ".join(assignments),
                params=params,
                max_docs=limit,
            )
        except Exception as e:
            raise InternalError(f"Failed to apply editorial policy: {e}")

        # Cached article reads would otherwise keep serving the old policy.
        for doc in affected:
            urn = doc.get("urn")
            if urn:
                self.invalidate_cache(urn)
        for urn in urns or []:
            self.invalidate_cache(urn)

        logger.info(
            "Editorial policy applied by %s: matched=%s updated=%s visibility=%s tier=%s",
            updater,
            matched,
            result.get("updated"),
            reader_visibility,
            "(cleared)" if clear_indexing_tier else indexing_tier,
        )

        return {
            "dry_run": False,
            "matched": matched,
            "updated": result.get("updated", 0),
            "capped": matched > limit,
            "max_docs": limit,
            "version_conflicts": result.get("version_conflicts", 0),
            "failures": result.get("failures", []),
            "sample": preview,
        }

    def patch(self, urn: str, spec: Dict[str, Any], updater=None) -> None:
        """Partially update an existing article."""
        try:
            article_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating article: {e}")

        # Check if article exists
        self.validate_existence(urn)

        # Convert to dict and update in Elasticsearch
        article_dict = article_data.model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        )
        article_dict = self.upsert_system_fields(article_dict, update=True)
        article_dict["urn"] = urn
        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=article_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update article: {e}")

        # Re-embed if an editor changed the text the vector was built from.
        #
        # `create` and `enhance` both do this; `patch` did not, so a human
        # rewriting a title or abstract in the console left the stored vector
        # describing the previous wording. That failure is silent and worse
        # than a missing embedding: `embedded_at` stays populated, so the
        # article looks embedded, retrieval keeps matching the old text, and
        # `backfill_embeddings(only_missing=True)` skips it forever.
        #
        # The field list mirrors `embed()`, which builds its text from exactly
        # title + abstract + content. `exclude_unset` above means membership
        # here reflects what the caller actually sent, so a status-only patch
        # does not pay for an embedding.
        if requires_reembedding(article_dict, EMBEDDED_ARTICLE_FIELDS):
            try:
                EMBEDDING_QUEUE.enqueue(self.embed(urn, None, updater))
            except Exception as e:
                # Fire-and-forget, as everywhere else: a queue outage must not
                # fail an edit the editor already saw succeed. `backfill_embeddings`
                # is the recovery path.
                logger.error(
                    "Failed to enqueue re-embedding for article %s: %s", urn, e
                )

    def delete(self, urn: str) -> bool:
        # Permanently delete the article
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete article: {e}")

        return {"deleted": urn}


ARTICLE = Article()
