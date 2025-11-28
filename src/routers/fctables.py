from fastapi import APIRouter, Request, Depends, UploadFile, Form, File
from fastapi.responses import StreamingResponse
from routers.generic import render
from schemas import FoodCompositionTableCreationSchema, FoodCompositionTableUpdateSchema, SearchSchema
import kutils
from exceptions import DataError
from entities.fctables import FCTABLE
from auth import auth
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/fctables", tags=["Food Composition Tables Management Operations"])


@router.get(
    "",
    dependencies=[Depends(auth())],
    summary="List Food Composition Tables",
    description="Retrieve a paginated list of food composition tables from the database."
)
@render()
def api_list_fctables(request: Request, limit: int = 100, offset: int = 0):
    return FCTABLE.list_entities(limit=limit, offset=offset)


@router.get(
    "/fetch",
    dependencies=[Depends(auth())],
    summary="Fetch Food Composition Tables",
    description="Fetch a paginated collection of food composition tables with detailed information."
)
@render()
def api_fetch_fctables(request: Request, limit: int = 100, offset: int = 0):
    return FCTABLE.fetch_entities(limit=limit, offset=offset)


@router.get(
    "/{urn}",
    dependencies=[Depends(auth())],
    summary="Get food composition table details",
    description="Retrieve details of a specific food composition table by its URN.",
)
@render()
def api_get_fctable(request: Request, urn: str):
    return FCTABLE.get_entity(urn)

@router.post(
    "",
    dependencies=[Depends(auth())],
    summary="Create a new food composition table",
    description="Create a new food composition table in the system using the provided data.",
)
@render()
def api_create_fctable(request: Request, a: FoodCompositionTableCreationSchema):
    return FCTABLE.create_entity(
        a.model_dump(mode="json"), kutils.current_user(request)
    )

@router.post(
    "/search",
    dependencies=[Depends(auth())],
    summary="Search food composition tables",
    description="Search for food composition tables based on specified criteria."
)
@render()
def api_search_fctables(request: Request, q: SearchSchema):
    return FCTABLE.search_entities(query=q)


@router.patch(
    "/{urn}",
    dependencies=[Depends(auth())],
    summary="Update food composition table details",
    description="Update the details of an existing food composition table by its URN.",
)
@render()
def api_patch_fctable(request: Request, urn: str, a: FoodCompositionTableUpdateSchema):
    return FCTABLE.patch_entity(urn, a.model_dump(mode="json"))


@router.delete(
    "/{urn}",
    dependencies=[Depends(auth())],
    summary="Delete a food composition table",
    description="Delete a food composition table from the system by its URN.",
)
@render()
def api_delete_fctable(request: Request, urn: str):
    return FCTABLE.delete_entity(urn)
