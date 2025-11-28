"""
Guide Entity
------------------
The Guide entity inherits from the base Entity class and provides
methods to manage dietary guide data, including retrieval, creation,
updating, and deletion of dietary guides. Collection operations such as
LIST, FETCH and SEARCH are implemented in the parent class. This class
consolidates and applies schemas specific to dietary guides for data validation
and serialization. It implements the CRUD operations while leveraging
the underlying infrastructure provided by the Entity base class.
"""

from typing import Optional, List, Dict, Any
from backend.elastic import ELASTIC_CLIENT
from exceptions import (
    DataError,
    InternalError,
    NotFoundError,
    ConflictError,
)
import logging
from schemas import (
    FoodCompositionTableCreationSchema,
    FoodCompositionTableUpdateSchema,
    FoodCompositionTableSchema,
    SearchSchema,
)

from entity import Entity
from entities.artifacts import ARTIFACT

logger = logging.getLogger(__name__)


class FoodCompositionTable(Entity):
    def __init__(self):
        super().__init__(
            "fctable", 
            "fctables", 
            FoodCompositionTableSchema, 
            FoodCompositionTableCreationSchema, 
            FoodCompositionTableUpdateSchema
        )

    def get(self, urn: str) -> Dict[str, Any]:
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=urn)
        if entity is None:
            raise NotFoundError(f"Food Composition Table with URN {urn} not found.")
        else:
            # Fetch and attach artifacts
            artifacts = ARTIFACT.fetch(parent_urn=urn)
            entity["artifacts"] = artifacts
        return entity

    def create(self, spec: FoodCompositionTableCreationSchema, creator: dict) -> Dict[str, Any]:
        # Validate input data
        try:
            fctable_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating food composition table: {e}")

        # Check if food composition table with same URN already exists
        try:
            self.validate_existence("urn:fctable:" + fctable_data.urn)
            raise ConflictError(f"Food Composition Table with URN {fctable_data.urn} already exists.")
        except NotFoundError:
            pass  # Expected if food composition table does not exist

        # Convert to dict and store in Elasticsearch
        fctable_dict = fctable_data.model_dump(mode="json")
        fctable_dict["creator"] = creator["preferred_username"]
        fctable_dict = self.upsert_system_fields(fctable_dict, update=False)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=fctable_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create food composition table: {e}")

    def patch(self, urn: str, spec: FoodCompositionTableUpdateSchema):
        """Partially update an existing food composition table."""
        try:
            fctable_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating food composition table: {e}")

        # Check if food composition table exists
        self.validate_existence(urn)

        # Convert to dict and update in Elasticsearch
        fctable_dict = fctable_data.model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        )
        fctable_dict = self.upsert_system_fields(fctable_dict, update=True)
        fctable_dict["urn"] = urn
        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=fctable_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update food composition table: {e}")

    def delete(self, urn: str) -> bool:
        # Permanently delete the food composition table
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete food composition table: {e}")
        return {"deleted": urn}


FCTABLE = FoodCompositionTable()
