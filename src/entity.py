"""
The Entity class is a base class for all API entities. The main responsibility
of the Entity class is to provide a common interface for interacting via the
Data API. The class defines a set of operations that can be performed
on an entity, such as listing, fetching, creating, updating, and deleting.
The specific implementation of these operations is left to the subclasses.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.redis import REDIS
from backend.embedding_queue import EMBEDDING_QUEUE
from backend.elastic import ELASTIC_CLIENT
from datetime import datetime
from schemas import SearchSchema
from utils import is_valid_uuid
from main import config
import uuid
from exceptions import (
    NotAllowedError,
    DataError,
    NotFoundError,
)
import logging


logger = logging.getLogger(__name__)


class Entity:
    """
    Base class for all API entities.

    In ReST terminology, an entity is a resource that can be accessed via an API.

    This class provides the basic structure for all entities. It defines the common
    operations that can be performed on an entity, such as listing, fetching, creating,
    updating, and deleting. The specific implementation of these operations is left to
    the subclasses.

    The API defined in this class is the one used by the endpoint definitions.
    """

    OPERATIONS = frozenset(
        [
            "list",
            "fetch",
            "get",
            "create",
            "delete",
            "search",
            "patch",
        ]
    )

    def __init__(
        self,
        name: str,
        collection_name: str,
        dump_schema: BaseModel,
        creation_schema: BaseModel,
        update_schema: BaseModel,
    ):
        """
        Initialize the entity with its name, collection name, creation schema, and update schema.

        :param name: The name of the entity.
        :param collection_name: The name of the collection of such entities.
        :param creation_schema: The schema used for creating instances of this entity.
        :param update_schema: The schema used for updating instances of this entity.
        """
        self.name = name
        self.collection_name = collection_name
        self.dump_schema = dump_schema
        self.creation_schema = creation_schema
        self.update_schema = update_schema

        self.operations = Entity.OPERATIONS.copy()
        if update_schema is None:
            self.operations.remove("patch")

    def fetch_entities(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch a list of entities bundler method.

        :param limit: The maximum number of entities to return.
        :param offset: The number of entities to skip before starting to collect the result set.
        :return: A list of entities.
        """
        return self.fetch(limit=limit, offset=offset)

    def fetch(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch a list of entities.

        :param limit: The maximum number of entities to return.
        :param offset: The number of entities to skip before starting to collect the result set.
        :return: A list of entities.
        """
        return ELASTIC_CLIENT.fetch_entities(
            index_name=self.collection_name, limit=limit or 100, offset=offset or 0
        )

    def list_entities(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[str]:
        """
        List entities by their URNs bundler method.

        :param limit: The maximum number of entities to return.
        :param offset: The number of entities to skip before starting to collect the result set.
        :return: A list of URNs.
        """
        return self.list(limit=limit, offset=offset)

    def list(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[str]:
        """
        List entities by their URNs.

        :param limit: The maximum number of entities to return.
        :param offset: The number of entities to skip before starting to collect the result set.
        :return: A list of URNs.
        """
        return ELASTIC_CLIENT.list_entities(
            index_name=self.collection_name, size=limit or 100, offset=offset or 0
        )

    @staticmethod
    def resolve_type(urn: str) -> str:
        """
        Resolve the type of an entity given its URN.

        :param urn: The URN of the entity.
        :return: The type of the entity.
        """
        try:
            return urn.split(":")[1]
        except Exception as e:
            raise DataError(f"Invalid URN format: {urn}. Error: {e}")

    @staticmethod
    def validate_existence(urn: str) -> None:
        """
        Validate the existence of an entity given its URN.

        :param urn: The URN of the entity.
        :return: True if the entity exists, False otherwise.
        """
        entity_type = Entity.resolve_type(urn)
        if entity_type == "guide":
            if ELASTIC_CLIENT.get_entity(index_name="guides", urn=urn) is None:
                raise NotFoundError(f"Guide with URN {urn} not found.")
        elif entity_type == "artifact":
            if ELASTIC_CLIENT.get_entity(index_name="artifacts", urn=urn) is None:
                raise NotFoundError(f"Artifact with URN {urn} not found.")
        elif entity_type == "article":
            if ELASTIC_CLIENT.get_entity(index_name="articles", urn=urn) is None:
                raise NotFoundError(f"Article with URN {urn} not found.")
        elif entity_type == "organization":
            if ELASTIC_CLIENT.get_entity(index_name="organizations", urn=urn) is None:
                raise NotFoundError(f"Organization with URN {urn} not found.")
        elif entity_type == "fctable":
            if ELASTIC_CLIENT.get_entity(index_name="fctables", urn=urn) is None:
                raise NotFoundError(f"Food Composition Table with URN {urn} not found.")

    def get_identifier(self, identifier: str) -> str:
        """
        Get the URN of an entity given its URN or UUID.

        :param identifier: The URN or UUID of the entity.
        :return: The URN of the entity.
        """
        if is_valid_uuid(identifier):
            if self.name == "artifact":
                return identifier
            return self.resolve_urn(identifier)
        elif identifier.startswith(f"urn:{self.name}:"):
            return identifier
        else:
            return f"urn:{self.name}:{identifier}"

    def cache(self, urn: str, obj) -> None:
        """
        Cache the entity.

        This method caches the entity for faster access.
        """
        if config.settings.get("CACHE_ENABLED", False):
            try:
                REDIS.set(urn, obj)
            except Exception as e:
                logging.error(f"Failed to cache entity {urn}: {e}")

    def invalidate_cache(self, urn: str) -> None:
        """
        Invalidate the cache for the entity.

        :param urn: The URN of the entity.
        """
        if config.settings.get("CACHE_ENABLED", False):
            try:
                REDIS.delete(urn)
            except Exception as e:
                logging.error(f"Failed to invalidate cache for entity {urn}: {e}")

    def resolve_urn(self, uuid: str) -> str:
        """
        Resolve the URN of an entity given its UUID.
        :param uuid: The UUID of the entity.
        :return: The URN of the entity.
        """
        try:
            qspec = {"fq": [f"id:{uuid}"]}
            result = ELASTIC_CLIENT.search_entities(
                index_name=self.collection_name, qspec=qspec
            )
            if not result.get("results"):  # Changed to check results key
                raise NotFoundError(f"Entity with UUID {uuid} not found.")
            return result["results"][0]["urn"]
        except Exception as e:
            logger.error(f"Failed to resolve URN for UUID {uuid}: {e}")
            raise NotFoundError(f"Failed to resolve URN for UUID {uuid}: {e}")

    def get_cached(self, urn: str) -> Optional[Dict[str, Any]]:
        obj = None
        if config.settings.get("CACHE_ENABLED", False):
            try:
                obj = REDIS.get(urn)
            except Exception as e:
                logging.error(f"Failed to get cached entity {urn}: {e}")

        if obj is None:
            obj = self.get(urn)
            self.cache(urn, obj)

        return self.dump_schema.model_validate(obj).model_dump(mode="json")

    def get_entity(self, urn: str) -> Dict[str, Any]:
        """
        Get an entity by its URN or UUID bundler method.

        :param urn: The URN or UUID of the entity to fetch.
        :return: The entity or None if not found.
        """
        identifier = self.get_identifier(urn)
        return self.get_cached(identifier)

    def get(self, urn: str) -> Dict[str, Any]:
        """
        Get an entity by its URN or UUID.

        :param urn: The URN of the entity to fetch.
        :return: The entity or None if not found.
        """
        raise NotImplementedError(
            "Subclasses of the Entity class must implement this method."
        )

    def create_entity(self, spec, creator) -> Dict[str, Any]:
        """
        Create a new entity bundler method.

        :param spec: The data for the new entity.
        :param creator: The dict of the creator user fetched from header.
        :return: The created entity.
        """
        self.create(spec, creator)
        return self.get_entity(spec.get("urn", spec.get("id")))

    def create(self, spec, creator) -> None:
        """
        Create a new entity.

        :param data: The validated data for the new entity.
        :param creator: The creator user dict fetched from header.
        :return: The created entity.
        """
        raise NotImplementedError(
            "Subclasses of the Entity class must implement this method."
        )

    def embed_entity(
        self, spec: Dict[str, Any], creator: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """
        Enqueue an embedding job for an entity; returns immediately with job info.

        :param spec: The data for the entity to embed.
        :param creator: The requesting user (if available) for audit metadata.
        :return: A dict containing job metadata.
        """
        identifier = self.get_identifier(spec.get("urn", spec.get("id")))
        job_payload = self.embed(identifier, spec, creator)
        job_id = EMBEDDING_QUEUE.enqueue(job_payload)
        return {"urn": identifier, "job_id": job_id, "status": "queued"}

    def embed(
        self, urn: str, spec: Dict[str, Any], creator: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """
        Build an embedding job payload for the given entity.

        :param urn: The URN of the entity to embed.
        :param spec: The validated data for embedding.
        :param creator: The requesting user (if available).
        :return: A job payload dict.
        """
        raise NotImplementedError(
            "Subclasses of the Entity class must implement this method."
        )

    def enhance_entity(
        self, urn: str, spec: Dict[str, Any], creator: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """
        Apply an AI-generated enhancement for an entity bundler method.

        :param spec: The data for the entity to enhance.
        :param creator: The requesting user (if available) for audit metadata.
        :return: A dict containing job metadata.
        """
        return self.enhance(urn, spec, creator)

    def enhance(
        self, urn: str, spec: Dict[str, Any], creator: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """
        Apply an AI-generated enhancement for an entity.

        :param spec: The data for the entity to enhance.
        :param creator: The requesting user (if available) for audit metadata.
        :return: A dict containing job metadata.
        """
        raise NotImplementedError(
            "Subclasses of the Entity class must implement this method."
        )

    def delete_entity(self, urn: str) -> bool:
        """
        Delete an entity by its URN or UUID bundler method.

        :param urn: The URN or UUID of the entity to delete.
        :return: True if the entity was deleted, False otherwise.
        """
        identifier = self.get_identifier(urn)
        self.invalidate_cache(identifier)
        return self.delete(identifier)

    def delete(self, urn: str, purge=False) -> bool:
        """
        Delete an entity by its URN.

        :param urn: The URN of the entity to delete.
        :param purge: Whether to permanently delete the entity.
        :return: True if the entity was deleted, False otherwise.
        """
        raise NotImplementedError(
            "Subclasses of the Entity class must implement this method."
        )

    def patch_entity(self, urn: str, spec) -> Dict[str, Any]:
        """
        Update an entity by its URN or UUID bundler method.

        :param urn: The URN or UUID of the entity to update.
        :param data: The data to update the entity with.
        :return: The updated entity.
        """
        if self.update_schema is None:
            raise NotAllowedError(f"The {self.name} entity does not support updates.")

        identifier = self.get_identifier(urn)
        self.invalidate_cache(identifier)
        self.patch(identifier, spec)
        return self.get_entity(identifier)

    def patch(self, urn: str, spec) -> None:
        """
        Update an entity by its URN.

        :param urn: The URN of the entity to update.
        :param data: The validated data to update the entity with.
        :return: The updated entity.
        """
        raise NotImplementedError(
            "Subclasses of the Entity class must implement this method."
        )

    def search_entities(
        self,
        query: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Search for entities bundler method.

        :param query: The search query.
        :param limit: The maximum number of entities to return.
        :param offset: The number of entities to skip before starting to collect the result set.
        :return: A list of entities matching the search query.
        """
        return self.search(query=query)

    def search(
        self,
        query: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Search for entities.

        :param query: The search query.
        :param limit: The maximum number of entities to return.
        :param offset: The number of entities to skip before starting to collect the result set.
        :return: A list of entities matching the search query.
        """
        try:
            qspec = SearchSchema.model_validate(query)
        except Exception as e:
            raise DataError(f"Invalid search query: {e}")

        return ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )

    def upsert_system_fields(self, spec: Dict, update=False) -> Dict[str, Any]:
        """
        Upsert system fields for the entity.

        :param data: The data to upsert system fields into.
        :return: The data with upserted system fields.
        """
        # Fix URN and UUIDs
        if "urn" in spec and not update:
            spec["urn"] = f"urn:{self.name}:{spec['urn'].split(':')[-1]}"
            spec["id"] = str(uuid.uuid4())

        if not update and self.name == "artifact" and "id" not in spec:
            spec["id"] = str(uuid.uuid4())

        if update and "creator" in spec:
            spec.pop("creator")
        # Generate timestamps
        spec["updated_at"] = str(datetime.now().isoformat())
        if not update:
            spec["created_at"] = str(datetime.now().isoformat())
        return spec


"""
VersionedEntity
------------------
Base class for entities that are *versioned*, i.e. they maintain
a history of changes over time.

A VersionedEntity:
- Uses the normal Entity index for the "current" resource.
- Uses a separate *versions* index to store historical versions.
- Supports:
  - creating versions (with user-provided OR auto-generated version labels),
  - listing all versions for a parent,
  - fetching a specific version,
  - fetching the latest version,
  - updating / soft-deleting versions.
"""

from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
import uuid
import logging

from pydantic import BaseModel

from backend.elastic import ELASTIC_CLIENT
from backend.redis import REDIS
from main import config
from utils import is_valid_uuid
from exceptions import DataError, NotFoundError, NotAllowedError

logger = logging.getLogger(__name__)


class VersionedEntity(Entity):
    """
    Base class for versioned entities.

    This keeps version handling generic and reusable across all entities.
    """

    def __init__(
        self,
        name: str,
        collection_name: str,
        dump_schema: BaseModel,
        creation_schema: BaseModel,
        update_schema: Optional[BaseModel],
        *,
        # Version-related wiring
        version_collection_name: str,
        version_dump_schema: BaseModel,
        version_creation_schema: BaseModel,
        version_update_schema: Optional[BaseModel],
        version_entity_name: str = "entity_version",
        version_field: str = "version_label",
        auto_version_generator: Optional[Callable[[str], str]] = None,
    ):
        """
        :param name: Name of the primary entity (e.g. 'guide').
        :param collection_name: Index name for primary entities (e.g. 'guides').
        :param dump_schema: Pydantic schema for primary entity responses.
        :param creation_schema: Pydantic schema for primary entity creation.
        :param update_schema: Pydantic schema for primary entity updates.
        :param version_collection_name: Index name for versions (e.g. 'entity_versions').
        :param version_dump_schema: Pydantic schema for version responses.
        :param version_creation_schema: Pydantic schema for version creation.
        :param version_update_schema: Pydantic schema for version updates.
        :param version_entity_name: Logical name for versions (used in URNs, e.g. 'entity_version').
        :param version_field: Field name in version docs holding the version label (e.g. 'version_label').
        :param auto_version_generator: Optional callable(parent_urn) -> version_label for auto versioning.
        """
        super().__init__(
            name, collection_name, dump_schema, creation_schema, update_schema
        )

        self.version_collection_name = version_collection_name
        self.version_dump_schema = version_dump_schema
        self.version_creation_schema = version_creation_schema
        self.version_update_schema = version_update_schema
        self.version_entity_name = version_entity_name
        self.version_field = version_field
        self.auto_version_generator = auto_version_generator

    # ------------------------------------------------------------------
    # Version identifier helpers
    # ------------------------------------------------------------------

    def _version_get_identifier(self, identifier: str) -> str:
        """
        Resolve the identifier for a version document.

        Accepts either:
        - UUID (id)
        - full URN: 'urn:<version_entity_name>:<slug>'
        - slug: '<slug>'  -> mapped to 'urn:<version_entity_name>:<slug>'
        """
        if is_valid_uuid(identifier):
            # For versions we always store and query by id when UUID is used.
            return identifier

        if identifier.startswith(f"urn:{self.version_entity_name}:"):
            return identifier

        # Treat as URN slug
        return f"urn:{self.version_entity_name}:{identifier}"

    # ------------------------------------------------------------------
    # Version system fields upsert
    # ------------------------------------------------------------------

    def upsert_version_system_fields(
        self, spec: Dict[str, Any], update: bool = False
    ) -> Dict[str, Any]:
        """
        Upsert system fields for a version document:
        - urn
        - id
        - created_at / updated_at
        - status (optional)
        """
        # URN + UUID
        if "urn" in spec and not update:
            spec["urn"] = f"urn:{self.version_entity_name}:{spec['urn'].split(':')[-1]}"
            spec["id"] = str(uuid.uuid4())

        if update and "creator" in spec:
            spec.pop("creator", None)

        # Timestamps
        spec["updated_at"] = datetime.now().isoformat()
        if not update:
            spec["created_at"] = datetime.now().isoformat()

        # Default status if missing
        if not update and "status" not in spec:
            spec["status"] = "active"

        return spec

    # ------------------------------------------------------------------
    # Version label generation
    # ------------------------------------------------------------------

    def generate_next_version_label(self, parent_urn: str) -> str:
        """
        Default auto-versioning strategy when no user-provided version is given.

        Strategy:
        - Look up all existing versions for this parent.
        - Collect numeric version labels convertible to float.
        - Return max + 1.0 as string.
        - If nothing found, return '1.0'.

        Subclasses can override or pass a custom `auto_version_generator`
        in the constructor for different schemes (dates, semver, etc.).
        """
        if self.auto_version_generator:
            return self.auto_version_generator(parent_urn)

        try:
            qspec = {
                "fq": [f"parent_urn:{parent_urn}"],
                "size": 1000,
                "offset": 0,
            }
            result = ELASTIC_CLIENT.search_entities(
                index_name=self.version_collection_name,
                qspec=qspec,
            )
            # Depending on your ES wrapper, this may be:
            # - a bare list, or
            # - a dict with "results" key
            if isinstance(result, dict) and "results" in result:
                hits = result["results"]
            else:
                hits = result
        except Exception as e:
            logger.error(
                f"Failed to load versions for auto versioning of {parent_urn}: {e}"
            )
            hits = []

        values = []
        for doc in hits:
            label = doc.get(self.version_field)
            if label is None:
                continue
            try:
                values.append(float(label))
            except Exception:
                continue

        if not values:
            return "1.0"

        return str(max(values) + 1.0)

    # ------------------------------------------------------------------
    # Version CRUD
    # ------------------------------------------------------------------

    def create_version(
        self, parent_urn: str, spec: Dict[str, Any], creator: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a new version document for the given parent entity.

        - Ensures parent exists.
        - Fills in parent_urn / parent_type.
        - Validates payload with version_creation_schema.
        - Auto-generates version label if missing.
        - Writes to the versions index.
        - Returns the created version (dump_schema validated).
        """
        # Check that parent exists
        self.validate_existence(parent_urn)

        # Ensure parent_urn is present in spec (schema probably has it too)
        spec.setdefault("parent_urn", parent_urn)
        spec.setdefault("parent_type", self.name)

        # Auto-generate version label if missing
        if self.version_field not in spec or not spec[self.version_field]:
            spec[self.version_field] = self.generate_next_version_label(parent_urn)

        # Validate spec via schema
        try:
            data = self.version_creation_schema.model_validate(spec).model_dump(
                mode="json"
            )
        except Exception as e:
            raise DataError(f"Invalid version spec: {e}")

        # Attach creator if your version schema has it
        if "creator" not in data and creator:
            # Adjust field according to your auth claims
            data["creator"] = (
                creator.get("sub") or creator.get("id") or creator.get("email")
            )

        # Upsert system fields (id, urn, timestamps, status)
        data = self.upsert_version_system_fields(data, update=False)

        # Persist to ES
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.version_collection_name,
                id=data["id"],
                body=data,
            )
        except Exception as e:
            logger.error(f"Failed to create version for {parent_urn}: {e}")
            raise DataError(f"Failed to create version for {parent_urn}: {e}")

        return self.version_dump_schema.model_validate(data).model_dump(mode="json")

    def get_version(self, identifier: str) -> Dict[str, Any]:
        """
        Fetch a single version document by:
        - UUID id, OR
        - URN, OR
        - URN slug (mapped to full URN).
        """
        ident = self._version_get_identifier(identifier)

        # If ident looks like a UUID, search by id, otherwise search by urn
        if is_valid_uuid(ident):
            qspec = {"fq": [f"id:{ident}"], "size": 1, "offset": 0}
        else:
            qspec = {"fq": [f"urn:{ident}"], "size": 1, "offset": 0}

        try:
            result = ELASTIC_CLIENT.search_entities(
                index_name=self.version_collection_name,
                qspec=qspec,
            )
            if isinstance(result, dict) and "results" in result:
                hits = result["results"]
            else:
                hits = result
        except Exception as e:
            logger.error(f"Failed to fetch version {identifier}: {e}")
            raise DataError(f"Failed to fetch version {identifier}: {e}")

        if not hits:
            raise NotFoundError(f"Version {identifier} not found.")

        doc = hits[0]
        return self.version_dump_schema.model_validate(doc).model_dump(mode="json")

    def list_versions(
        self,
        parent_urn: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        List all versions for a given parent entity.
        """
        # Ensure parent exists (fail fast)
        self.validate_existence(parent_urn)

        qspec = {
            "fq": [f"parent_urn:{parent_urn}"],
            "size": limit or 100,
            "offset": offset or 0,
        }

        try:
            result = ELASTIC_CLIENT.search_entities(
                index_name=self.version_collection_name,
                qspec=qspec,
            )
            if isinstance(result, dict) and "results" in result:
                hits = result["results"]
            else:
                hits = result
        except Exception as e:
            logger.error(f"Failed to list versions for {parent_urn}: {e}")
            raise DataError(f"Failed to list versions for {parent_urn}: {e}")

        return [
            self.version_dump_schema.model_validate(doc).model_dump(mode="json")
            for doc in hits
        ]

    def get_latest_version(self, parent_urn: str) -> Optional[Dict[str, Any]]:
        """
        Return the latest version document for the given parent.

        Strategy:
        - First look for is_latest:true.
        - If none, pick the one with max created_at.
        """
        # Ensure parent exists
        self.validate_existence(parent_urn)

        # First try with is_latest:true
        qspec_latest = {
            "fq": [f"parent_urn:{parent_urn}", "is_latest:true"],
            "size": 1,
            "offset": 0,
        }

        try:
            result = ELASTIC_CLIENT.search_entities(
                index_name=self.version_collection_name,
                qspec=qspec_latest,
            )
            if isinstance(result, dict) and "results" in result:
                hits = result["results"]
            else:
                hits = result
        except Exception as e:
            logger.error(f"Failed to fetch latest version for {parent_urn}: {e}")
            raise DataError(f"Failed to fetch latest version for {parent_urn}: {e}")

        if hits:
            doc = hits[0]
            return self.version_dump_schema.model_validate(doc).model_dump(mode="json")

        # Fallback: sort by created_at desc (if your qspec supports sort)
        qspec_all = {
            "fq": [f"parent_urn:{parent_urn}"],
            "size": 1,
            "offset": 0,
            "sort": ["created_at:desc"],
        }

        try:
            result = ELASTIC_CLIENT.search_entities(
                index_name=self.version_collection_name,
                qspec=qspec_all,
            )
            if isinstance(result, dict) and "results" in result:
                hits = result["results"]
            else:
                hits = result
        except Exception as e:
            logger.error(
                f"Failed to fetch latest version (fallback) for {parent_urn}: {e}"
            )
            raise DataError(
                f"Failed to fetch latest version (fallback) for {parent_urn}: {e}"
            )

        if not hits:
            return None

        doc = hits[0]
        return self.version_dump_schema.model_validate(doc).model_dump(mode="json")

    def patch_version(self, identifier: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing version document (partial update).

        - Validates via version_update_schema.
        - Does not allow changing parent_urn or parent_type here.
        """
        if self.version_update_schema is None:
            raise NotAllowedError(f"Versions for {self.name} do not support updates.")

        # Load current to ensure it exists
        current = self.get_version(identifier)
        version_id = current["id"]

        try:
            update_data = self.version_update_schema.model_validate(spec).model_dump(
                mode="json",
                exclude_unset=True,
            )
        except Exception as e:
            raise DataError(f"Invalid version update spec: {e}")

        # Guard against parent change
        for forbidden in ("parent_urn", "parent_type", "id", "urn"):
            if forbidden in update_data:
                update_data.pop(forbidden, None)

        update_data = self.upsert_version_system_fields(update_data, update=True)

        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.version_collection_name,
                id=version_id,
                body={"doc": update_data},
            )
        except Exception as e:
            logger.error(f"Failed to update version {identifier}: {e}")
            raise DataError(f"Failed to update version {identifier}: {e}")

        # Return fresh version
        return self.get_version(version_id)

    def delete_version(self, identifier: str, purge: bool = False) -> bool:
        """
        Delete a version document by id / URN / slug.

        - If purge=False: soft delete (status='deleted').
        - If purge=True: hard delete.
        """
        # Make sure it exists
        version = self.get_version(identifier)
        version_id = version["id"]

        try:
            if purge:
                deleted = ELASTIC_CLIENT.delete_entity(
                    index_name=self.version_collection_name,
                    id=version_id,
                )
                return bool(deleted)
            else:
                update_data = {
                    "status": "deleted",
                    "updated_at": datetime.utcnow().isoformat(),
                }
                ELASTIC_CLIENT.update_entity(
                    index_name=self.version_collection_name,
                    id=version_id,
                    body={"doc": update_data},
                )
                return True
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete version {identifier}: {e}")
            raise DataError(f"Failed to delete version {identifier}: {e}")


"""
DependentEntity
------------------
Base class for entities that are *dependent* on other API entities,
such as ratings, comments, reactions, etc.

A DependentEntity:
- does NOT have its own URN (only an `id` UUID),
- references a parent entity via a URN field (e.g. `target_urn`),
- reuses most of Entity's infrastructure (search, list, fetch, create, patch, delete),
- adds parent existence validation and tweaks system-field upsert logic.
"""


class DependentEntity(Entity):
    """
    Base class for entities that depend on other entities (e.g. engagements).

    Key differences from `Entity`:
    - No own URN; documents are addressed by `id` (UUID) only.
    - Each document must reference a parent entity via a URN field (e.g. `target_urn`).
    - Provides helper to validate that the parent entity exists.
    """

    def __init__(
        self,
        name: str,
        collection_name: str,
        dump_schema: BaseModel,
        creation_schema: BaseModel,
        update_schema: Optional[BaseModel],
        *,
        parent_field: str = "target_urn",
        parent_required: bool = True,
    ):
        """
        :param name: Logical name of the dependent entity (e.g. 'engagement').
        :param collection_name: Elasticsearch index name (e.g. 'engagements').
        :param dump_schema: Pydantic schema used for serializing responses.
        :param creation_schema: Pydantic schema used for validating create payloads.
        :param update_schema: Pydantic schema used for validating patch payloads.
        :param parent_field: Name of the field holding the parent's URN (e.g. 'target_urn').
        :param parent_required: Whether the parent URN is required on create.
        """
        super().__init__(
            name=name,
            collection_name=collection_name,
            dump_schema=dump_schema,
            creation_schema=creation_schema,
            update_schema=update_schema,
        )
        self.parent_field = parent_field
        self.parent_required = parent_required

    # ---------- Identifier handling (UUID only, no URNs) ----------

    def get_identifier(self, identifier: str) -> str:
        """
        For dependent entities, we treat the identifier as a raw UUID.

        - If it's a valid UUID -> return as-is.
        - Otherwise -> error (no URN resolution for dependent entities).
        """
        if is_valid_uuid(identifier):
            return identifier
        raise DataError(
            f"Dependent entity '{self.name}' must be referenced by UUID, got: {identifier}"
        )

    def get_entity(self, identifier: str) -> Dict[str, Any]:
        """
        Override the bundler to avoid URN logic; we only use UUIDs for dependent entities.
        """
        id_ = self.get_identifier(identifier)
        obj = self.get_cached(id_)
        return obj

    def cache(self, identifier: str, obj) -> None:
        """
        Cache by UUID, not URN.
        """
        if config.settings.get("CACHE_ENABLED", False):
            try:
                REDIS.set(identifier, obj)
            except Exception as e:
                logger.error(f"Failed to cache dependent entity {identifier}: {e}")

    def invalidate_cache(self, identifier: str) -> None:
        """
        Invalidate cache by UUID.
        """
        if config.settings.get("CACHE_ENABLED", False):
            try:
                REDIS.delete(identifier)
            except Exception as e:
                logger.error(
                    f"Failed to invalidate cache for dependent entity {identifier}: {e}"
                )

    def get_cached(self, identifier: str) -> Dict[str, Any]:
        obj = None
        if config.settings.get("CACHE_ENABLED", False):
            try:
                obj = REDIS.get(identifier)
            except Exception as e:
                logger.error(f"Failed to get cached dependent entity {identifier}: {e}")

        if obj is None:
            obj = self.get(identifier)
            self.cache(identifier, obj)

        return self.dump_schema.model_validate(obj).model_dump(mode="json")

    # ---------- Parent existence helpers ----------

    def ensure_parent_exists(self, spec: Dict[str, Any]) -> None:
        """
        Ensure the parent entity referenced in `parent_field` exists.

        Uses Entity.validate_existence under the hood.
        """
        parent_urn = spec.get(self.parent_field)

        if not parent_urn:
            if self.parent_required:
                raise DataError(
                    f"Field '{self.parent_field}' is required for dependent entity '{self.name}'."
                )
            # If not required and not present, nothing to validate
            return

        # Delegate validation to the global Entity resolver
        Entity.validate_existence(parent_urn)

    # ---------- System fields handling ----------

    def upsert_system_fields(
        self, spec: Dict[str, Any], update: bool = False
    ) -> Dict[str, Any]:
        """
        Upsert system fields for a dependent entity.

        Differences vs Entity.upsert_system_fields:
        - No URN handling.
        - Always use `id` (UUID) as the primary identifier.
        """
        # Validate parent reference before anything else
        if not update:
            self.ensure_parent_exists(spec)

        # Ensure id exists
        if not update and "id" not in spec:
            spec["id"] = str(uuid.uuid4())

        # Prevent updates to creator if passed in accidentally
        if update and "creator" in spec:
            spec.pop("creator")

        # Timestamps
        spec["updated_at"] = datetime.now().isoformat()
        if not update:
            spec["created_at"] = datetime.now().isoformat()

        return spec

    # ---------- Optional convenience methods for dependents ----------

    def list_for_parent(
        self,
        parent_urn: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        List dependent documents for a specific parent entity.

        :param parent_urn: The URN of the parent entity (e.g. an article's URN).
        :param limit: Max number of documents.
        :param offset: Offset for pagination.
        """
        # Ensure the parent exists (fail fast)
        Entity.validate_existence(parent_urn)

        qspec = {
            "fq": [{self.parent_field: parent_urn}],
            "size": limit or 100,
            "offset": offset or 0,
        }

        results = ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )
        return [
            self.dump_schema.model_validate(obj).model_dump(mode="json")
            for obj in results
        ]
