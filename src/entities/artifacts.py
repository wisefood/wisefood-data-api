
from datetime import timedelta
import mimetypes
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.redis import REDIS
from backend.elastic import ELASTIC_CLIENT
from catalog_access import can_view_unapproved_catalog, is_approved_or_active
from backend.minio import MINIO_CLIENT, MINIO_PUBLIC_CLIENT
from pathlib import Path
from minio.error import S3Error
from io import BytesIO
from main import config
import uuid
from exceptions import (
    NotAllowedError,
    DataError,
    InternalError,
    NotFoundError,
)
import logging
from schemas import (
    ArtifactCreationSchema,
    ArtifactSchema,
    ArtifactUpdateSchema,
    SearchSchema,
)
from entity import Entity

logger = logging.getLogger(__name__)



# -----------------------------------
#
#  *** Artifact Entity ***
#
#  The artifact entity currently
#  hosts all features related to
#  linking resources under a catalog
#  entity. It is not considered
#  a standalone entity and its
#  existence is tied to the
#  existence of the parent entity.
#
# -----------------------------------
class Artifact(Entity):
   

    def __init__(self):
        super().__init__(
            "artifact",
            "artifacts",
            ArtifactSchema,
            ArtifactCreationSchema,
            ArtifactUpdateSchema,
        )
        self.BUCKET_NAME = config.settings.get("MINIO_BUCKET")
        self.MAX_FILE_SIZE = 1_073_741_824
        self.PRESIGNED_URL_EXPIRY_SECONDS = config.settings.get(
            "MINIO_PRESIGNED_URL_EXPIRY_SECONDS", 3600
        )

    def list(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[str]:
        raise NotImplementedError("The Artifact entity does not support listing.")

    @staticmethod
    def _viewer_can_access_all(
        viewer: Dict[str, Any] | None, *, include_unapproved: bool = False
    ) -> bool:
        """Allow unrestricted artifact reads only for privileged viewers or explicit bypasses."""
        return include_unapproved or can_view_unapproved_catalog(viewer)

    def _ensure_parent_visible(
        self,
        parent_urn: str,
        viewer: Dict[str, Any] | None,
        *,
        include_unapproved: bool = False,
    ) -> None:
        """Hide guide artifacts from non-privileged viewers when the parent guide is hidden."""
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ):
            return
        if not parent_urn.startswith("urn:guide:"):
            return

        guide = ELASTIC_CLIENT.get_entity(index_name="guides", urn=parent_urn)
        if guide is None or not is_approved_or_active(guide):
            raise NotFoundError("Artifact not found.")

    def fetch(
        self,
        parent_urn: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch artifacts for a parent entity after enforcing parent-based visibility."""
        try:
            Entity.validate_existence(parent_urn)
        except NotFoundError:
            raise NotFoundError(f"Parent entity {parent_urn} not found.")

        self._ensure_parent_visible(
            parent_urn, viewer, include_unapproved=include_unapproved
        )

        query = {
            "limit": 1000,
            "fq": [f'parent_urn:"{parent_urn}"'] 
        }

        try:
            qspec = SearchSchema.model_validate(query)
        except Exception as e:
            raise DataError(f"Invalid search query: {e}")

        
        response = ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )

        return [
            self._normalize_artifact_document(
                self.dump_schema.model_validate(
                    self._strip_search_metadata(obj)
                ).model_dump(mode="json")
            )
            for obj in response["results"]
        ]

    def search(self, query: Dict[str, Any]):
        """
        Searching artifacts is not supported as they are dependent on parent entities.
        Use fetch() with a parent_urn instead.
        """
        raise NotAllowedError(
            "The Artifact entity does not support searching. "
            "Use fetch(parent_urn) to retrieve artifacts for a specific parent."
        )


    def get(
        self,
        urn: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        """Fetch a single artifact and ensure its parent is visible to the caller."""
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=urn)
        if entity is None:
            raise NotFoundError(f"Artifact with ID {urn} not found.")
        self._ensure_parent_visible(
            entity.get("parent_urn", ""),
            viewer,
            include_unapproved=include_unapproved,
        )
        return self._normalize_artifact_document(entity)

    @staticmethod
    def _parse_s3_url(s3_url: str | None, artifact_id: str) -> tuple[str, str]:
        if not s3_url or not s3_url.startswith("s3://"):
            raise DataError(
                f"Artifact {artifact_id} does not reference an S3 object."
            )

        parts = s3_url[5:].split("/", 1)
        bucket_name = parts[0].strip()
        object_name = parts[1].strip() if len(parts) > 1 else ""

        if not bucket_name or not object_name:
            raise DataError(f"Invalid S3 URL for artifact {artifact_id}.")

        return bucket_name, object_name

    @staticmethod
    def _extension_from_name(name: str | None) -> str | None:
        if not name:
            return None
        suffix = Path(name).suffix.lower().strip()
        if not suffix:
            return None
        return suffix.lstrip(".")

    def _normalize_file_type(
        self,
        file_type: str | None,
        *,
        filename: str | None = None,
        strict: bool = False,
    ) -> str | None:
        extension = self._extension_from_name(filename)
        if extension:
            return extension

        if file_type is None:
            if strict:
                raise DataError("Artifact file_type is required.")
            return None

        value = file_type.strip().lower()
        if not value:
            if strict:
                raise DataError("Artifact file_type cannot be empty.")
            return None

        if "/" in value:
            guessed = mimetypes.guess_extension(value, strict=False)
            if guessed:
                return guessed.lstrip(".").lower()
            if strict:
                raise DataError(
                    f"Artifact file_type '{file_type}' could not be normalized to a file extension."
                )
            return value

        return value.lstrip(".")

    def _normalize_artifact_document(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(artifact)
        object_name = None
        try:
            _, object_name = self._parse_s3_url(
                normalized.get("file_s3_url"), str(normalized.get("id", "artifact"))
            )
        except DataError:
            object_name = None

        normalized_file_type = self._normalize_file_type(
            normalized.get("file_type"),
            filename=object_name,
        )
        if normalized_file_type:
            normalized["file_type"] = normalized_file_type

        return normalized

    @staticmethod
    def _artifact_download_name(
        artifact: Dict[str, Any],
        object_name: str,
    ) -> str:
        title = artifact.get("title")
        if title and Path(title).suffix:
            return title
        return artifact.get("filename", object_name.split("/")[-1])

    @staticmethod
    def _guess_download_content_type(
        filename: str,
        file_type: str | None,
    ) -> str:
        raw_type = (file_type or "").strip().lower()
        if "/" in raw_type:
            return raw_type

        guessed_from_name, _ = mimetypes.guess_type(filename, strict=False)
        if guessed_from_name:
            return guessed_from_name

        if raw_type:
            guessed_from_extension, _ = mimetypes.guess_type(
                f"file.{raw_type}", strict=False
            )
            if guessed_from_extension:
                return guessed_from_extension

        return "application/octet-stream"

    def _get_storage_client(self):
        try:
            return MINIO_CLIENT()
        except Exception as e:
            logger.error(f"Failed to get MinIO client: {e}")
            raise InternalError(f"Failed to initialize storage client: {e}")

    def _get_public_storage_client(self):
        try:
            return MINIO_PUBLIC_CLIENT()
        except Exception as e:
            logger.error(f"Failed to get public MinIO client: {e}")
            raise InternalError(f"Failed to initialize public storage client: {e}")

    def _get_presign_expiry_seconds(self) -> int:
        expires_in = int(self.PRESIGNED_URL_EXPIRY_SECONDS)
        if expires_in <= 0 or expires_in > 604800:
            raise InternalError(
                "MINIO_PRESIGNED_URL_EXPIRY_SECONDS must be between 1 and 604800."
            )
        return expires_in

    def create_entity(self, spec, creator) -> Dict[str, Any]:
        """
        Create a new entity bundler method.

        :param spec: The data for the new entity.
        :param creator: The dict of the creator user fetched from header.
        :param override: If True, skip validation (used for uploads).
        :return: The created entity.
        """
        id = self.create(spec, creator)
        return self.get(id, viewer=creator, include_unapproved=True)

    def create(self, spec: BaseModel, creator: dict, override: bool = False) -> str:
        # Validate input data
        if not override:
            try:
                artifact_data = self.creation_schema.model_validate(spec)
            except Exception as e:
                raise DataError(f"Invalid data for creating artifact: {e}")
        else:
            artifact_data = spec
        # Check if the parent entity exists, this will throw NotFoundError if not
        Entity.validate_existence(artifact_data.parent_urn if not override else spec["parent_urn"])
        # Invalidate parent cache since a new artifact is being added
        self.invalidate_cache(artifact_data.parent_urn if not override else spec["parent_urn"])

        artifact_data = artifact_data.model_dump(mode="json") if not override else artifact_data
        artifact_data["file_type"] = self._normalize_file_type(
            artifact_data.get("file_type"),
            strict=True,
        )
        artifact_data["creator"] = creator["preferred_username"]
        artifact_data = self.upsert_system_fields(artifact_data, update=False)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=artifact_data
            )
        except Exception as e:
            raise InternalError(f"Failed to create artifact: {e}")

        return artifact_data["id"]
    
    def download(
        self,
        id: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ):
        """
        Download the file associated with the artifact.

        :param id: The ID of the artifact.
        :return: Tuple of (file_content, filename, content_type)
        """
        artifact = self.get(
            id,
            viewer=viewer,
            include_unapproved=include_unapproved,
        )
        if artifact is None:
            raise NotFoundError(f"Artifact with ID {id} not found.")

        minio_client = self._get_storage_client()

        # Extract bucket and object name from file_s3_url
        try:
            bucket_name, object_name = self._parse_s3_url(
                artifact.get("file_s3_url"), id
            )
        except Exception as e:
            raise DataError(f"Failed to parse S3 URL for artifact {id}: {e}")

        try:
            response = minio_client.get_object(bucket_name, object_name)
            # Don't read() or close() - return the response object directly
            
            filename = self._artifact_download_name(artifact, object_name)
            content_type = self._guess_download_content_type(
                filename,
                artifact.get("file_type"),
            )
            
            return response, filename, content_type
            
        except S3Error as e:
            logger.error(f"Failed to download file from MinIO: {e}")
            raise InternalError(f"Failed to download file from storage: {e}")

    def presign(
        self,
        id: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a temporary presigned URL for the file associated with the artifact.

        :param id: The ID of the artifact.
        :return: Dict with the presigned URL and expiry information.
        """
        artifact = self.get(
            id,
            viewer=viewer,
            include_unapproved=include_unapproved,
        )

        try:
            bucket_name, object_name = self._parse_s3_url(
                artifact.get("file_s3_url"), id
            )
        except Exception as e:
            raise DataError(f"Failed to parse S3 URL for artifact {id}: {e}")

        expires_in = self._get_presign_expiry_seconds()
        minio_client = self._get_public_storage_client()

        try:
            url = minio_client.presigned_get_object(
                bucket_name,
                object_name,
                expires=timedelta(seconds=expires_in),
            )
        except S3Error as e:
            logger.error(f"Failed to presign file from MinIO: {e}")
            raise InternalError(f"Failed to presign file from storage: {e}")

        return {
            "artifact_id": str(artifact["id"]),
            "url": url,
            "expires_in": expires_in,
        }
        
        
    def upload(
        self,
        file,  # UploadFile from FastAPI
        file_content: bytes,
        parent_urn: str,
        title: Optional[str],
        description: Optional[str],
        language: Optional[str],
        creator: dict,
        token: str,
    ) -> Dict[str, Any]:
        """
        Upload a file to MinIO and create an artifact entry.
        
        :param file: UploadFile from FastAPI
        :param file_content: File content as bytes
        :param parent_urn: URN of the parent entity
        :param title: Optional title (defaults to filename)
        :param description: Optional description
        :param language: Optional language code
        :param creator: Creator user dict from request
        :param token: JWT token 
        :return: Created artifact document
        :raises DataError: If file validation fails
        :raises NotFoundError: If parent entity doesn't exist
        :raises InternalError: If upload or creation fails
        """
        # Validate file size
        file_size = len(file_content)
        
        if file_size == 0:
            raise DataError("Cannot upload empty file")
            
        if file_size > self.MAX_FILE_SIZE:
            raise DataError(
                f"File size ({file_size:,} bytes) exceeds maximum allowed "
                f"size of {self.MAX_FILE_SIZE:,} bytes (1GB)"
            )
        
        # Validate parent exists
        Entity.validate_existence(parent_urn)
 
        # Generate unique filename and ID 
        id = str(uuid.uuid4())
        file_extension = Path(file.filename).suffix.lower()
        unique_filename = f"{id}{file_extension}"
        
        # Determine content type
        content_type = file.content_type or "application/octet-stream"
        file_type = self._normalize_file_type(
            content_type,
            filename=file.filename,
        ) or "bin"
        
        # Use ROOT client for uploads (has write permissions)
        # Personalized client would be for user-specific file access
        minio_client = self._get_storage_client()
        
        # Create organized object path
        # Format: parent_type/parent_id/filename
        parent_parts = parent_urn.split(":")
        if len(parent_parts) >= 3:
            object_name = f"{parent_parts[1]}/{parent_parts[2]}/{unique_filename}"
        else:
            object_name = f"artifacts/{unique_filename}"
        
        # Upload file to MinIO

        try:
            minio_client.put_object(
                bucket_name=self.BUCKET_NAME,
                object_name=object_name,
                data=BytesIO(file_content),
                length=file_size,
                content_type=content_type,
            )
        except S3Error as e:
            logger.error(f"Failed to upload file to MinIO: {e}")
            raise InternalError(f"Failed to upload file to storage: {e}")
        
        # Generate file URLs
        file_url = config.settings.get("APP_EXT_DOMAIN") + config.settings.get("CONTEXT_PATH") + f"/api/v1/artifacts/{id}/download"
        file_s3_url = f"s3://{self.BUCKET_NAME}/{object_name}"
        
        # Create artifact metadata
        artifact_spec = {
            "id": id,
            "parent_urn": parent_urn,
            "title": title or file.filename,
            "description": description,
            "language": language,
            "file_url": file_url,
            "file_s3_url": file_s3_url,
            "file_type": file_type,
            "file_size": file_size,
        }
        
        # Create artifact entry
        try:
            artifact_id = self.create(artifact_spec, creator, override=True)
            return self.get(
                artifact_id, viewer=creator, include_unapproved=True
            )
        except Exception as e:
            # Cleanup orphaned file
            try:
                minio_client.remove_object(self.BUCKET_NAME, object_name)
                logger.warning(f"Cleaned up orphaned file {object_name} after failed artifact creation")
            except Exception as cleanup_error:
                logger.error(f"Failed to clean up file after error: {cleanup_error}")
            raise

    def patch(self, urn, spec):
        raise NotImplementedError("The Artifact entity does not support updating.")

    def _delete_bound_storage_object(self, artifact: Dict[str, Any]) -> None:
        artifact_id = str(artifact.get("id", "artifact"))
        file_s3_url = artifact.get("file_s3_url")

        if not file_s3_url:
            return

        try:
            bucket_name, object_name = self._parse_s3_url(file_s3_url, artifact_id)
        except DataError as e:
            logger.warning(
                "Skipping storage deletion for artifact %s: %s",
                artifact_id,
                e,
            )
            return

        minio_client = self._get_storage_client()
        try:
            minio_client.remove_object(bucket_name, object_name)
        except S3Error as e:
            logger.error(
                "Failed to delete storage object for artifact %s: %s",
                artifact_id,
                e,
            )
            raise InternalError(f"Failed to delete file from storage: {e}")

    def delete(self, urn: str) -> bool:
        artifact = self.get(urn, include_unapproved=True)
        parent_urn = artifact.get("parent_urn")

        self._delete_bound_storage_object(artifact)

        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete artifact: {e}")

        if parent_urn:
            self.invalidate_cache(parent_urn)

        return {"deleted": urn}


ARTIFACT = Artifact()
