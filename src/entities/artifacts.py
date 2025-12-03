
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.redis import REDIS
from backend.elastic import ELASTIC_CLIENT
from backend.minio import MINIO_CLIENT
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

    def list(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[str]:
        raise NotImplementedError("The Artifact entity does not support listing.")

    def fetch(
        self, parent_urn: str,
    ) -> List[Dict[str, Any]]:
        try:
            Entity.validate_existence(parent_urn)
        except NotFoundError:
            raise NotFoundError(f"Parent entity {parent_urn} not found.")

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
        
        # Return just the results list, not the whole dict
        return response["results"]

    def search(self, query: Dict[str, Any]):
        """
        Searching artifacts is not supported as they are dependent on parent entities.
        Use fetch() with a parent_urn instead.
        """
        raise NotAllowedError(
            "The Artifact entity does not support searching. "
            "Use fetch(parent_urn) to retrieve artifacts for a specific parent."
        )


    def get(self, urn: str) -> Dict[str, Any]:
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=urn)
        if entity is None:
            raise NotFoundError(f"Artifact with ID {urn} not found.")
        return entity

    def create_entity(self, spec, creator) -> Dict[str, Any]:
        """
        Create a new entity bundler method.

        :param spec: The data for the new entity.
        :param creator: The dict of the creator user fetched from header.
        :param override: If True, skip validation (used for uploads).
        :return: The created entity.
        """
        id = self.create(spec, creator)
        return self.get_entity(id)

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
        artifact_data["creator"] = creator["preferred_username"]
        artifact_data = self.upsert_system_fields(artifact_data, update=False)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=artifact_data
            )
        except Exception as e:
            raise InternalError(f"Failed to create artifact: {e}")

        return artifact_data["id"]
    
    def download(self, id: str):
        """
        Download the file associated with the artifact.

        :param id: The ID of the artifact.
        :return: Tuple of (file_content, filename, content_type)
        """
        artifact = self.get_entity(id)
        if artifact is None:
            raise NotFoundError(f"Artifact with ID {id} not found.")

        try:
            minio_client = MINIO_CLIENT()
        except Exception as e:
            logger.error(f"Failed to get MinIO client: {e}")
            raise InternalError(f"Failed to initialize storage client: {e}")

        # Extract bucket and object name from file_s3_url
        try:
            s3_url = artifact.get("file_s3_url")
            if not s3_url or not s3_url.startswith("s3://"):
                raise DataError(f"Invalid S3 URL for artifact {id}.")
            parts = s3_url[5:].split("/", 1)
            bucket_name = parts[0]
            object_name = parts[1] if len(parts) > 1 else ""
        except Exception as e:
            raise DataError(f"Failed to parse S3 URL for artifact {id}: {e}")

        try:
            response = minio_client.get_object(bucket_name, object_name)
            # Don't read() or close() - return the response object directly
            
            filename = artifact.get("filename", object_name.split("/")[-1])
            content_type = artifact.get("content_type", "application/octet-stream")
            
            return response, filename, content_type
            
        except S3Error as e:
            logger.error(f"Failed to download file from MinIO: {e}")
            raise InternalError(f"Failed to download file from storage: {e}")
        
        
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
        
        # Use ROOT client for uploads (has write permissions)
        # Personalized client would be for user-specific file access
        try:
            minio_client = MINIO_CLIENT()
        except Exception as e:
            logger.error(f"Failed to get MinIO client: {e}")
            raise InternalError(f"Failed to initialize storage client: {e}")
        
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
            "file_type": content_type,
            "file_size": file_size,
        }
        
        # Create artifact entry
        try:
            artifact_id = self.create(artifact_spec, creator, override=True)
            return self.get_entity(artifact_id)
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

    def delete(self, urn: str) -> bool:
        raise NotImplementedError("The Artifact entity does not support deleting.")


ARTIFACT = Artifact()
