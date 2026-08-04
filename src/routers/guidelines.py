from fastapi import APIRouter, Depends, Request

import kutils
from auth import auth
from entities.guidelines import GUIDELINE
from routers.generic import render
from schemas import (
    GuidelineAutocompleteSchema,
    GuidelineBulkImportSchema,
    GuidelineCreationSchema,
    GuidelineEditorialPolicySchema,
    GuidelineEnrichmentBatchSchema,
    GuidelineEnrichmentSchema,
    GuidelineUpdateSchema,
    SearchSchema,
)

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
    "/autocomplete",
    summary="Autocomplete dietary guidelines",
    description="Search guidelines by title/rule_text prefix and return minimal representations for dropdown display.",
)
@render()
def api_autocomplete_guidelines(
    request: Request,
    q: str = "",
    limit: int = 15,
    viewer: dict = Depends(auth()),
):
    query = {"q": q, "limit": limit, "fl": ["id", "guide_urn", "title", "action_type"]}
    response = GUIDELINE.search(query=query, viewer=viewer)
    results = response.get("results", []) if isinstance(response, dict) else response
    return [GuidelineAutocompleteSchema.model_validate(r).model_dump(mode="json") for r in results]


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


@router.post(
    "/enrich-batch",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Batch machine enrichment of guidelines",
    description=(
        "Write machine-derived facets (life stage, setting, nutrients, ...) onto up to "
        "200 guidelines in one call. Fields with human-edited values are skipped unless "
        "explicitly forced. Use dry_run to preview what would be written."
    ),
)
@render()
def api_enrich_guidelines_batch(
    request: Request,
    payload: GuidelineEnrichmentBatchSchema,
):
    return GUIDELINE.enrich_batch(payload, enricher=kutils.current_user(request))


@router.post(
    "/editorial-policy",
    dependencies=[Depends(auth(("admin",)))],
    summary="Batch edit guideline lifecycle state",
    description=(
        "Bulk-set status/review_status/visibility/applicability_status on every matching "
        "guideline (e.g. activate a reviewed guide's rules so they become retrievable). "
        "Selection requires ids, q, or fq — never the whole corpus. Always dry_run first."
    ),
)
@render()
def api_guideline_editorial_policy(
    request: Request,
    payload: GuidelineEditorialPolicySchema,
):
    return GUIDELINE.set_editorial_policy(payload, updater=kutils.current_user(request))


@router.post(
    "/embeddings/backfill",
    dependencies=[Depends(auth(("admin",)))],
    summary="Queue existing guidelines for embedding",
    description=(
        "Queue stored guidelines for semantic embedding. Defaults to rules that "
        "have no vector yet, so the call is safe to repeat and resumable after "
        "an interruption. Scope to one guide with guide_urn."
    ),
)
@render()
def api_backfill_guideline_embeddings(
    request: Request,
    guide_urn: str | None = None,
    only_missing: bool = True,
    max_docs: int | None = None,
    dry_run: bool = False,
):
    return GUIDELINE.backfill_embeddings(
        guide_urn=guide_urn,
        only_missing=only_missing,
        max_docs=max_docs,
        dry_run=dry_run,
    )


@router.patch(
    "/{id}/enrich",
    dependencies=[Depends(auth(("admin", "expert")))],
    summary="Machine-enrich a single guideline",
    description=(
        "Write machine-derived facets onto one guideline. Human-edited values are "
        "preserved unless the field is listed in force_fields."
    ),
)
@render()
def api_enrich_guideline(
    request: Request,
    id: str,
    payload: GuidelineEnrichmentSchema,
):
    return GUIDELINE.enrich(id, payload, enricher=kutils.current_user(request))


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
