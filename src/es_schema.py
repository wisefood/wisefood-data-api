# es_schema.py

from typing import Any, Dict


# ---------------------------------------------------------------------------
# Common settings & helpers
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: Dict[str, Any] = {
    "analysis": {
        "analyzer": {
            # General-purpose analyzer for text fields
            "default_text": {
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding"],
            },
            # Autocomplete analyzer for titles / names, etc.
            "autocomplete": {
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    "asciifolding",
                    "edge_ngram_filter",
                ],
            },
        },
        "filter": {
            "edge_ngram_filter": {
                "type": "edge_ngram",
                "min_gram": 2,
                "max_gram": 20,
            }
        },
    }
}


def _embedding_field(dim: int) -> Dict[str, Any]:
    """Helper to define a dense_vector embedding field."""
    return {
        "type": "dense_vector",
        "dims": dim,
        "index": True,
        "similarity": "cosine",
    }


# ---------------------------------------------------------------------------
# Recipe collection
# ---------------------------------------------------------------------------

def recipe_collection_index(dim: int) -> Dict[str, Any]:
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "autocomplete",
                            "search_analyzer": "default_text",
                        },
                    },
                },
                "description": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "ingredients": {
                    "type": "nested",
                    "properties": {
                        "name": {
                            "type": "text",
                            "analyzer": "default_text",
                            "search_analyzer": "default_text",
                            "fields": {
                                "keyword": {"type": "keyword"},
                            },
                        },
                        "quantity": {"type": "text"},
                    },
                },
                "instructions": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "tags": {"type": "keyword"},
                # semantic vector on the constructed recipe text
                "embedding": _embedding_field(dim),
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "updated_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# Artifact index
# ---------------------------------------------------------------------------

def artifact_index(dim: int) -> Dict[str, Any]:
    """
    Elasticsearch mapping for artifacts.
    """
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "urn": {"type": "keyword"},
                "parent_urn": {"type": "keyword"},  # base entity URN
                "type": {"type": "keyword"},
                # Core metadata
                "title": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                    },
                },
                "description": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "creator": {"type": "keyword"},
                "language": {"type": "keyword"},
                # File info
                "file_url": {"type": "keyword"},
                "file_s3_url": {"type": "keyword"},
                "file_type": {"type": "keyword"},
                "file_size": {"type": "long"},
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "updated_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                # Optional extracted content for semantic search
                "content": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "embedding": _embedding_field(dim),
            }
        },
    }


# ---------------------------------------------------------------------------
# Guide index
# ---------------------------------------------------------------------------

def guide_index(dim: int) -> Dict[str, Any]:
    """
    Elasticsearch index mapping for GuideSchema.
    Aligns with GuideCreationSchema and GuideSchema fields.
    """
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                # System-generated fields
                "urn": {"type": "keyword"},
                "id": {"type": "keyword"},
                "creator": {"type": "keyword"},
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "updated_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "publication_date": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "organization_urn": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "autocomplete",
                            "search_analyzer": "default_text",
                        },
                    },
                },
                "description": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "tags": {"type": "keyword"},
                "status": {"type": "keyword"},
                "url": {"type": "keyword"},
                "license": {"type": "keyword"},
                "region": {"type": "keyword"},
                "language": {"type": "keyword"},
                # Guide-specific fields
                "content": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "topic": {"type": "keyword"},
                "audience": {"type": "keyword"},
                "type": {"type": "keyword"},
                # Nested artifacts (denormalized)
                "artifacts": {
                    "type": "nested",
                    "properties": {
                        "urn": {"type": "keyword"},
                        "id": {"type": "keyword"},
                        "title": {
                            "type": "text",
                            "analyzer": "default_text",
                            "search_analyzer": "default_text",
                        },
                        "description": {
                            "type": "text",
                            "analyzer": "default_text",
                            "search_analyzer": "default_text",
                        },
                        "file_url": {"type": "keyword"},
                        "file_type": {"type": "keyword"},
                        "file_size": {"type": "long"},
                        "created_at": {
                            "type": "date",
                            "format": "strict_date_optional_time||epoch_millis",
                        },
                        "updated_at": {
                            "type": "date",
                            "format": "strict_date_optional_time||epoch_millis",
                        },
                        "type": {"type": "keyword"},
                    },
                },
                # Semantic embedding over selected guide fields
                "embedding": _embedding_field(dim),
            }
        },
    }


# ---------------------------------------------------------------------------
# Article index
# ---------------------------------------------------------------------------

def article_index(dim: int) -> Dict[str, Any]:
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "id": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "autocomplete",
                            "search_analyzer": "default_text",
                        },
                    },
                },
                "description": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "tags": {"type": "keyword"},
                "status": {"type": "keyword"},
                "creator": {"type": "keyword"},
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "updated_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "url": {"type": "keyword"},
                "license": {"type": "keyword"},
                "region": {"type": "keyword"},
                "language": {"type": "keyword"},
                "external_id": {"type": "keyword"},
                "abstract": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "category": {"type": "keyword"},
                "type": {"type": "keyword"},
                "authors": {
                    "type": "keyword",
                },
                "publication_year": {
                    "type": "date",
                    "format": "yyyy||strict_date_optional_time||epoch_millis",
                },
                "organization_urn": {"type": "keyword"},
                "content": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "venue": {"type": "keyword"},
                # Nested artifacts (denormalized)
                "artifacts": {
                    "type": "nested",
                    "properties": {
                        "urn": {"type": "keyword"},
                        "id": {"type": "keyword"},
                        "title": {
                            "type": "text",
                            "analyzer": "default_text",
                            "search_analyzer": "default_text",
                        },
                        "description": {
                            "type": "text",
                            "analyzer": "default_text",
                            "search_analyzer": "default_text",
                        },
                        "file_url": {"type": "keyword"},
                        "file_type": {"type": "keyword"},
                        "file_size": {"type": "long"},
                        "created_at": {
                            "type": "date",
                            "format": "strict_date_optional_time||epoch_millis",
                        },
                        "updated_at": {
                            "type": "date",
                            "format": "strict_date_optional_time||epoch_millis",
                        },
                        "type": {"type": "keyword"},
                    },
                },
                # Semantic embedding over article text
                "embedding": _embedding_field(dim),
            }
        },
    }


# ---------------------------------------------------------------------------
# Engagement index (ratings / reactions / comments)
# ---------------------------------------------------------------------------

def engagement_index(dim: int) -> Dict[str, Any]:
    # dim unused here, but kept for a consistent function signature
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "updated_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "target_urn": {"type": "keyword"},
                "target_type": {"type": "keyword"},  # guide | article | recipe | foodtable | organization | person
                "user_id": {"type": "keyword"},
                # Engagement payload
                "rating": {"type": "float"},     # numeric rating (optional)
                "reaction": {"type": "keyword"},  # like/love/etc (optional)
                "comment": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                # Classification & moderation
                "kind": {"type": "keyword"},      # rating | comment | reaction
                "status": {"type": "keyword"},    # pending | approved | rejected
            }
        },
    }


# ---------------------------------------------------------------------------
# Food table index
# ---------------------------------------------------------------------------

def foodtable_index(dim: int) -> Dict[str, Any]:
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "autocomplete",
                            "search_analyzer": "default_text",
                        },
                    },
                },
                "category": {"type": "keyword"},
                "language": {"type": "keyword"},
                "region": {"type": "keyword"},
                "description": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "nutritional_mappings": {
                    "type": "nested",
                    "properties": {
                        "name": {
                            "type": "text",
                            "analyzer": "default_text",
                            "search_analyzer": "default_text",
                            "fields": {
                                "keyword": {"type": "keyword"},
                            },
                        },
                        "amount": {"type": "float"},
                        "serving_size": {"type": "keyword"},
                        "calories": {"type": "float"},
                        "protein": {"type": "float"},
                        "carbs": {"type": "float"},
                        "fat": {"type": "float"},
                        "fiber": {"type": "float"},
                        "sugar": {"type": "float"},
                        "sodium": {"type": "float"},
                        "vitamins": {"type": "object"},
                    },
                },
                "tags": {"type": "keyword"},
                "embedding": _embedding_field(dim),
            }
        },
    }


# ---------------------------------------------------------------------------
# Organization index (merged / canonical version)
# ---------------------------------------------------------------------------

def organization_index(dim: int) -> Dict[str, Any]:
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "id": {"type": "keyword"},
                "name": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "autocomplete",
                            "search_analyzer": "default_text",
                        },
                    },
                },
                "description": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "industry": {"type": "keyword"},
                "image_url": {"type": "keyword"},
                "location": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "url": {"type": "keyword"},
                "contact_email": {"type": "keyword"},
                "status": {"type": "keyword"},
                "type": {"type": "keyword"},
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "updated_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "embedding": _embedding_field(dim),
            }
        },
    }


# ---------------------------------------------------------------------------
# Person index
# ---------------------------------------------------------------------------

def person_index(dim: int) -> Dict[str, Any]:
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "name": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "autocomplete",
                            "search_analyzer": "default_text",
                        },
                    },
                },
                "bio": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "role": {"type": "keyword"},
                # URN or ID of organization
                "organization": {"type": "keyword"},
                "image_url": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "embedding": _embedding_field(dim),
            }
        },
    }


# ---------------------------------------------------------------------------
# RAG chunk index (for semantic retrieval & citations)
# ---------------------------------------------------------------------------

from typing import Any, Dict

# assuming you already have these in your module:
# DEFAULT_SETTINGS and _embedding_field(dim)

def rag_chunk_index(dim: int) -> Dict[str, Any]:
    """
    Index optimized for RAG chunks.
    One document = one text chunk, linked back to a base entity via base_urn.
    """
    return {
        "settings": DEFAULT_SETTINGS,
        "mappings": {
            "properties": {
                # Identity / linking
                "chunk_id": {"type": "keyword"},        # unique ID for this chunk
                "base_urn": {"type": "keyword"},        # URN of guide/article/recipe/etc.
                "base_type": {"type": "keyword"},       # guide | article | recipe | foodtable | person | organization
                "organization_urn": {"type": "keyword"},# optional: for org-based filters

                # For citations
                "title": {                               # base entity title (for display/citations)
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                    },
                },
                "url": {"type": "keyword"},

                # Structural anchors
                "section": {
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "paragraph_start": {"type": "integer"},
                "paragraph_end": {"type": "integer"},

                # Optional content-based anchor for robustness
                "anchor_start": {                       # first N tokens of the chunk
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },

                # Locale filters
                "language": {"type": "keyword"},
                "region": {"type": "keyword"},

                # Actual text used in RAG
                "text": {                               # full chunk text fed to the LLM
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },
                "snippet": {                            # shorter preview / UI snippet (optional)
                    "type": "text",
                    "analyzer": "default_text",
                    "search_analyzer": "default_text",
                },

                # Embedding for semantic search
                "embedding": _embedding_field(dim),

                # Timestamps (optional but handy)
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "updated_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
            }
        },
    }

