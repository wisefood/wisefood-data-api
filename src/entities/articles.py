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
from typing import Optional, List, Dict, Any
from backend.elastic import ELASTIC_CLIENT
from entities.artifacts import ARTIFACT
from exceptions import (
    DataError,
    InternalError,
    NotFoundError,
    ConflictError,
)
import logging
from schemas import (
    SearchSchema,
    ArticleCreationSchema,
    ArticleUpdateSchema,
    ArticleSchema,
)

from entity import Entity

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