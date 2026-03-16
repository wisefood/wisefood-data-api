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
    GuideCreationSchema,
    GuideUpdateSchema,
    GuideSchema,
    validate_editorial_state,
    validate_guide_publication,
)

from entity import Entity
from entities.artifacts import ARTIFACT
from entities.guidelines import GUIDELINE

logger = logging.getLogger(__name__)


class Guide(Entity):
    def __init__(self):
        super().__init__(
            "guide", 
            "guides", 
            GuideSchema, 
            GuideCreationSchema, 
            GuideUpdateSchema
        )

    @staticmethod
    def _resolve_actor_id(actor: dict | None) -> str | None:
        if not actor:
            return None
        return actor.get("sub") or actor.get("id") or actor.get("preferred_username")

    def _apply_verifier_metadata(
        self,
        guide_dict: Dict[str, Any],
        actor: dict | None,
        *,
        review_status_explicit: bool,
        current_verifier_user_id: str | None = None,
    ) -> Dict[str, Any]:
        if guide_dict.get("review_status") == "verified" and (
            review_status_explicit or not current_verifier_user_id
        ):
            verifier_user_id = self._resolve_actor_id(actor)
            if not verifier_user_id:
                raise DataError(
                    "A verifier user ID is required when setting review_status='verified'."
                )
            guide_dict["verifier_user_id"] = verifier_user_id
        elif review_status_explicit and guide_dict.get("review_status") != "verified":
            guide_dict["verifier_user_id"] = None
        elif current_verifier_user_id is not None:
            guide_dict["verifier_user_id"] = current_verifier_user_id

        return guide_dict

    def _ensure_guide_can_be_active(self, guide_dict: Dict[str, Any]) -> None:
        if guide_dict.get("status") != "active":
            return

        if guide_dict.get("review_status") != "verified":
            raise ConflictError(
                "Guide must be verified before it can be published as active."
            )

        if not guide_dict.get("verifier_user_id"):
            raise ConflictError(
                "Guide must have a verifier user ID before it can be published as active."
            )

        if ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=guide_dict["urn"]) is None:
            return

        for guideline in GUIDELINE.fetch_for_guide(guide_dict["urn"]):
            if guideline.get("review_status") != "verified" or not guideline.get("verifier_user_id"):
                raise ConflictError(
                    "Guide cannot be active while it has unverified guidelines."
                )

    def _hydrate_guide(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        hydrated = dict(entity)
        if "urn" not in hydrated:
            return hydrated
        hydrated["artifacts"] = ARTIFACT.fetch(parent_urn=hydrated["urn"])
        hydrated["guidelines"] = GUIDELINE.list_ids_for_guide(hydrated["urn"])
        return hydrated

    def get(self, urn: str) -> Dict[str, Any]:
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=urn)
        if entity is None:
            raise NotFoundError(f"Guide with URN {urn} not found.")
        return self._hydrate_guide(entity)

    def fetch(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        guides = super().fetch(limit=limit, offset=offset)
        return [self._hydrate_guide(guide) for guide in guides]

    def search(self, query: Dict[str, Any]):
        response = super().search(query=query)
        response["results"] = [
            self._hydrate_guide(guide) for guide in response.get("results", [])
        ]
        return response

    def create(self, spec: GuideCreationSchema, creator: dict) -> Dict[str, Any]:
        # Validate input data
        try:
            guide_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating guide: {e}")

        # Check if guide with same URN already exists
        try:
            self.validate_existence("urn:guide:" + guide_data.urn)

            raise ConflictError(f"Guide with URN {guide_data.urn} already exists.")
        except NotFoundError:
            pass  # Expected if guide does not exist

        # Convert to dict and store in Elasticsearch
        guide_dict = guide_data.model_dump(mode="json")
        guide_dict["creator"] = creator["preferred_username"]
        guide_dict = self.upsert_system_fields(guide_dict, update=False)
        guide_dict = self._apply_verifier_metadata(
            guide_dict, creator, review_status_explicit=True
        )
        validate_editorial_state(guide_dict)
        validate_guide_publication(guide_dict)
        self._ensure_guide_can_be_active(guide_dict)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=guide_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create guide: {e}")

    def patch_entity_with_actor(self, urn: str, spec: Dict[str, Any], actor: dict):
        identifier = self.get_identifier(urn)
        self.invalidate_cache(identifier)
        self.patch(identifier, spec, actor=actor)
        return self.get_entity(identifier)

    def patch(self, urn: str, spec: GuideUpdateSchema, actor: dict | None = None):
        """Partially update an existing guide."""
        try:
            guide_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating guide: {e}")

        current = self.get_entity(urn)

        # Convert to dict and update in Elasticsearch
        update_dict = guide_data.model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        )
        merged_guide = {**current, **update_dict, "urn": urn}
        merged_guide = self._apply_verifier_metadata(
            merged_guide,
            actor,
            review_status_explicit="review_status" in update_dict,
            current_verifier_user_id=current.get("verifier_user_id"),
        )
        validate_editorial_state(merged_guide)
        validate_guide_publication(merged_guide)
        self._ensure_guide_can_be_active(merged_guide)

        guide_dict = self.upsert_system_fields(update_dict, update=True)
        if "verifier_user_id" in merged_guide:
            guide_dict["verifier_user_id"] = merged_guide.get("verifier_user_id")
        guide_dict["urn"] = urn
        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=guide_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update guide: {e}")

        if "region" in update_dict:
            GUIDELINE.sync_parent_metadata(urn)
        if "status" in update_dict or "visibility" in update_dict:
            GUIDELINE.sync_publication_state(
                urn,
                guide_status=merged_guide["status"],
                guide_visibility=merged_guide["visibility"],
            )

    def delete(self, urn: str) -> bool:
        if GUIDELINE.has_guidelines_for_guide(urn):
            raise ConflictError(
                f"Guide {urn} still has linked guidelines. Delete them first."
            )

        # Permanently delete the guide
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete guide: {e}")

        return {"deleted": urn}


GUIDE = Guide()
