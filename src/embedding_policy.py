"""
Which writes invalidate a stored embedding.

An entity's vector is built from a fixed subset of its fields. Any write path
that changes one of those fields must re-embed, or the stored vector goes on
describing text that is no longer there.

That failure is silent, and worse than never embedding at all: `embedded_at`
stays populated, so the document still looks embedded, semantic retrieval keeps
matching the previous wording, and `backfill_embeddings(only_missing=True)`
skips it forever. Nothing surfaces the drift.

This module holds the field sets and the predicate so that every write path
consults one definition. It deliberately imports nothing — `backend.elastic`
opens a connection at import time, which would make this untestable without a
live cluster, and the point of the module is that the rule can be tested.
"""

from datetime import datetime
from typing import Iterable, Optional, Sequence

# The fields `Article.embed()` concatenates into its embedding text.
EMBEDDED_ARTICLE_FIELDS: Sequence[str] = ("title", "abstract", "content")

# The non-facet fields `Guideline._embedding_text()` builds from. The facet
# fields are appended by the entity, which owns that list.
EMBEDDED_GUIDELINE_FIELDS: Sequence[str] = ("rule_text", "title", "notes")


def requires_reembedding(
    changed_fields: Iterable[str], embedded_fields: Iterable[str]
) -> bool:
    """
    Whether a write touching `changed_fields` invalidates the stored vector.

    `changed_fields` is what the caller actually sent — for a partial update
    that means the keys present after `exclude_unset`, not every field on the
    schema. A status-only edit therefore costs nothing, while a title-only edit
    re-embeds.
    """
    embedded = set(embedded_fields)
    return any(field in embedded for field in changed_fields)


def embedding_is_stale(
    updated_at: Optional[str], embedded_at: Optional[str]
) -> bool:
    """
    Whether a document was edited after its vector was computed.

    This is the recovery side of the rule above. Documents edited while a write
    path was not re-embedding — or while Redis was down, since every enqueue is
    fire-and-forget — carry a vector describing older text. They cannot be found
    by looking for a missing `embedded_at`, because theirs is set; the only
    evidence is that `updated_at` moved past it.

    Both timestamps are written as naive `datetime.now().isoformat()`, so they
    are directly comparable.

    Judgement calls at the edges:

    - No `embedded_at` means never embedded, which is *missing*, not stale. The
      caller handles that case and would otherwise count it twice.
    - No `updated_at` means there is nothing to compare against, so the vector
      is assumed current rather than re-queued on no evidence.
    - An unparseable timestamp is treated as stale. Backfill is an explicit,
      capped, operator-invoked action, so re-embedding on bad data is the
      cheaper mistake — silently keeping a wrong vector is the expensive one.
    """
    if not embedded_at:
        return False
    if not updated_at:
        return False

    try:
        return datetime.fromisoformat(updated_at) > datetime.fromisoformat(embedded_at)
    except (TypeError, ValueError):
        return True
