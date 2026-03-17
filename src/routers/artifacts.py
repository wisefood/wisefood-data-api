from fastapi import APIRouter, Request, Depends, UploadFile, Form, File
from fastapi.responses import StreamingResponse
from routers.generic import render
from schemas import ArtifactCreationSchema, ArtifactUpdateSchema
import kutils
from exceptions import DataError
from entities.artifacts import ARTIFACT
from auth import auth
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/artifacts", tags=["Artifact Management Operations"])


@router.get(
    "/{id}",
    summary="Get artifact details",
    description="Retrieve details of a specific artifact by its ID.",
)
@render()
def api_get_artifact(request: Request, id: str, viewer: dict = Depends(auth())):
    return ARTIFACT.get(id, viewer=viewer)


@router.get(
    "/{id}/download",
    summary="Download artifact",
    description="Download the file associated with a specific artifact by its ID.",
)
def api_download_artifact(request: Request, id: str, viewer: dict = Depends(auth())):
    response_obj, filename, content_type = ARTIFACT.download(id, viewer=viewer)
    
    return StreamingResponse(
        response_obj,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.post(
    "",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Create a new artifact",
    description="Create a new artifact in the system using the provided data.",
)
@render()
def api_create_artifact(request: Request, a: ArtifactCreationSchema):
    return ARTIFACT.create_entity(
        a.model_dump(mode="json"), kutils.current_user(request)
    )


@router.post(
    "/upload",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Upload a file and create an artifact",
    description="Upload a file to the system and create an associated artifact. Maximum file size is 1GB.",
)
@render()
async def api_upload_artifact(
    request: Request,
    file: UploadFile = File(...),
    parent_urn: str = Form(...),
    title: str = Form(None),
    description: str = Form(None),
    language: str = Form(None),
):
    """
    Upload a file and create an artifact.

    Max file size: 1GB
    """
    MAX_FILE_SIZE = 1_073_741_824

    # Read file content
    file_content = await file.read()
    file_size = len(file_content)

    if file_size > MAX_FILE_SIZE:
        raise DataError(
            f"File size ({file_size} bytes) exceeds maximum allowed size of 1GB"
        )

    if file_size == 0:
        raise DataError("File is empty")

    # Upload to MinIO and create artifact
    return ARTIFACT.upload(
        file=file,
        file_content=file_content,
        parent_urn=parent_urn,
        title=title,
        description=description,
        language=language,
        creator=kutils.current_user(request),
        token=kutils.current_token(request),
    )


@router.patch(
    "/{id}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Update artifact details",
    description="Update the details of an existing artifact by its ID.",
)
@render()
def api_patch_artifact(request: Request, id: str, a: ArtifactUpdateSchema):
    return


@router.delete(
    "/{id}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Delete an artifact",
    description="Delete an artifact from the system by its ID.",
)
@render()
def api_delete_artifact(request: Request, id: str):
    return
