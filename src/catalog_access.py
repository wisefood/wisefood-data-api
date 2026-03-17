"""Shared helpers for catalog visibility and role-based viewing rules."""

from __future__ import annotations

from typing import Any, Dict


PRIVILEGED_CATALOG_ROLES = frozenset({"admin", "expert"})
APPROVED_OR_ACTIVE_FILTER = "(review_status:verified OR status:active)"


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
