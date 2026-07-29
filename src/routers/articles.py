from fastapi import APIRouter, Request, Depends, UploadFile, Form, File
from fastapi.responses import StreamingResponse
from routers.generic import render
from schemas import (
    ArticleCreationSchema,
    ArticleEditorialPolicySchema,
    ArticleUpdateSchema,
    SearchSchema,
    ArticleEnhancementSchema,
    ArticleAutocompleteSchema,
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
    "/autocomplete",
    dependencies=[Depends(auth())],
    summary="Autocomplete articles",
    description="Search articles by title prefix and return minimal representations for dropdown display.",
)
@render()
def api_autocomplete_articles(request: Request, q: str = "", limit: int = 15):
    query = {"q": q, "limit": limit, "fl": ["urn", "title", "authors", "publication_year", "venue"]}
    response = ARTICLE.search_entities(query=query)
    results = response.get("results", []) if isinstance(response, dict) else response
    return [ArticleAutocompleteSchema.model_validate(r).model_dump(mode="json") for r in results]


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
    dependencies=[Depends(auth(("admin", "expert", "agent")))],
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
    dependencies=[Depends(auth(("admin", "expert", "agent")))],
    summary="Update article details",
    description="Update the details of an existing article by its ID.",
)
@render()
def api_patch_article(request: Request, urn: str, a: ArticleUpdateSchema):
    return ARTICLE.patch_entity(urn, a.model_dump(mode="json"))


@router.post(
    "/policy",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Batch-edit editorial policy",
    description=(
        "Set reader visibility and/or indexing tier on every article matching a "
        "selection. Select by explicit URN list, by free-text query `q`, by `fq` "
        "filter clauses, or any combination — the same semantics as "
        "`POST /articles/search`, so the console can apply an edit to exactly "
        "the result set the editor is browsing.\n\n"
        "`reader_visibility` controls who reads the article: `public` (everyone), "
        "`expert_only` (hidden from beginner/intermediate readers) or `hidden` "
        "(no readers). `indexing_tier` controls retrieval priority, with `prime` "
        "reserved for editorially promoted, influential work; send "
        "`clear_indexing_tier` to fall back to the agent's `ai_indexing_tier`.\n\n"
        "Send `dry_run: true` first: it returns the match count and a sample "
        "without writing. Updates are capped at 10000 documents, and a selection "
        "matching the entire corpus is rejected."
    ),
)
@render()
def api_set_article_policy(request: Request, a: ArticleEditorialPolicySchema):
    return ARTICLE.set_editorial_policy(
        urns=a.urns,
        q=a.q,
        fq=a.fq,
        reader_visibility=a.reader_visibility,
        indexing_tier=a.indexing_tier,
        clear_indexing_tier=a.clear_indexing_tier,
        max_docs=a.max_docs,
        dry_run=a.dry_run,
        updater=kutils.current_user(request),
    )


@router.patch(
    "/{urn}/enhance",
    dependencies=[Depends(auth(("admin", "expert", "agent")))],
    summary="Enhance an article",
    description="Apply AI-generated enhancements to an article by its URN.",
)
@render()
def api_enhance_article(request: Request, urn: str, a: ArticleEnhancementSchema):
    return ARTICLE.enhance_entity(urn, a, kutils.current_user(request))

@router.delete(
    "/{urn}",
    dependencies=[Depends(auth(("admin", "expert", "agent")))],
    summary="Delete an article",
    description="Delete an article from the system by its URN.",
)
@render()
def api_delete_article(request: Request, urn: str):
    return ARTICLE.delete_entity(urn)
