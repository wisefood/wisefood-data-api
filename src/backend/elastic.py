import os
import re
import threading
from datetime import datetime
from elasticsearch import Elasticsearch, NotFoundError, BadRequestError, helpers
from typing import Optional, List, Dict, Any
from es_schema import (
    recipe_collection_index,
    rcollection_index,
    article_index,
    guide_index,
    guideline_index,
    textbook_index,
    textbook_passage_index,
    organization_index,
    person_index,
    artifact_index,
    fctable_index,
    rag_chunk_index
)
from schemas import SearchSchema
from exceptions import InvalidError
import logging

logger = logging.getLogger(__name__)

ELASTIC_HOST = os.getenv("ELASTIC_HOST", "http://elasticsearch:9200")
ES_DIM = int(os.getenv("ES_DIM", 384))
# Elasticsearch's index-level "max_result_window" defaults to 10000, which caps
# from+size pagination and makes the bulk of a large corpus unreachable by
# browsing. We raise it so every document is reachable via offset paging. The
# value is applied to each index's settings in _bootstrap(). Keep this in sync
# with the per-index "index.max_result_window" setting; a hard ceiling guards
# against pathologically large windows that would blow up node heap.
MAX_RESULT_WINDOW = min(
    int(os.getenv("ELASTIC_MAX_RESULT_WINDOW", "50000")), 1_000_000
)
SCROLL_KEEPALIVE = os.getenv("ELASTIC_SCROLL_KEEPALIVE", "1m")
SCROLL_BATCH_SIZE = int(os.getenv("ELASTIC_SCROLL_BATCH_SIZE", "1000"))

# Every index this service owns, and how to build its mapping. Bootstrap walks
# this, and so does the admin index-state view — a single list means an index
# cannot be created at startup yet be invisible to operators.
INDEX_BUILDERS = {
    "rcollections": rcollection_index,
    "guides": guide_index,
    "guidelines": guideline_index,
    "textbooks": textbook_index,
    "textbook_passages": textbook_passage_index,
    "artifacts": artifact_index,
    "articles": article_index,
    "organizations": organization_index,
    "persons": person_index,
    "fctables": fctable_index,
    "rag_chunks": rag_chunk_index,
}

# Indices whose documents carry a semantic vector, and the field each is keyed
# by — used to report embedding coverage.
EMBEDDED_INDEX_IDENTIFIERS = {
    "articles": "urn",
    "guidelines": "id",
    "guides": "urn",
    "textbooks": "urn",
    "rcollections": "urn",
}

DEFAULT_FACET_EXCLUDE_FIELDS = {
    # long text / content
    "abstract",
    "content",
    "description",
    "instructions",
    "bio",
    "text",
    "snippet",
    "page_summary",
    "key_takeaways",
    "ai_key_takeaways",
    # semantic-only
    "embedding",
    "embedded_at",

    # technical / audit
    "before",
    "after",
}

NON_FACET_SEMANTIC_FIELDS = {
    # identifiers
    "id",
    "urn",
    "external_id",
    "url",

    # timestamps
    "created_at",
    "updated_at",
    "embedded_at",

    # display-only
    "title",

    # governance / audit
    "status",
    "verifier_user_id",
    "license",
    "ai_generated_fields",

    # extraction / enrichment provenance
    "extractor_name",
    "extractor_run_id",
    "extraction_model",
    "enrichment_version",
    "enrichment_confidence",
}


class ElasticsearchClientSingleton:
    """Singleton around a single thread-safe Elasticsearch client."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._client = Elasticsearch(
                        hosts=ELASTIC_HOST,
                        # Optional tuning:
                        # request_timeout=10,
                        # max_retries=3,
                        # retry_on_timeout=True,
                    )
                    instance._bootstrap()
                    cls._instance = instance
        return cls._instance

    @property
    def client(self) -> Elasticsearch:
        return self._client

    def _bootstrap(self) -> None:
        """Create indices in Elasticsearch if they do not exist."""
        indices = self._client.indices

        def ensure_index(name: str, body: Dict[str, Any]) -> None:
            if not indices.exists(index=name):
                logger.info("Creating index %s", name)
                # Inject our raised result window into the new index's settings.
                settings = dict(body.get("settings") or {})
                settings.setdefault("index", {})
                settings["index"] = {
                    **settings["index"],
                    "max_result_window": MAX_RESULT_WINDOW,
                }
                indices.create(index=name, body={**body, "settings": settings})
            else:
                # Index already exists (e.g. an established corpus): make sure
                # its result window matches our current setting so deep browsing
                # works without recreating/reindexing.
                self._ensure_result_window(name)
                self._ensure_mapping_fields(name, body)

        for name, builder in INDEX_BUILDERS.items():
            ensure_index(name, builder(ES_DIM))

    def _ensure_mapping_fields(self, name: str, body: Dict[str, Any]) -> None:
        """
        Add mapping properties this code knows about but the live index lacks.

        Without this, a field added to ``es_schema`` never reaches an existing
        corpus: ``ensure_index`` only builds mappings at creation time. Worse,
        the first document written with an unmapped string field gets ES's
        dynamic ``text`` + ``.keyword`` treatment, and a term filter on it
        silently matches nothing — a type that then cannot be corrected without
        a full reindex.

        Only *new* top-level properties are pushed. Changing the type of an
        existing field is not something ES allows in place, so those are left
        alone (and logged) rather than attempted.
        """
        desired = ((body.get("mappings") or {}).get("properties")) or {}
        if not desired:
            return

        try:
            current = self._client.indices.get_mapping(index=name)
            live = (
                current[name]["mappings"].get("properties", {})
                if name in current
                else {}
            )
        except Exception:
            logger.warning("Could not read mapping for %s", name, exc_info=True)
            return

        missing = {
            field: definition
            for field, definition in desired.items()
            if field not in live
        }
        if not missing:
            return

        try:
            self._client.indices.put_mapping(
                index=name,
                body={"properties": missing},
            )
            logger.info(
                "Added %d mapping field(s) to existing index %s: %s",
                len(missing),
                name,
                ", ".join(sorted(missing)),
            )
        except Exception:
            logger.warning(
                "Failed to add mapping fields %s to %s",
                ", ".join(sorted(missing)),
                name,
                exc_info=True,
            )

    def _ensure_result_window(self, name: str) -> None:
        """Update an existing index's max_result_window if it's below our target."""
        try:
            current = self._client.indices.get_settings(index=name)
            window = int(
                current[name]["settings"]["index"].get("max_result_window", 10000)
            )
        except Exception:
            window = 10000

        if window >= MAX_RESULT_WINDOW:
            return

        try:
            self._client.indices.put_settings(
                index=name,
                body={"index": {"max_result_window": MAX_RESULT_WINDOW}},
            )
            logger.info(
                "Raised max_result_window on %s to %s", name, MAX_RESULT_WINDOW
            )
        except Exception:
            logger.warning(
                "Failed to update max_result_window on %s", name, exc_info=True
            )

    # --- Simple helpers -----------------------------------------------------

    def index_exists(self, index_name: str) -> bool:
        return self.client.indices.exists(index=index_name)

    def get_entity(self, index_name: str, urn: str) -> Optional[Dict[str, Any]]:
        try:
            r = self.client.get(index=index_name, id=urn)
            return r["_source"]
        except NotFoundError:
            return None
        except Exception:
            logger.exception("Error fetching entity %s from %s", urn, index_name)
            raise

    @staticmethod
    def _active_entities_query() -> Dict[str, Any]:
        return {"bool": {"must_not": {"term": {"status": "deleted"}}}}

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        if limit < 0 or offset < 0:
            raise InvalidError("Limit and offset must be greater than or equal to 0.")

    def _validate_result_window(self, *, limit: int, offset: int, operation: str) -> None:
        self._validate_pagination(limit, offset)
        result_window = limit + offset
        if result_window <= MAX_RESULT_WINDOW:
            return

        raise InvalidError(
            detail=(
                f"{operation} pagination exceeds Elasticsearch's maximum result window "
                f"of {MAX_RESULT_WINDOW}. Received offset={offset}, limit={limit}, "
                f"window={result_window}."
            ),
            extra={"title": "InvalidPagination"},
        )

    def _scroll_entities(
        self,
        *,
        index_name: str,
        limit: int,
        offset: int,
        source: bool,
    ) -> List[Dict[str, Any]]:
        self._validate_pagination(limit, offset)
        if limit == 0:
            return []

        batch_size = max(1, min(SCROLL_BATCH_SIZE, max(limit, 100)))
        body: Dict[str, Any] = {
            "size": batch_size,
            "sort": ["_doc"],
            "query": self._active_entities_query(),
        }
        if not source:
            body["_source"] = False

        logger.info(
            "Using scroll fallback for %s (offset=%s, limit=%s)",
            index_name,
            offset,
            limit,
        )

        scroll_id = None
        skipped = 0
        collected: List[Dict[str, Any]] = []

        try:
            response = self.client.search(
                index=index_name,
                body=body,
                scroll=SCROLL_KEEPALIVE,
            )
            scroll_id = response.get("_scroll_id")

            while True:
                hits = response["hits"]["hits"]
                if not hits:
                    break

                if skipped < offset:
                    if skipped + len(hits) <= offset:
                        skipped += len(hits)
                    else:
                        start = offset - skipped
                        needed = limit - len(collected)
                        collected.extend(hits[start : start + needed])
                        skipped = offset
                else:
                    needed = limit - len(collected)
                    collected.extend(hits[:needed])

                if len(collected) >= limit:
                    break

                response = self.client.scroll(
                    scroll_id=scroll_id,
                    scroll=SCROLL_KEEPALIVE,
                )
                scroll_id = response.get("_scroll_id", scroll_id)

            return collected
        finally:
            if scroll_id:
                try:
                    self.client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    logger.warning(
                        "Failed to clear scroll for %s", index_name, exc_info=True
                    )

    def list_entities(
        self, index_name: str, size: int = 1000, offset: int = 0
    ) -> List[str]:
        self._validate_pagination(size, offset)
        if size + offset > MAX_RESULT_WINDOW:
            hits = self._scroll_entities(
                index_name=index_name,
                limit=size,
                offset=offset,
                source=False,
            )
            return [h["_id"] for h in hits]

        body = {
            "from": offset,
            "size": size,
            "_source": False,
            "sort": ["_doc"],
            "query": self._active_entities_query(),
        }
        r = self.client.search(index=index_name, body=body)
        return [h["_id"] for h in r["hits"]["hits"]]

    def fetch_entities(
        self, index_name: str, limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        self._validate_pagination(limit, offset)
        if limit + offset > MAX_RESULT_WINDOW:
            hits = self._scroll_entities(
                index_name=index_name,
                limit=limit,
                offset=offset,
                source=True,
            )
            return [hit["_source"] for hit in hits]

        body = {
            "from": offset,
            "size": limit,
            "sort": ["_doc"],
            "query": self._active_entities_query(),
        }
        r = self.client.search(index=index_name, body=body)
        return [hit["_source"] for hit in r["hits"]["hits"]]

    def index_entity(self, index_name: str, document: Dict[str, Any]) -> None:
        doc_id = document.get("urn", document.get("id"))
        self.client.index(
            index=index_name,
            id=doc_id,
            document=document,
            refresh="wait_for",
        )

    def delete_entity(self, index_name: str, urn: str) -> None:
        self.client.delete(index=index_name, id=urn, refresh="wait_for")

    def update_entity(
        self,
        index_name: str,
        document: Dict[str, Any],
        *,
        refresh: Any = "wait_for",
    ) -> None:
        """
        Merge a partial document into an existing entity.

        ``refresh`` defaults to ``wait_for`` because most callers are servicing
        a request that will immediately re-read what it just wrote. Bulk writers
        should pass ``refresh=False``: ``wait_for`` blocks until the index's next
        refresh cycle (a second by default), which serializes a few thousand
        background writes into an hour of waiting for no benefit, since nothing
        reads those documents synchronously.
        """
        identifier = document.get("urn", document.get("id"))
        if not identifier:
            raise ValueError("document must include either 'urn' or 'id'")

        # Avoid updating if only system fields are present
        if set(document.keys()) in ({"updated_at", "urn"}, {"updated_at", "id"}):
            return

        existing = self.get_entity(index_name, identifier)
        if not existing:
            return

        merged = {**existing, **document}
        self.client.update(
            index=index_name,
            id=identifier,
            doc=merged,
            refresh=refresh,
        )

    def enhance_entity(
        self,
        index_name: str,
        urn: str,
        *,
        fields: Dict[str, Any],
        enhancement_event: Dict[str, Any],
        updated_at: str | None = None,
    ) -> None:
        """
        Append an AI enhancement event and update fields atomically.
        """

        updated_at = updated_at or datetime.now().isoformat()

        self.client.update(
            index=index_name,
            id=urn,
            refresh="wait_for",
            script={
                "lang": "painless",
                "source": """
                    if (ctx._source.enhancements == null) {
                        ctx._source.enhancements = [];
                    }
                    ctx._source.enhancements.add(params.event);

                    if (ctx._source.ai_generated_fields == null) {
                        ctx._source.ai_generated_fields = [];
                    }

                    for (entry in params.fields.entrySet()) {
                        ctx._source[entry.getKey()] = entry.getValue();

                        if (!ctx._source.ai_generated_fields.contains(entry.getKey())) {
                            ctx._source.ai_generated_fields.add(entry.getKey());
                        }
                    }

                    ctx._source.updated_at = params.updated_at;
                """,
                "params": {
                    "event": enhancement_event,
                    "fields": fields,
                    "updated_at": updated_at,
                },
            },
        )

    # ------------------------------------------------------------------ #
    # Operational introspection (admin console)
    # ------------------------------------------------------------------ #

    def cluster_state(self) -> Dict[str, Any]:
        """Cluster health, or a reachable=False report if the cluster is down."""
        try:
            health = self.client.cluster.health()
        except Exception as exc:
            logger.warning("Could not read cluster health: %s", exc)
            return {"reachable": False, "error": str(exc)}

        return {
            "reachable": True,
            "cluster_name": health.get("cluster_name"),
            "status": health.get("status"),
            "number_of_nodes": health.get("number_of_nodes"),
            "active_shards": health.get("active_shards"),
            "unassigned_shards": health.get("unassigned_shards"),
        }

    def index_state(self) -> List[Dict[str, Any]]:
        """
        Per-index doc counts, size, and mapping drift against the code.

        ``missing_fields`` is the point of this: it names the top-level mapping
        properties `es_schema` defines that the live index lacks. Startup adds
        them automatically, so a non-empty list means the index predates a
        change and has not been restarted into — or the field type conflicts and
        the additive migration skipped it, which needs a reindex.

        Three cluster round trips regardless of index count: mappings and
        settings are fetched for every index at once. Asking per index turned an
        admin page load into ~34 sequential calls.
        """
        names = list(INDEX_BUILDERS)
        joined = ",".join(names)

        def safe(call, default):
            try:
                return call()
            except Exception as exc:
                logger.warning("Index introspection call failed: %s", exc)
                return default

        stats = safe(
            lambda: self.client.indices.stats(metric="docs,store").get("indices", {}),
            {},
        )
        # ignore_unavailable keeps a single missing index from failing the batch.
        mappings = safe(
            lambda: self.client.indices.get_mapping(
                index=joined, ignore_unavailable=True
            ),
            {},
        )
        settings = safe(
            lambda: self.client.indices.get_settings(
                index=joined, ignore_unavailable=True
            ),
            {},
        )

        # An index reached through an alias reports under its concrete name, so
        # build a lookup that resolves either form.
        def resolve(source: Dict[str, Any], name: str):
            if name in source:
                return name, source[name]
            for concrete, value in source.items():
                aliases = value.get("aliases") if isinstance(value, dict) else None
                if aliases and name in aliases:
                    return concrete, value
            return None, None

        report: List[Dict[str, Any]] = []
        for name, builder in INDEX_BUILDERS.items():
            concrete, mapping_entry = resolve(mappings, name)
            entry: Dict[str, Any] = {"index": name, "exists": mapping_entry is not None}

            if mapping_entry is None:
                report.append(entry)
                continue

            if concrete and concrete != name:
                entry["concrete_index"] = concrete

            resolved_stats = stats.get(concrete or name) or {}
            primaries = resolved_stats.get("primaries", {})
            entry["doc_count"] = primaries.get("docs", {}).get("count")
            entry["deleted_docs"] = primaries.get("docs", {}).get("deleted")
            entry["size_bytes"] = primaries.get("store", {}).get("size_in_bytes")

            live_props = mapping_entry.get("mappings", {}).get("properties", {})
            expected_props = builder(ES_DIM).get("mappings", {}).get("properties", {})
            entry["mapped_fields"] = len(live_props)
            entry["missing_fields"] = sorted(set(expected_props) - set(live_props))

            _, settings_entry = resolve(settings, name)
            index_settings = (
                (settings_entry or {}).get("settings", {}).get("index", {})
            )
            window = index_settings.get("max_result_window")
            entry["max_result_window"] = int(window) if window else None
            entry["expected_max_result_window"] = MAX_RESULT_WINDOW

            report.append(entry)

        return report

    def embedding_state(self) -> List[Dict[str, Any]]:
        """
        Embedding coverage per index: how many documents carry a vector.

        ``missing`` is what a backfill would have to process, so this is how an
        operator knows whether hybrid retrieval is safe to switch on.

        One round trip for every index: a terms aggregation over ``_index`` with
        an embedded sub-filter, rather than two counts per index.
        """
        names = list(EMBEDDED_INDEX_IDENTIFIERS)
        report: Dict[str, Dict[str, Any]] = {
            name: {"index": name, "identifier_field": identifier, "exists": False}
            for name, identifier in EMBEDDED_INDEX_IDENTIFIERS.items()
        }

        try:
            response = self.client.search(
                index=",".join(names),
                ignore_unavailable=True,
                body={
                    "size": 0,
                    "query": {
                        "bool": {"must_not": [{"term": {"status": "deleted"}}]}
                    },
                    "aggs": {
                        "per_index": {
                            "terms": {"field": "_index", "size": len(names) * 2},
                            "aggs": {
                                "embedded": {
                                    "filter": {"exists": {"field": "embedded_at"}}
                                }
                            },
                        }
                    },
                },
            )
        except Exception as exc:
            logger.warning("Could not read embedding coverage: %s", exc)
            for entry in report.values():
                entry["error"] = str(exc)
            return list(report.values())

        buckets = response.get("aggregations", {}).get("per_index", {}).get("buckets", [])
        for bucket in buckets:
            concrete = bucket.get("key", "")
            # Match a concrete index back to the alias this service knows it by.
            name = next(
                (candidate for candidate in names if concrete.startswith(candidate)),
                None,
            )
            if name is None:
                continue

            total = bucket.get("doc_count", 0)
            embedded = bucket.get("embedded", {}).get("doc_count", 0)
            report[name].update(
                {
                    "exists": True,
                    "total": total,
                    "embedded": embedded,
                    "missing": max(total - embedded, 0),
                    "coverage": round(embedded / total, 4) if total else None,
                }
            )

        return list(report.values())

    def bulk_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        *,
        id_field: str = "urn",
        refresh: bool = True,
        chunk_size: int = 500,
    ) -> Dict[str, Any]:
        """
        Index many documents in one pass.

        Indexing document-by-document costs a round trip each, so a thousand-rule
        import spent its time in network latency rather than in Elasticsearch.

        Raises on any failed document: a partial import that reports success
        would leave a guide with silently missing rules.
        """
        if not documents:
            return {"indexed": 0}

        actions = [
            {
                "_index": index_name,
                "_id": document.get(id_field),
                "_source": document,
            }
            for document in documents
        ]

        indexed, errors = helpers.bulk(
            self.client,
            actions,
            chunk_size=chunk_size,
            refresh=refresh,
            raise_on_error=False,
        )

        if errors:
            raise InvalidError(
                f"{len(errors)} of {len(documents)} document(s) failed to index "
                f"into {index_name}: {errors[:3]}"
            )

        return {"indexed": indexed}

    def delete_by_query(self, index_name: str, query: Dict[str, Any]) -> None:
        self.client.delete_by_query(
            index=index_name,
            body={"query": query},
            refresh=True,
        )

    def search_documents(
        self,
        index_name: str,
        query: Dict[str, Any],
        *,
        size: int = 25,
        source_includes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch matching documents with an explicit field projection."""
        body: Dict[str, Any] = {"size": size, "query": query}
        source_config: Any = True
        if source_includes:
            source_config = {"includes": source_includes}

        response = self.client.search(
            index=index_name, body=body, source=source_config
        )
        return [hit.get("_source", {}) for hit in response["hits"]["hits"]]

    def count_by_query(self, index_name: str, query: Dict[str, Any]) -> int:
        """Exact number of documents a query matches."""
        response = self.client.count(index=index_name, body={"query": query})
        return int(response.get("count", 0))

    def update_by_query(
        self,
        index_name: str,
        query: Dict[str, Any],
        *,
        script_source: str,
        params: Optional[Dict[str, Any]] = None,
        max_docs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Apply a scripted field update to every document a query matches.

        One round trip instead of read-modify-write per document, which also
        means documents indexed before the field existed simply gain it.

        ``max_docs`` bounds the blast radius: callers should always set it so a
        mistyped query cannot rewrite the whole corpus.
        """
        body: Dict[str, Any] = {
            "query": query,
            "script": {
                "source": script_source,
                "lang": "painless",
                "params": params or {},
            },
        }
        if max_docs is not None:
            body["max_docs"] = int(max_docs)

        response = self.client.update_by_query(
            index=index_name,
            body=body,
            refresh=True,
            conflicts="proceed",
        )
        return {
            "total": response.get("total", 0),
            "updated": response.get("updated", 0),
            "version_conflicts": response.get("version_conflicts", 0),
            "failures": response.get("failures", []),
        }

    # --- Search with faceting ----------------------------------------------

    def parse_sort_string(self, sort_str: str):
        # Allow commas or spaces between fields
        tokens = sort_str.replace(",", " ").split()
        result = []

        i = 0
        while i < len(tokens):
            field = tokens[i]
            order = "asc"

            # If next token is asc/desc, use it
            if i + 1 < len(tokens) and tokens[i + 1].lower() in ("asc", "desc"):
                order = tokens[i + 1].lower()
                i += 2
            else:
                i += 1

            result.append((field, order))

        return result

    def _get_mapped_facet_fields(
        self, index_name: str, *, exclude_default_fields: bool
    ) -> Dict[str, str]:
        mapping = self.client.indices.get_mapping(index=index_name)
        props = mapping[index_name]["mappings"].get("properties", {})

        facet_fields: Dict[str, str] = {}

        def add_fields(properties: Dict[str, Any], *, prefix: str = "") -> None:
            for field, spec in properties.items():
                field_path = f"{prefix}{field}"

                if exclude_default_fields and (
                    field_path in DEFAULT_FACET_EXCLUDE_FIELDS
                    or field in DEFAULT_FACET_EXCLUDE_FIELDS
                ):
                    continue
                if exclude_default_fields and (
                    field_path in NON_FACET_SEMANTIC_FIELDS
                    or field in NON_FACET_SEMANTIC_FIELDS
                ):
                    continue

                field_type = spec.get("type")

                # Recurse into plain objects (but skip disabled objects and nested types)
                if (
                    "properties" in spec
                    and field_type not in {"nested"}
                    and spec.get("enabled", True) is not False
                ):
                    add_fields(spec["properties"], prefix=f"{field_path}.")
                    continue

                if field_type in {
                    "keyword",
                    "integer",
                    "long",
                    "float",
                    "boolean",
                    "date",
                }:
                    facet_fields[field_path] = field_type
                    continue

                if (
                    field_type == "text"
                    and "fields" in spec
                    and "keyword" in spec["fields"]
                    and field_path not in {"title"}
                ):
                    facet_fields[field_path] = "text"

        add_fields(props)

        return facet_fields

    def get_default_facet_fields(self, index_name: str) -> Dict[str, str]:
        return self._get_mapped_facet_fields(
            index_name, exclude_default_fields=True
        )

    @staticmethod
    def extract_query_string_fields(query: str) -> List[str]:
        return list(
            {
                match.group("field")
                for match in re.finditer(r"(?P<field>[A-Za-z_][\w.]*)\s*:", query)
            }
        )

    def resolve_facet_fields(
        self, index_name: str, fields: List[str] | None
    ) -> Dict[str, str]:
        if not fields:
            return {}

        mapped_fields = self._get_mapped_facet_fields(
            index_name, exclude_default_fields=False
        )
        resolved: Dict[str, str] = {}

        for field in fields:
            normalized_field = field.removesuffix(".keyword")
            field_type = mapped_fields.get(normalized_field)
            if field_type:
                resolved[normalized_field] = field_type

        return resolved

    def search_entities(self, index_name: str, qspec) -> Dict[str, Any]:
        q = qspec.model_dump()
        self._validate_result_window(
            limit=q["limit"],
            offset=q["offset"],
            operation="Search",
        )

        # ----------------------------
        # Query construction
        # ----------------------------
        must_clauses = []
        if q.get("q"):
            must_clauses.append(
                {
                    "multi_match": {
                        "query": q["q"],
                        "fields": ["*"],
                        # Require every term in the query to match. Without this,
                        # multi_match defaults to OR, so a query like
                        # "avocado health results" matches any doc containing any
                        # single (often common) term, ballooning the hit count.
                        "operator": "and",
                    }
                }
            )

        filters = []
        if q.get("fq"):
            for fq in q["fq"]:
                filters.append({"query_string": {"query": fq}})

        body: Dict[str, Any] = {
            "from": q["offset"],
            "size": q["limit"],
            # Count all matching docs exactly instead of capping at ES's default
            # of 10000. Otherwise hits.total.value saturates at 10000 (relation
            # "gte"), which makes the UI render unreachable pages past the result
            # window and report a misleading "10000" total.
            "track_total_hits": True,
            "query": {
                "bool": {
                    "must": must_clauses,
                    "filter": filters,
                }
            },
        }

        # ----------------------------
        # Facet field selection
        # ----------------------------
        facet_fields_list = q.get("fields") or []
        facet_fields = self.resolve_facet_fields(index_name, facet_fields_list)

        # 1) Explicit facet fields
        if facet_fields_list:
            pass

        # 2) Infer from fq filters
        elif q.get("fq"):
            extracted = []
            for fq in q["fq"]:
                extracted.extend(self.extract_query_string_fields(fq))
            facet_fields = self.resolve_facet_fields(index_name, extracted)

        # 3) Default mapping-driven facets
        if not facet_fields_list:
            if not q.get("fq"):
                facet_fields = self.get_default_facet_fields(index_name)

        # ----------------------------
        # Aggregations
        # ----------------------------
        if facet_fields:
            body["aggs"] = {}

            for field, field_type in facet_fields.items():
                # use correct field path
                if field_type == "text":
                    agg_field = f"{field}.keyword"
                else:
                    agg_field = field

                body["aggs"][f"{field}_facet"] = {
                    "terms": {
                        "field": agg_field,
                        "size": q["facet_limit"],
                        "order": {"_count": "desc"},
                        "min_doc_count": 1,
                    }
                }

        # ----------------------------
        # Source filtering & aliases
        # ----------------------------
        alias_map: Dict[str, str] = {}
        if q.get("fl"):
            source_fields = []
            for f in q["fl"]:
                if ":" in f:
                    original, alias = f.split(":", 1)
                    source_fields.append(original)
                    alias_map[original] = alias
                else:
                    source_fields.append(f)
            body["_source"] = source_fields

        # ----------------------------
        # Sorting
        # ----------------------------
        sort_spec = q.get("sort")
        if sort_spec:
            body["sort"] = []
            body["track_scores"] = True  # Track scores even when sorting
            for field, order in self.parse_sort_string(sort_spec):
                if field.lower() in ("relevance", "_score", "score"):
                    body["sort"].append({"_score": {"order": "desc"}})
                else:
                    body["sort"].append({field: {"order": order}})

        # ----------------------------
        # Highlighting
        # ----------------------------
        if q.get("highlight"):
            if q.get("highlight_fields"):
                hl_fields = q["highlight_fields"]
            elif q.get("fl"):
                hl_fields = [f.split(":", 1)[0] for f in q["fl"]]
            else:
                hl_fields = ["*"]

            body["highlight"] = {
                "pre_tags": [q["highlight_pre_tag"]],
                "post_tags": [q["highlight_post_tag"]],
                "fields": {field: {} for field in hl_fields},
            }

        # ----------------------------
        # Execute search (retry sort fix)
        # ----------------------------
        try:
            response = self.client.search(index=index_name, body=body)
        except BadRequestError as e:
            if "Fielddata is disabled" in str(e) and "sort" in body:
                fixed = []
                for s in body["sort"]:
                    (field, opts), = s.items()
                    if not field.startswith("_") and not field.endswith(".keyword"):
                        fixed.append({f"{field}.keyword": opts})
                    else:
                        fixed.append(s)
                body["sort"] = fixed
                response = self.client.search(index=index_name, body=body)
            else:
                raise

        # ----------------------------
        # Results
        # ----------------------------
        results: List[Dict[str, Any]] = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]

            if q.get("fl"):
                row = {
                    alias_map.get(k, k): v
                    for k, v in src.items()
                    if k in alias_map or k in body["_source"]
                }
            else:
                row = dict(src)

            row["_score"] = hit.get("_score")

            if q.get("highlight") and "highlight" in hit:
                row["_highlight"] = hit["highlight"]

            results.append(row)

        # ----------------------------
        # Facet results
        # ----------------------------
        facets: Dict[str, List[Dict[str, Any]]] = {}
        if "aggregations" in response:
            for agg_name, agg_data in response["aggregations"].items():
                field = agg_name.replace("_facet", "")
                facets[field] = [
                    {"value": b["key"], "count": b["doc_count"]}
                    for b in agg_data["buckets"]
                ]

        return {
            "results": results,
            "facets": facets,
            "total": response["hits"]["total"]["value"],
            # Largest offset+limit the backend will serve. The UI uses this to
            # clamp pagination so it never requests a window the API will reject.
            "max_result_window": MAX_RESULT_WINDOW,
        }

    from typing import Dict, Any


    def rebuild_index(
        self,
        *,
        alias_name: str,
        new_index_name: str,
        mapping: Dict[str, Any],
        settings: Dict[str, Any],
        delete_old: bool = False,
    ) -> None:
        """
        Rebuild an Elasticsearch index with a new mapping without data loss.

        Handles BOTH cases:
        - alias_name is already an alias
        - alias_name is a concrete index (one-time migration)
        """

        client = self.client
        old_index = None

        # Ensure rebuilt/migrated indices carry our raised result window so
        # deep browsing keeps working after a reindex.
        settings = dict(settings or {})
        settings["index"] = {
            **(settings.get("index") or {}),
            "max_result_window": MAX_RESULT_WINDOW,
        }

        # ─────────────────────────────────────────────
        # 1️⃣ Resolve old index (alias OR concrete index)
        # ─────────────────────────────────────────────

        if client.indices.exists_alias(name=alias_name):
            # Normal case: alias already exists
            alias_info = client.indices.get_alias(name=alias_name)
            old_index = list(alias_info.keys())[0]

        elif client.indices.exists(index=alias_name):
            # One-time migration: alias_name is a concrete index
            old_index = alias_name
            migrated_index = f"{alias_name}_v1"

            if not client.indices.exists(index=migrated_index):
                # Reindex alias_name → alias_name_v1
                client.indices.create(
                    index=migrated_index,
                    body={
                        "settings": settings,
                        "mappings": mapping,
                    },
                )

                client.reindex(
                    body={
                        "source": {"index": old_index},
                        "dest": {"index": migrated_index},
                    },
                    wait_for_completion=True,
                    refresh=True,
                    timeout="1h",
                )

            # Delete blocking concrete index name
            client.indices.delete(index=old_index)

            # Create alias
            client.indices.update_aliases(
                body={
                    "actions": [
                        {"add": {"index": migrated_index, "alias": alias_name}}
                    ]
                }
            )

            old_index = migrated_index

        else:
            # Fresh install: nothing exists yet
            old_index = None

        # ─────────────────────────────────────────────
        # 2️⃣ Create new index
        # ─────────────────────────────────────────────

        if client.indices.exists(index=new_index_name):
            raise RuntimeError(f"Index '{new_index_name}' already exists")

        client.indices.create(
            index=new_index_name,
            body={
                "settings": settings,
                "mappings": mapping,
            },
        )

        # ─────────────────────────────────────────────
        # 3️⃣ Reindex old → new
        # ─────────────────────────────────────────────

        if old_index:
            client.reindex(
                body={
                    "source": {"index": old_index},
                    "dest": {"index": new_index_name},
                },
                wait_for_completion=True,
                refresh=True,
                timeout="1h",
            )

        # ─────────────────────────────────────────────
        # 4️⃣ Atomically switch alias
        # ─────────────────────────────────────────────

        actions = []
        if old_index:
            actions.append({"remove": {"index": old_index, "alias": alias_name}})
        actions.append({"add": {"index": new_index_name, "alias": alias_name}})

        client.indices.update_aliases(body={"actions": actions})

        # ─────────────────────────────────────────────
        # 5️⃣ Optional cleanup
        # ─────────────────────────────────────────────

        if delete_old and old_index:
            client.indices.delete(index=old_index)


ELASTIC_CLIENT = ElasticsearchClientSingleton()
