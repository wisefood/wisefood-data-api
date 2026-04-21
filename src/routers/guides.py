from fastapi import APIRouter, Request, Depends
from schemas import GuideCreationSchema, GuideUpdateSchema, SearchSchema, GuideAutocompleteSchema
from routers.generic import render
import kutils
from auth import auth
from entities.guides import GUIDE

router = APIRouter(prefix="/api/v1/guides", tags=["Dietary Guides Operations"])


@router.get(
    "",
    summary="List dietary guides",
    description="Retrieve a paginated list of dietary guides from the database.",
)
@render()
def api_list_guides(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return GUIDE.list_entities(limit=limit, offset=offset, viewer=viewer)


@router.get(
    "/autocomplete",
    summary="Autocomplete dietary guides",
    description="Search guides by title prefix and return minimal representations for dropdown display.",
)
@render()
def api_autocomplete_guides(
    request: Request,
    q: str = "",
    limit: int = 15,
    viewer: dict = Depends(auth()),
):
    query = {"q": q, "limit": limit, "fl": ["urn", "title", "short_title", "region", "publication_year"]}
    response = GUIDE.search_entities(query=query, viewer=viewer)
    results = response.get("results", []) if isinstance(response, dict) else response
    return [GuideAutocompleteSchema.model_validate(r).model_dump(mode="json") for r in results]


@router.get(
    "/fetch",
    summary="Fetch dietary guides",
    description="Fetch a paginated collection of dietary guides with detailed information.",
)
@render()
def api_fetch_guides(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return GUIDE.fetch_entities(limit=limit, offset=offset, viewer=viewer)


@router.post(
    "/search",
    summary="Search dietary guides",
    description="Search for dietary guides based on query parameters and filters.",
)
@render()
def api_search_guides(
    request: Request, q: SearchSchema, viewer: dict = Depends(auth())
):
    return GUIDE.search_entities(
        query=q.model_dump(mode="json", exclude_none=True), viewer=viewer
    )


@router.get(
    "/{urn}",
    summary="Get dietary guide by URN",
    description="Retrieve a specific dietary guide by its unique resource name (URN).",
)
@render()
def api_get_guide(request: Request, urn: str, viewer: dict = Depends(auth())):
    return GUIDE.get_entity(urn, viewer=viewer)


@router.post(
    "",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Create dietary guide",
    description="Create a new dietary guide with the provided information.",
)
@render()
def api_create_guide(request: Request, g: GuideCreationSchema):
    return GUIDE.create_entity(
        g.model_dump(mode="json"), creator=kutils.current_user(request)
    )


@router.patch(
    "/{urn}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Update dietary guide",
    description="Partially update an existing dietary guide identified by its URN.",
)
@render()
def api_patch_guide(request: Request, urn: str, g: GuideUpdateSchema):
    return GUIDE.patch_entity(
        urn,
        g.model_dump(mode="json", exclude_unset=True),
        actor=kutils.current_user(request),
    )


@router.delete(
    "/{urn}",
    dependencies=[Depends(auth(("admin")))],
    summary="Delete dietary guide",
    description="Delete a dietary guide from the system by its URN.",
)
@render()
def api_delete_guide(request: Request, urn: str):
    return GUIDE.delete_entity(urn)
