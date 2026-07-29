"""Shared helpers for catalog visibility and role-based viewing rules."""

from __future__ import annotations

from typing import Any, Dict


PRIVILEGED_CATALOG_ROLES = frozenset({"admin", "expert"})
APPROVED_OR_ACTIVE_FILTER = "(review_status:verified OR status:active)"
PUBLIC_CATALOG_FILTER = "(visibility:public AND (review_status:verified OR status:active))"

# Reader-facing article visibility (see schemas.ReaderVisibility). This is a
# different axis from `visibility`, which gates staff/API access: it describes
# which *readers* an article is appropriate for.
#
# Every clause below is phrased as an exclusion. Articles indexed before
# `reader_visibility` existed have no value for it, and a positive clause
# (`reader_visibility:public`) would drop every one of them; an exclusion keeps
# them, which is the intended default.
EXCLUDE_NON_PUBLIC_READER_FILTER = "NOT reader_visibility:(expert_only OR hidden)"
EXCLUDE_HIDDEN_READER_FILTER = "NOT reader_visibility:hidden"

# Reader expertise levels that may see `expert_only` articles. Mirrors
# FoodScholar's QA `expertise_level` vocabulary (beginner|intermediate|expert).
EXPERT_READER_LEVELS = frozenset({"expert"})


def extract_roles(claims: Dict[str, Any] | None) -> set[str]:
    """Collect normalized roles from JWT claims across realm and client scopes."""
    if not claims:
        return set()

    roles = set()
    realm_access = claims.get("realm_access") or {}
    roles.update(str(role).strip().lower() for role in (realm_access.get("roles") or []))

    resource_access = claims.get("resource_access") or {}
    for client_access in resource_access.values():
        roles.update(
            str(role).strip().lower() for role in (client_access.get("roles") or [])
        )

    return {role for role in roles if role}


def can_view_unapproved_catalog(claims: Dict[str, Any] | None) -> bool:
    """Return whether the caller may bypass public catalog visibility filters."""
    return bool(extract_roles(claims) & PRIVILEGED_CATALOG_ROLES)


def is_approved_or_active(entity: Dict[str, Any] | None) -> bool:
    """Treat verified or active records as visible to non-privileged viewers."""
    if not entity:
        return False
    return (
        entity.get("review_status") == "verified"
        or entity.get("status") == "active"
    )


def apply_catalog_visibility_filter(
    query: Dict[str, Any], *, exclude_deleted: bool = False
) -> Dict[str, Any]:
    """Append the public visibility clause to an Elasticsearch-style search query."""
    filtered_query = dict(query)
    fq = list(filtered_query.get("fq") or [])
    fq.append(APPROVED_OR_ACTIVE_FILTER)
    if exclude_deleted and "NOT status:deleted" not in fq:
        fq.append("NOT status:deleted")
    filtered_query["fq"] = fq
    return filtered_query


def is_publicly_visible(entity: Dict[str, Any] | None) -> bool:
    """Return whether a catalog entity is publicly visible to non-privileged viewers."""
    if not entity:
        return False

    return (
        entity.get("visibility") == "public"
        and (
            entity.get("review_status") == "verified"
            or entity.get("status") == "active"
        )
    )


def is_expert_reader(reader_level: str | None) -> bool:
    """Whether a reader's expertise level may see `expert_only` articles."""
    if not reader_level:
        return False
    return str(reader_level).strip().lower() in EXPERT_READER_LEVELS


def reader_visibility_clause(reader_level: str | None) -> str:
    """The filter clause that hides articles this reader should not see."""
    if is_expert_reader(reader_level):
        return EXCLUDE_HIDDEN_READER_FILTER
    return EXCLUDE_NON_PUBLIC_READER_FILTER


def is_visible_to_reader(
    entity: Dict[str, Any] | None, reader_level: str | None
) -> bool:
    """
    Whether an article may be shown to a reader at this expertise level.

    An absent `reader_visibility` means `public`, so articles predating the
    field stay readable.
    """
    if not entity:
        return False

    visibility = entity.get("reader_visibility") or "public"
    if visibility == "hidden":
        return False
    if visibility == "expert_only":
        return is_expert_reader(reader_level)
    return True


def apply_reader_visibility_filter(
    query: Dict[str, Any], reader_level: str | None
) -> Dict[str, Any]:
    """Append the reader-visibility clause to an Elasticsearch-style query."""
    filtered_query = dict(query)
    fq = list(filtered_query.get("fq") or [])
    clause = reader_visibility_clause(reader_level)
    if clause not in fq:
        fq.append(clause)
    filtered_query["fq"] = fq
    return filtered_query


def apply_public_catalog_filter(
    query: Dict[str, Any], *, exclude_deleted: bool = False
) -> Dict[str, Any]:
    """Append the explicit public visibility clause to an Elasticsearch-style search query."""
    filtered_query = dict(query)
    fq = list(filtered_query.get("fq") or [])
    fq.append(PUBLIC_CATALOG_FILTER)
    if exclude_deleted and "NOT status:deleted" not in fq:
        fq.append("NOT status:deleted")
    filtered_query["fq"] = fq
    return filtered_query
