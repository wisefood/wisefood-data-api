from fastapi import APIRouter, Depends, Request

import kutils
from auth import auth
from entities.guidelines import GUIDELINE
from routers.generic import render
from schemas import GuidelineBulkImportSchema, GuidelineCreationSchema, GuidelineUpdateSchema, SearchSchema

router = APIRouter(prefix="/api/v1/guidelines", tags=["Dietary Guideline Operations"])


@router.get(
    "",
    summary="List dietary guidelines",
    description="Retrieve a paginated list of dietary guideline IDs from the database.",
)
@render()
def api_list_guidelines(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return GUIDELINE.list(limit=limit, offset=offset, viewer=viewer)


@router.get(
    "/fetch",
    summary="Fetch dietary guidelines",
    description="Fetch a paginated collection of dietary guidelines with detailed information.",
)
@render()
def api_fetch_guidelines(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return GUIDELINE.fetch(limit=limit, offset=offset, viewer=viewer)


@router.post(
    "/search",
    summary="Search dietary guidelines",
    description="Search for dietary guidelines based on query parameters and filters.",
)
@render()
def api_search_guidelines(
    request: Request, q: SearchSchema, viewer: dict = Depends(auth())
):
    return GUIDELINE.search(
        query=q.model_dump(mode="json", exclude_none=True), viewer=viewer
    )


@router.get(
    "/by-guide/{guide_urn}",
    summary="Fetch guidelines for a guide",
    description="Retrieve all dietary guidelines linked to a specific guide URN.",
)
@render()
def api_fetch_guide_guidelines(
    request: Request,
    guide_urn: str,
    limit: int = 1000,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return GUIDELINE.fetch_for_guide(
        guide_urn=guide_urn, limit=limit, offset=offset, viewer=viewer
    )


@router.post(
    "/by-guide/{guide_urn}/search",
    summary="Search guidelines for a guide",
    description=(
        "Search, paginate, filter, and facet dietary guidelines linked to a specific guide URN."
    ),
)
@render()
def api_search_guide_guidelines(
    request: Request,
    guide_urn: str,
    q: SearchSchema,
    viewer: dict = Depends(auth()),
):
    return GUIDELINE.search_for_guide(
        guide_urn=guide_urn,
        query=q.model_dump(mode="json", exclude_none=True),
        viewer=viewer,
    )


@router.post(
    "/by-guide/{guide_urn}/import",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Bulk import guidelines for a guide",
    description="Import up to 1000 guidelines into a guide in a single call. "
                "sequence_no is auto-assigned for items that omit it.",
)
@render()
def api_bulk_import_guidelines(
    request: Request,
    guide_urn: str,
    payload: GuidelineBulkImportSchema,
):
    return GUIDELINE.bulk_import_for_guide(
        guide_urn=guide_urn,
        spec=payload.model_dump(mode="json"),
        creator=kutils.current_user(request),
    )


@router.get(
    "/{id}",
    summary="Get dietary guideline by ID",
    description="Retrieve a specific dietary guideline by its UUID.",
)
@render()
def api_get_guideline(request: Request, id: str, viewer: dict = Depends(auth())):
    return GUIDELINE.get(id, viewer=viewer)


@router.post(
    "",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Create dietary guideline",
    description="Create a new dietary guideline linked to a guide.",
)
@render()
def api_create_guideline(request: Request, g: GuidelineCreationSchema):
    return GUIDELINE.create_entity(
        g.model_dump(mode="json"), creator=kutils.current_user(request)
    )


@router.patch(
    "/{id}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Update dietary guideline",
    description="Partially update an existing dietary guideline identified by UUID.",
)
@render()
def api_patch_guideline(request: Request, id: str, g: GuidelineUpdateSchema):
    return GUIDELINE.patch_entity_with_actor(
        id,
        g.model_dump(mode="json", exclude_unset=True),
        actor=kutils.current_user(request),
    )


@router.delete(
    "/{id}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Delete dietary guideline",
    description="Delete a dietary guideline from the system by its UUID.",
)
@render()
def api_delete_guideline(request: Request, id: str):
    return GUIDELINE.delete_entity(id)
