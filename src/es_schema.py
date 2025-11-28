def recipe_collection_index(dim: int):
    return {
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "title": {"type": "text"},
                "description": {"type": "text"},
                "ingredients": {
                    "type": "nested",
                    "properties": {
                        "name": {"type": "text"},
                        "quantity": {"type": "text"},
                    },
                },
                "instructions": {"type": "text"},
                "tags": {"type": "keyword"},
            }
        }
    }

def organization_index(dim: int):
    return {
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "id": {"type": "keyword"},
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "description": {"type": "text"},
                "url": {"type": "keyword"},
                "contact_email": {"type": "keyword"},
                "image_url": {"type": "keyword"},
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "status": {"type": "keyword"},
                "updated_at": {
                    "type": "date", 
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "type": {"type": "keyword"},
            }
        }
    }

def artifact_index(dim: int):
    """
    Elasticsearch mapping for artifacts. 
    """
    return {
        "mappings": {
            "properties": {
                "id": {"type": "keyword"}, 
                "parent_urn": {"type": "keyword"}, 
                "type": {"type": "keyword"},
                # Core metadata
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "description": {
                    "type": "text"
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
            }
        }
    }


def guide_index(dim: int):
    """
    Elasticsearch index mapping for GuideSchema.
    Aligns with GuideCreationSchema and GuideSchema fields.
    """
    return {
        "mappings": {
            "properties": {
                # System-generated fields
                "urn": {"type": "keyword"},
                "id": {"type": "keyword"},
                "creator": {"type": "keyword"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "publication_date": {"type": "date"},
                "organization_urn": {"type": "keyword"},
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "description": {"type": "text"},
                "tags": {"type": "keyword"},
                "status": {"type": "keyword"},
                "url": {"type": "keyword"},
                "license": {"type": "keyword"},
                "region": {"type": "keyword"},
                "language": {"type": "keyword"},
                # Guide-specific fields
                "content": {"type": "text"},
                "topic": {"type": "keyword"},
                "audience": {"type": "keyword"},
                "type": {"type": "keyword"},
                # Nested artifacts
                "artifacts": {
                    "type": "nested",
                    "properties": {
                        "urn": {"type": "keyword"},
                        "id": {"type": "keyword"},
                        "title": {"type": "text"},
                        "description": {"type": "text"},
                        "file_url": {"type": "keyword"},
                        "file_type": {"type": "keyword"},
                        "file_size": {"type": "long"},
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"},
                        "type": {"type": "keyword"},
                    },
                },
            }
        }
    }

def article_index(dim: int):
    return {
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "id": {"type": "keyword"},
                "title": {"type": "text"},
                "description": {"type": "text"},
                "tags": {"type": "keyword"},
                "status": {"type": "keyword"},
                "creator": {"type": "keyword"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "url": {"type": "keyword"},
                "license": {"type": "keyword"},
                "region": {"type": "keyword"},
                "language": {"type": "keyword"},
                "external_id": {"type": "keyword"},
                "abstract": {"type": "text"},
                "category": {"type": "keyword"},
                "type": {"type": "keyword"},
                "authors": {"type": "keyword"},
                "publication_year": {"type": "date"},
                "organization_urn": {"type": "keyword"},
                "content": {"type": "text"},
                "venue": {"type": "keyword"},
                # Nested artifacts
                "artifacts": {
                    "type": "nested",
                    "properties": {
                        "urn": {"type": "keyword"},
                        "id": {"type": "keyword"},
                        "title": {"type": "text"},
                        "description": {"type": "text"},
                        "file_url": {"type": "keyword"},
                        "file_type": {"type": "keyword"},
                        "file_size": {"type": "long"},
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"},
                        "type": {"type": "keyword"},
                    },
                },
            }
        }
    }

def engagement_index(dim: int):
    return {
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
                "target_type": {"type": "keyword"},    

                "user_id": {"type": "keyword"},

                # Engagement payload
                "rating": {"type": "float"},            # numeric rating (optional)
                "reaction": {"type": "keyword"},        # like/love/etc (optional)
                "comment": {"type": "text"},            # free text (optional)

                # Classification & moderation
                "kind": {"type": "keyword"},            # rating | comment | reaction
                "status": {"type": "keyword"},          # pending | approved | rejected
            }
        }
    }




def foodtable_index(dim: int):
    return {
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "title": {"type": "text"},
                "category": {"type": "keyword"},
                "language": {"type": "keyword"},
                "region": {"type": "keyword"},
                "description": {"type": "text"},
                "nutritional_mappings": {
                    "type": "nested",
                    "properties": {
                        "name": {"type": "text"},
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
                    }
                },
                "tags": {"type": "keyword"},
            }
        }
    }


def organization_index(dim: int):
    return {
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "name": {"type": "text"},
                "description": {"type": "text"},
                "industry": {"type": "keyword"},
                "image_url": {"type": "keyword"},
                "location": {"type": "keyword"},
                "tags": {"type": "keyword"},
            }
        }
    }


def person_index(dim: int):
    return {
        "mappings": {
            "properties": {
                "urn": {"type": "keyword"},
                "name": {"type": "text"},
                "bio": {"type": "text"},
                "role": {"type": "keyword"},
                "organization": {"type": "keyword"},
                "image_url": {"type": "keyword"},
                "tags": {"type": "keyword"},
            }
        }
    }
