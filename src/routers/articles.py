from fastapi import APIRouter, Request, Depends, UploadFile, Form, File
from fastapi.responses import StreamingResponse
from routers.generic import render
from schemas import (
    ArticleCreationSchema,
    ArticleUpdateSchema,
    SearchSchema,
    ArticleEnhancementSchema,
)
import kutils
from entities.articles import ARTICLE
from backend.elastic import ELASTIC_CLIENT
from es_schema import article_index
from auth import auth
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/articles", tags=["Articles Management Operations"])


@router.get(
    "",
    dependencies=[Depends(auth())],
    summary="List articles",
    description="Retrieve a paginated list of articles from the database.",
)
@render()
def api_list_articles(request: Request, limit: int = 100, offset: int = 0):
    return ARTICLE.list_entities(limit=limit, offset=offset)


@router.get(
    "/fetch",
    dependencies=[Depends(auth())],
    summary="Fetch articles",
    description="Fetch a paginated collection of articles with detailed information.",
)
@render()
def api_fetch_articles(request: Request, limit: int = 100, offset: int = 0):
    return ARTICLE.fetch_entities(limit=limit, offset=offset)


@router.get(
    "/{urn}",
    dependencies=[Depends(auth())],
    summary="Get article details",
    description="Retrieve details of a specific article by its URN.",
)
@render()
def api_get_article(request: Request, urn: str):
    return ARTICLE.get_entity(urn)


@router.post(
    "",
    dependencies=[Depends(auth())],
    summary="Create a new article",
    description="Create a new article in the system using the provided data.",
)
@render()
def api_create_article(request: Request, a: ArticleCreationSchema):
    return ARTICLE.create_entity(
        a.model_dump(mode="json"), kutils.current_user(request)
    )


@router.post(
    "/search",
    dependencies=[Depends(auth())],
    summary="Search articles",
    description="Search for articles based on specified criteria.",
)
@render()
def api_search_articles(request: Request, q: SearchSchema):
    return ARTICLE.search_entities(query=q)


@router.patch(
    "/{urn}",
    dependencies=[Depends(auth())],
    summary="Update article details",
    description="Update the details of an existing article by its ID.",
)
@render()
def api_patch_article(request: Request, urn: str, a: ArticleUpdateSchema):
    return ARTICLE.patch_entity(urn, a.model_dump(mode="json"))


@router.patch(
    "/{urn}/enhance",
    dependencies=[Depends(auth("agent"))],
    summary="Enhance an article",
    description="Apply AI-generated enhancements to an article by its URN.",
)
@render()
def api_enhance_article(request: Request, urn: str, a: ArticleEnhancementSchema):
    return ARTICLE.enhance_entity(urn, a, kutils.current_user(request))


@router.post(
    "/rebuild",
    dependencies=[Depends(auth())],
    summary="Rebuild article index",
    description="Rebuild the entire article index in the database.",
)
@render()
def api_rebuild_article_index(request: Request):
    return ELASTIC_CLIENT.rebuild_index(
        alias_name="articles",
        new_index_name="articles_v2",
        mapping=article_index(384)["mappings"],
        settings=article_index(384)["settings"],
        delete_old=False,
    )


@router.delete(
    "/{urn}",
    dependencies=[Depends(auth())],
    summary="Delete an article",
    description="Delete an article from the system by its URN.",
)
@render()
def api_delete_article(request: Request, urn: str):
    return ARTICLE.delete_entity(urn)
