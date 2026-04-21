import os
import re
import threading
from datetime import datetime
from elasticsearch import Elasticsearch, NotFoundError, BadRequestError
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
MAX_RESULT_WINDOW = min(int(os.getenv("ELASTIC_MAX_RESULT_WINDOW", "10000")), 10000)
SCROLL_KEEPALIVE = os.getenv("ELASTIC_SCROLL_KEEPALIVE", "1m")
SCROLL_BATCH_SIZE = int(os.getenv("ELASTIC_SCROLL_BATCH_SIZE", "1000"))

DEFAULT_FACET_EXCLUDE_FIELDS = {
    # long text / content
    "abstract",
    "content",
    "description",
    "instructions",
    "bio",
    "text",
    "snippet",
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
                indices.create(index=name, body=body)

        ensure_index("rcollections", rcollection_index(ES_DIM))
        ensure_index("guides", guide_index(ES_DIM))
        ensure_index("guidelines", guideline_index(ES_DIM))
        ensure_index("textbooks", textbook_index(ES_DIM))
        ensure_index("textbook_passages", textbook_passage_index(ES_DIM))
        ensure_index("artifacts", artifact_index(ES_DIM))
        ensure_index("articles", article_index(ES_DIM))
        ensure_index("organizations", organization_index(ES_DIM))
        ensure_index("persons", person_index(ES_DIM))
        ensure_index("fctables", fctable_index(ES_DIM))
        ensure_index("rag_chunks", rag_chunk_index(ES_DIM))

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

    def update_entity(self, index_name: str, document: Dict[str, Any]) -> None:
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
            refresh="wait_for",
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

    def delete_by_query(self, index_name: str, query: Dict[str, Any]) -> None:
        self.client.delete_by_query(
            index=index_name,
            body={"query": query},
            refresh=True,
        )

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
