from fastapi import APIRouter, Depends, Request

import kutils
from auth import auth
from entities.textbook_passages import TEXTBOOK_PASSAGE
from routers.generic import render
from schemas import (
    SearchSchema,
    TextbookPassageBulkReplaceSchema,
    TextbookPassageCreationSchema,
    TextbookPassageUpdateSchema,
)

router = APIRouter(
    prefix="/api/v1/textbook-passages", tags=["Textbook Passage Operations"]
)


@router.post(
    "",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Create textbook passage",
    description="Create a single extracted textbook passage linked to a textbook artifact.",
)
@render()
def api_create_textbook_passage(
    request: Request,
    payload: TextbookPassageCreationSchema,
):
    return TEXTBOOK_PASSAGE.create_entity(
        payload.model_dump(mode="json", exclude_none=True),
        creator=kutils.current_user(request),
    )


@router.get(
    "/by-textbook/{textbook_urn}",
    summary="Fetch passages for a textbook",
    description="Retrieve extracted passages linked to a specific textbook URN.",
)
@render()
def api_fetch_textbook_passages(
    request: Request,
    textbook_urn: str,
    limit: int = 1000,
    offset: int = 0,
    viewer: dict = Depends(auth()),
):
    return TEXTBOOK_PASSAGE.fetch_for_textbook(
        textbook_urn=textbook_urn,
        limit=limit,
        offset=offset,
        viewer=viewer,
    )


@router.post(
    "/by-textbook/{textbook_urn}/search",
    summary="Search passages for a textbook",
    description="Search, paginate, filter, and facet extracted passages linked to a textbook URN.",
)
@render()
def api_search_textbook_passages(
    request: Request,
    textbook_urn: str,
    q: SearchSchema,
    viewer: dict = Depends(auth()),
):
    return TEXTBOOK_PASSAGE.search_for_textbook(
        textbook_urn=textbook_urn,
        query=q.model_dump(mode="json", exclude_none=True),
        viewer=viewer,
    )


@router.get(
    "/{id}",
    summary="Get textbook passage by ID",
    description="Retrieve a specific extracted textbook passage by its UUID.",
)
@render()
def api_get_textbook_passage(
    request: Request, id: str, viewer: dict = Depends(auth())
):
    return TEXTBOOK_PASSAGE.get(id, viewer=viewer)


@router.patch(
    "/{id}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Update textbook passage",
    description="Partially update a single extracted textbook passage by UUID.",
)
@render()
def api_patch_textbook_passage(
    request: Request,
    id: str,
    payload: TextbookPassageUpdateSchema,
):
    return TEXTBOOK_PASSAGE.patch_entity_with_actor(
        id,
        payload.model_dump(mode="json", exclude_unset=True),
        actor=kutils.current_user(request),
    )


@router.delete(
    "/{id}",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Delete textbook passage",
    description="Delete a single extracted textbook passage by UUID.",
)
@render()
def api_delete_textbook_passage(request: Request, id: str):
    return TEXTBOOK_PASSAGE.delete_entity(id)


@router.post(
    "/by-textbook/{textbook_urn}/replace",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Replace passages for a textbook artifact",
    description="Replace extracted passages for one textbook artifact and optionally update textbook page metadata.",
)
@render()
def api_replace_textbook_passages(
    request: Request,
    textbook_urn: str,
    payload: TextbookPassageBulkReplaceSchema,
):
    return TEXTBOOK_PASSAGE.replace_for_textbook(
        textbook_urn=textbook_urn,
        spec=payload.model_dump(mode="json", exclude_none=True),
        creator=kutils.current_user(request),
    )
