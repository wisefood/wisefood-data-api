from fastapi import APIRouter, Request, Depends

import kutils
from auth import auth
from entities.textbooks import TEXTBOOK
from routers.generic import render
from schemas import SearchSchema, TextbookCreationSchema, TextbookUpdateSchema

router = APIRouter(prefix="/api/v1/textbooks", tags=["Textbook Operations"])


@router.get(
    "",
    summary="List textbooks",
    description="Retrieve a paginated list of visible textbook URNs.",
)
@render()
def api_list_textbooks(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return TEXTBOOK.list_entities(limit=limit, offset=offset, viewer=viewer)


@router.get(
    "/fetch",
    summary="Fetch textbooks",
    description="Fetch a paginated collection of visible textbooks with detailed information.",
)
@render()
def api_fetch_textbooks(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return TEXTBOOK.fetch_entities(limit=limit, offset=offset, viewer=viewer)


@router.post(
    "/search",
    summary="Search textbooks",
    description="Search for textbooks based on query parameters and filters.",
)
@render()
def api_search_textbooks(
    request: Request, q: SearchSchema, viewer: dict = Depends(auth())
):
    return TEXTBOOK.search_entities(
        query=q.model_dump(mode="json", exclude_none=True), viewer=viewer
    )


@router.get(
    "/{urn}",
    summary="Get textbook by URN",
    description="Retrieve a specific textbook by its unique resource name (URN).",
)
@render()
def api_get_textbook(request: Request, urn: str, viewer: dict = Depends(auth())):
    return TEXTBOOK.get_entity(urn, viewer=viewer)


@router.post(
    "",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Create textbook",
    description="Create a new textbook with the provided metadata.",
)
@render()
def api_create_textbook(request: Request, t: TextbookCreationSchema):
    return TEXTBOOK.create_entity(
        t.model_dump(mode="json"), creator=kutils.current_user(request)
    )


@router.patch(
    "/{urn}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Update textbook",
    description="Partially update an existing textbook identified by its URN.",
)
@render()
def api_patch_textbook(request: Request, urn: str, t: TextbookUpdateSchema):
    return TEXTBOOK.patch_entity(
        urn,
        t.model_dump(mode="json", exclude_unset=True),
        actor=kutils.current_user(request),
    )


@router.delete(
    "/{urn}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Delete textbook",
    description="Delete a textbook and its extracted passages from the system.",
)
@render()
def api_delete_textbook(request: Request, urn: str):
    return TEXTBOOK.delete_entity(urn)
