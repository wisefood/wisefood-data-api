from fastapi import APIRouter, Request, Depends

import kutils
from auth import auth
from entities.rcollections import RCOLLECTION
from routers.generic import render
from schemas import SearchSchema, RCollectionCreationSchema, RCollectionUpdateSchema, RCollectionAutocompleteSchema

router = APIRouter(prefix="/api/v1/rcollections", tags=["RCollection Operations"])


@router.get(
    "",
    summary="List recipe collections",
    description="Retrieve a paginated list of visible recipe collection URNs.",
)
@render()
def api_list_rcollections(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return RCOLLECTION.list_entities(limit=limit, offset=offset, viewer=viewer)


@router.get(
    "/autocomplete",
    summary="Autocomplete recipe collections",
    description="Search recipe collections by title prefix and return minimal representations for dropdown display.",
)
@render()
def api_autocomplete_rcollections(
    request: Request,
    q: str = "",
    limit: int = 15,
    viewer: dict = Depends(auth()),
):
    query = {"q": q, "limit": limit, "fl": ["urn", "title", "source_type", "recipe_count"]}
    response = RCOLLECTION.search_entities(query=query, viewer=viewer)
    results = response.get("results", []) if isinstance(response, dict) else response
    return [RCollectionAutocompleteSchema.model_validate(r).model_dump(mode="json") for r in results]


@router.get(
    "/fetch",
    summary="Fetch recipe collections",
    description="Fetch a paginated list of visible recipe collections with full details.",
)
@render()
def api_fetch_rcollections(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return RCOLLECTION.fetch_entities(limit=limit, offset=offset, viewer=viewer)


@router.post(
    "/search",
    summary="Search recipe collections",
    description="Search for recipe collections based on query parameters and filters.",
)
@render()
def api_search_rcollections(
    request: Request, q: SearchSchema, viewer: dict = Depends(auth())
):
    return RCOLLECTION.search_entities(
        query=q.model_dump(mode="json", exclude_none=True), viewer=viewer
    )


@router.get(
    "/{urn}",
    summary="Get recipe collection by URN",
    description="Retrieve a specific recipe collection by its URN.",
)
@render()
def api_get_rcollection(request: Request, urn: str, viewer: dict = Depends(auth())):
    return RCOLLECTION.get_entity(urn, viewer=viewer)


@router.post(
    "",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Create recipe collection",
    description="Create a new recipe collection with the provided metadata.",
)
@render()
def api_create_rcollection(request: Request, rc: RCollectionCreationSchema):
    return RCOLLECTION.create_entity(
        rc.model_dump(mode="json"), creator=kutils.current_user(request)
    )


@router.patch(
    "/{urn}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Update recipe collection",
    description="Partially update an existing recipe collection identified by its URN.",
)
@render()
def api_patch_rcollection(request: Request, urn: str, rc: RCollectionUpdateSchema):
    return RCOLLECTION.patch_entity(
        urn,
        rc.model_dump(mode="json", exclude_unset=True),
        actor=kutils.current_user(request),
    )


@router.delete(
    "/{urn}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Delete recipe collection",
    description="Delete a recipe collection from the system.",
)
@render()
def api_delete_rcollection(request: Request, urn: str):
    return RCOLLECTION.delete_entity(urn)
