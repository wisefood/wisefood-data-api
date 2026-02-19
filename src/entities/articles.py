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

from typing import Dict, Any
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
)

from entity import Entity
from backend.embedding_queue import EMBEDDING_QUEUE

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

        text_parts = [
            article.get("title"),
            article.get("abstract"),
            article.get("content"),
        ]
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
        current = self.get(urn)

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
        if any(f in ("title", "abstract", "content") for f in spec.fields):
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


    def patch(self, urn: str, spec: Dict[str, Any], updater=None) -> Dict[str, Any]:
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

    def delete(self, urn: str) -> bool:
        # Permanently delete the article
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete article: {e}")

        return {"deleted": urn}


ARTICLE = Article()
