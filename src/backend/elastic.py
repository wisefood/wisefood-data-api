import os
import threading
from datetime import datetime
from elasticsearch import Elasticsearch, NotFoundError, BadRequestError
from typing import Optional, List, Dict, Any
from es_schema import (
    recipe_collection_index,
    article_index,
    guide_index,
    organization_index,
    person_index,
    artifact_index,
    fctable_index,
    rag_chunk_index
)
from schemas import SearchSchema
import logging

logger = logging.getLogger(__name__)

ELASTIC_HOST = os.getenv("ELASTIC_HOST", "http://elasticsearch:9200")
ES_DIM = int(os.getenv("ES_DIM", 384))


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

        ensure_index("recipes", recipe_collection_index(ES_DIM))
        ensure_index("guides", guide_index(ES_DIM))
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

    def list_entities(
        self, index_name: str, size: int = 1000, offset: int = 0
    ) -> List[str]:
        body = {
            "from": offset,
            "size": size,
            "query": {"bool": {"must_not": {"term": {"status": "deleted"}}}},
        }
        r = self.client.search(index=index_name, body=body)
        return [h["_id"] for h in r["hits"]["hits"]]

    def fetch_entities(
        self, index_name: str, limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        body = {
            "from": offset,
            "size": limit,
            "query": {"bool": {"must_not": {"term": {"status": "deleted"}}}},
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
        # Avoid updating if only system fields are present
        if set(document.keys()) == {"updated_at", "urn"}:
            return

        existing = self.get_entity(index_name, document["urn"])
        if not existing:
            return

        merged = {**existing, **document}
        self.client.update(
            index=index_name,
            id=document["urn"],
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

        updated_at = updated_at or datetime.utcnow().isoformat()

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

    def search_entities(self, index_name: str, qspec: SearchSchema) -> Dict[str, Any]:
        q = qspec.model_dump()

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

        facet_fields = q.get("fields") or []

        if not facet_fields and q.get("fq"):
            # best-effort extraction of facet fields from "field:value" filters
            extracted_fields = set()
            for fq in q["fq"]:
                if ":" in fq:
                    field_name = fq.split(":", 1)[0].strip()
                    extracted_fields.add(field_name)
            facet_fields = list(extracted_fields)

        if facet_fields:
            body["aggs"] = {}
            for field in facet_fields:
                body["aggs"][f"{field}_facet"] = {
                    "terms": {
                        # Using .keyword by default is safer for text fields
                        "field": f"{field}.keyword",
                        "size": q["facet_limit"],
                    }
                }

        if q.get("fl"):
            source_fields = []
            alias_map: Dict[str, str] = {}
            for f in q["fl"]:
                if ":" in f:
                    original, alias = f.split(":", 1)
                    source_fields.append(original)
                    alias_map[original] = alias
                else:
                    source_fields.append(f)
            body["_source"] = source_fields
        else:
            alias_map = {}

        sort_spec = q.get("sort")

        if sort_spec:
            sort_items = self.parse_sort_string(sort_spec)
            body["sort"] = []

            for field, order in sort_items:
                # Relevance sorting
                if field.lower() in ("relevance", "score", "_score"):
                    body["sort"].append({"_score": {"order": "desc"}})
                else:
                    body["sort"].append({field: {"order": order}})

        if q.get("highlight"):
            # Decide which fields to highlight:
            # 1) explicit highlight_fields
            # 2) else fl (if present)
            # 3) else everything ("*")
            if q.get("highlight_fields"):
                hl_fields = q["highlight_fields"]
            elif q.get("fl"):
                # use the original field names, not aliases
                hl_fields = [f.split(":", 1)[0] for f in q["fl"]]
            else:
                hl_fields = ["*"]

            body["highlight"] = {
                "pre_tags": [q["highlight_pre_tag"]],
                "post_tags": [q["highlight_post_tag"]],
                "fields": {field: {} for field in hl_fields},
            }

        # --- Execute search, with retry on fielddata error ------------------
        try:
            r = self.client.search(index=index_name, body=body)
        except BadRequestError as e:
            if "Fielddata is disabled" in str(e):
                fixed = []
                for s in body["sort"]:
                    (field, opts), = s.items()
                    if not field.endswith(".keyword") and not field.startswith("_"):
                        fixed.append({f"{field}.keyword": opts})
                    else:
                        fixed.append(s)
                body["sort"] = fixed
                r = self.client.search(index=index_name, body=body)
            else:
                raise

        results: List[Dict[str, Any]] = []
        for hit in r["hits"]["hits"]:
            source = hit["_source"]

            if q.get("fl"):
                aliased = {}
                for original in body["_source"]:
                    if original in source:
                        aliased[alias_map.get(original, original)] = source[original]
            else:
                aliased = dict(source)

            aliased["_score"] = hit.get("_score")

            if q.get("highlight") and "highlight" in hit:
                aliased["_highlight"] = hit["highlight"]

            results.append(aliased)

        facets: Dict[str, List[Dict[str, Any]]] = {}
        if "aggregations" in r:
            for agg_name, agg_data in r["aggregations"].items():
                field_name = agg_name.replace("_facet", "")
                facets[field_name] = [
                    {"value": bucket["key"], "count": bucket["doc_count"]}
                    for bucket in agg_data["buckets"]
                ]

        return {
            "results": results,
            "facets": facets,
            "total": r["hits"]["total"]["value"],
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
