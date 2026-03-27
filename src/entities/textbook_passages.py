"""
Textbook Passage Entity
-----------------------
Dependent extracted passages belonging to a parent textbook and artifact.
Passages do not carry independent workflow state; they are visible whenever
their parent textbook is visible.
"""

from typing import Dict, Any, List, Optional, Tuple

import logging

from backend.elastic import ELASTIC_CLIENT
from backend.redis import REDIS
from catalog_access import can_view_unapproved_catalog, is_publicly_visible
from entity import DependentEntity
from entities.artifacts import ARTIFACT
from exceptions import DataError, InternalError, NotAllowedError, NotFoundError
from main import config
from schemas import (
    SearchSchema,
    TextbookPassageBulkReplaceSchema,
    TextbookPassageCreationSchema,
    TextbookPassageSchema,
    TextbookPassageUpdateSchema,
)

logger = logging.getLogger(__name__)


class TextbookPassage(DependentEntity):
    def __init__(self):
        super().__init__(
            "textbook_passage",
            "textbook_passages",
            TextbookPassageSchema,
            TextbookPassageCreationSchema,
            TextbookPassageUpdateSchema,
            parent_field="textbook_urn",
        )

    @staticmethod
    def _viewer_can_access_all(
        viewer: Dict[str, Any] | None, *, include_unapproved: bool = False
    ) -> bool:
        return include_unapproved or can_view_unapproved_catalog(viewer)

    def _get_textbook(self, textbook_urn: str) -> Dict[str, Any]:
        textbook = ELASTIC_CLIENT.get_entity(index_name="textbooks", urn=textbook_urn)
        if textbook is None:
            raise NotFoundError(f"Textbook with URN {textbook_urn} not found.")
        return textbook

    def _ensure_textbook_visible(
        self,
        textbook: Dict[str, Any],
        viewer: Dict[str, Any] | None,
        *,
        include_unapproved: bool = False,
    ) -> None:
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ) or is_publicly_visible(textbook):
            return
        raise NotFoundError(f"Textbook with URN {textbook['urn']} not found.")

    def get(
        self,
        id_: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        entity = self.get_cached(id_)
        textbook = self._get_textbook(entity["textbook_urn"])
        self._ensure_textbook_visible(
            textbook, viewer, include_unapproved=include_unapproved
        )
        return entity

    def get_cached(self, identifier: str) -> Dict[str, Any]:
        id_ = self.get_identifier(identifier)
        obj = None

        if config.settings.get("CACHE_ENABLED", False):
            try:
                obj = REDIS.get(id_)
            except Exception as e:
                logger.error(f"Failed to get cached textbook passage {id_}: {e}")

        if obj is None:
            obj = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=id_)
            if obj is None:
                raise NotFoundError(f"Textbook passage with ID {id_} not found.")
            self.cache(id_, obj)

        return self.dump_schema.model_validate(
            self._strip_search_metadata(obj)
        ).model_dump(mode="json")

    def list(self, limit: Optional[int] = None, offset: Optional[int] = None) -> List[str]:
        raise NotAllowedError(
            "Textbook passages do not support global listing. Use by-textbook endpoints."
        )

    def fetch(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotAllowedError(
            "Textbook passages do not support global fetch. Use by-textbook endpoints."
        )

    def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotAllowedError(
            "Textbook passages do not support global search. Use by-textbook endpoints."
        )

    def _validate_artifact_belongs_to_textbook(
        self, textbook_urn: str, artifact_id: str
    ) -> None:
        artifacts = ARTIFACT.fetch(parent_urn=textbook_urn, include_unapproved=True)
        if not artifacts:
            raise DataError(
                f"Textbook {textbook_urn} has no artifacts attached. "
                "Attach an artifact before creating or replacing passages."
            )
        artifact_ids = {str(artifact["id"]) for artifact in artifacts}
        if str(artifact_id) not in artifact_ids:
            raise DataError(
                f"Artifact {artifact_id} is not attached to textbook {textbook_urn}."
            )

    def _next_sequence_no(self, textbook_urn: str, artifact_id: str) -> int:
        qspec = SearchSchema.model_validate(
            {
                "limit": 1,
                "offset": 0,
                "fq": [
                    f'textbook_urn:"{textbook_urn}"',
                    f'artifact_id:"{artifact_id}"',
                ],
                "sort": "sequence_no desc",
            }
        )
        response = ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )
        if not response["results"]:
            return 1
        return int(response["results"][0].get("sequence_no", 0)) + 1

    @staticmethod
    def _match_structure_node(
        node: Dict[str, Any], page_no: int, artifact_id: str
    ) -> Optional[Tuple[str, List[str]]]:
        node_artifact_id = node.get("artifact_id")
        if node_artifact_id is not None and str(node_artifact_id) != str(artifact_id):
            return None

        page_start = node.get("page_start")
        page_end = node.get("page_end", page_start)
        if page_start is None or page_end is None:
            return None
        if not (int(page_start) <= page_no <= int(page_end)):
            return None

        for child in node.get("children", []):
            child_match = TextbookPassage._match_structure_node(child, page_no, artifact_id)
            if child_match is not None:
                return child_match[0], [str(node["title"]), *child_match[1]]

        return str(node["id"]), [str(node["title"])]

    def _structure_anchor_for_page(
        self, textbook: Dict[str, Any], *, page_no: int, artifact_id: str
    ) -> Tuple[str | None, List[str]]:
        structure_tree = textbook.get("structure_tree") or {}
        for root in structure_tree.get("roots", []):
            match = self._match_structure_node(root, page_no, artifact_id)
            if match is not None:
                return match
        return None, []

    @staticmethod
    def _ensure_page_within_count(textbook: Dict[str, Any], page_no: int) -> None:
        page_count = textbook.get("page_count")
        if page_count is not None and page_no > int(page_count):
            raise DataError(
                f"Passage page_no {page_no} exceeds textbook page_count {page_count}."
            )

    def _invalidate_textbook_cache(self, textbook_urn: str) -> None:
        if config.settings.get("CACHE_ENABLED", False):
            try:
                REDIS.delete(textbook_urn)
            except Exception as e:
                logger.error(
                    f"Failed to invalidate cache for textbook {textbook_urn}: {e}"
                )

    def create(self, spec, creator=None) -> str:
        try:
            passage_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating textbook passage: {e}")

        passage_dict = passage_data.model_dump(mode="json")
        textbook = self._get_textbook(passage_dict["textbook_urn"])
        self._validate_artifact_belongs_to_textbook(
            passage_dict["textbook_urn"], str(passage_dict["artifact_id"])
        )
        self._ensure_page_within_count(textbook, int(passage_dict["page_no"]))

        if passage_dict.get("sequence_no") is None:
            passage_dict["sequence_no"] = self._next_sequence_no(
                passage_dict["textbook_urn"], str(passage_dict["artifact_id"])
            )

        structure_node_id, structure_path = self._structure_anchor_for_page(
            textbook,
            page_no=int(passage_dict["page_no"]),
            artifact_id=str(passage_dict["artifact_id"]),
        )
        passage_dict["structure_node_id"] = structure_node_id
        passage_dict["structure_path"] = structure_path
        if creator:
            passage_dict["creator"] = creator.get("preferred_username")
        passage_dict = self.upsert_system_fields(passage_dict, update=False)

        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=passage_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create textbook passage: {e}")

        return passage_dict["id"]

    def create_entity(self, spec, creator) -> Dict[str, Any]:
        identifier = self.create(spec, creator)
        return self.get(identifier, viewer=creator, include_unapproved=True)

    def patch_entity_with_actor(self, id_: str, spec: Dict[str, Any], actor: dict):
        identifier = self.get_identifier(id_)
        self.patch(identifier, spec)
        self.invalidate_cache(identifier)
        return self.get(identifier, viewer=actor, include_unapproved=True)

    def patch(self, id_: str, spec) -> None:
        try:
            passage_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating textbook passage: {e}")

        current = self.get_cached(id_)
        update_dict = passage_data.model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        )

        if not update_dict:
            return

        textbook = self._get_textbook(current["textbook_urn"])
        artifact_id = str(current["artifact_id"])
        self._validate_artifact_belongs_to_textbook(current["textbook_urn"], artifact_id)

        merged = {**current, **update_dict}
        if int(merged["char_end"]) < int(merged["char_start"]):
            raise DataError("char_end must be greater than or equal to char_start")
        self._ensure_page_within_count(textbook, int(merged["page_no"]))

        structure_node_id, structure_path = self._structure_anchor_for_page(
            textbook,
            page_no=int(merged["page_no"]),
            artifact_id=artifact_id,
        )

        update_dict["structure_node_id"] = structure_node_id
        update_dict["structure_path"] = structure_path
        update_dict = self.upsert_system_fields(update_dict, update=True)
        update_dict["id"] = id_

        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=update_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update textbook passage: {e}")

        self.invalidate_cache(id_)

    def delete(self, id_: str) -> bool:
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=id_)
        except Exception as e:
            raise InternalError(f"Failed to delete textbook passage: {e}")

        self.invalidate_cache(id_)
        return {"deleted": id_}

    def fetch_for_textbook(
        self,
        textbook_urn: str,
        limit: int = 1000,
        offset: int = 0,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[Dict[str, Any]]:
        response = self.search_for_textbook(
            textbook_urn=textbook_urn,
            query={
                "limit": limit,
                "offset": offset,
                "sort": "page_no asc, sequence_no asc",
            },
            viewer=viewer,
            include_unapproved=include_unapproved,
        )
        return response["results"]

    def search_for_textbook(
        self,
        textbook_urn: str,
        query: Dict[str, Any],
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ):
        textbook = self._get_textbook(textbook_urn)
        self._ensure_textbook_visible(
            textbook, viewer, include_unapproved=include_unapproved
        )

        scoped_query = dict(query)
        fq = [f'textbook_urn:"{textbook_urn}"', *(scoped_query.get("fq") or [])]
        scoped_query["fq"] = fq
        scoped_query.setdefault("sort", "page_no asc, sequence_no asc")

        response = super().search(query=scoped_query)
        response["results"] = [
            self.dump_schema.model_validate(
                self._strip_search_metadata(passage)
            ).model_dump(mode="json")
            for passage in response.get("results", [])
        ]
        return response

    def _list_cached_ids_for_scope(
        self, textbook_urn: str, artifact_id: str | None = None
    ) -> List[str]:
        ids: List[str] = []
        limit = 1000
        offset = 0

        while True:
            fq = [f'textbook_urn:"{textbook_urn}"']
            if artifact_id is not None:
                fq.append(f'artifact_id:"{artifact_id}"')

            qspec = SearchSchema.model_validate(
                {
                    "limit": limit,
                    "offset": offset,
                    "fl": ["id"],
                    "fq": fq,
                }
            )
            response = ELASTIC_CLIENT.search_entities(
                index_name=self.collection_name, qspec=qspec
            )
            batch = response.get("results", [])
            if not batch:
                break

            ids.extend(str(item["id"]) for item in batch if item.get("id") is not None)
            if len(batch) < limit:
                break
            offset += len(batch)

        return ids

    def delete_for_textbook(
        self, textbook_urn: str, artifact_id: str | None = None
    ) -> Dict[str, Any]:
        cached_ids = self._list_cached_ids_for_scope(textbook_urn, artifact_id)
        for id_ in cached_ids:
            self.invalidate_cache(id_)

        filters: List[Dict[str, Any]] = [{"term": {"textbook_urn": textbook_urn}}]
        if artifact_id is not None:
            filters.append({"term": {"artifact_id": str(artifact_id)}})

        try:
            ELASTIC_CLIENT.delete_by_query(
                index_name=self.collection_name,
                query={"bool": {"filter": filters}},
            )
        except Exception as e:
            raise InternalError(f"Failed to delete textbook passages: {e}")

        return {
            "deleted_textbook_urn": textbook_urn,
            "artifact_id": artifact_id,
            "deleted_count": len(cached_ids),
        }

    def replace_for_textbook(
        self, textbook_urn: str, spec: Dict[str, Any], creator: dict | None = None
    ) -> Dict[str, Any]:
        try:
            replace_data = TextbookPassageBulkReplaceSchema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for replacing textbook passages: {e}")

        textbook = self._get_textbook(textbook_urn)
        artifact_id = str(replace_data.artifact_id)
        self._validate_artifact_belongs_to_textbook(textbook_urn, artifact_id)

        textbook_update: Dict[str, Any] = {}
        if replace_data.page_count is not None:
            textbook_update["page_count"] = replace_data.page_count
        if replace_data.structure_tree is not None:
            textbook_update["structure_tree"] = replace_data.structure_tree.model_dump(
                mode="json"
            )

        if textbook_update:
            update_doc = {"urn": textbook_urn, **textbook_update}
            update_doc = self.upsert_system_fields(update_doc, update=True)
            try:
                ELASTIC_CLIENT.update_entity(index_name="textbooks", document=update_doc)
            except Exception as e:
                raise InternalError(f"Failed to update textbook metadata: {e}")
            textbook = {**textbook, **textbook_update}
            self._invalidate_textbook_cache(textbook_urn)

        self.delete_for_textbook(textbook_urn, artifact_id=artifact_id)

        passages = replace_data.passages
        documents: List[Dict[str, Any]] = []

        for idx, passage in enumerate(passages, start=1):
            passage_dict = passage.model_dump(mode="json")
            self._ensure_page_within_count(textbook, int(passage_dict["page_no"]))

            structure_node_id, structure_path = self._structure_anchor_for_page(
                textbook,
                page_no=int(passage_dict["page_no"]),
                artifact_id=artifact_id,
            )

            document = {
                "textbook_urn": textbook_urn,
                "artifact_id": artifact_id,
                "page_no": int(passage_dict["page_no"]),
                "sequence_no": int(passage_dict.get("sequence_no") or idx),
                "text": passage_dict["text"],
                "char_start": int(passage_dict["char_start"]),
                "char_end": int(passage_dict["char_end"]),
                "structure_node_id": structure_node_id,
                "structure_path": structure_path,
                "extractor_name": replace_data.extractor_name,
                "extractor_run_id": replace_data.extractor_run_id,
            }
            if creator:
                document["creator"] = creator.get("preferred_username")

            document = self.upsert_system_fields(document, update=False)
            documents.append(document)

        if documents:
            try:
                for document in documents:
                    ELASTIC_CLIENT.client.index(
                        index=self.collection_name,
                        id=document["id"],
                        document=document,
                    )
                ELASTIC_CLIENT.client.indices.refresh(index=self.collection_name)
            except Exception as e:
                raise InternalError(f"Failed to index textbook passages: {e}")

        return {
            "textbook_urn": textbook_urn,
            "artifact_id": artifact_id,
            "replaced_count": len(documents),
            "page_count": textbook.get("page_count"),
            "structure_tree_updated": replace_data.structure_tree is not None,
        }


TEXTBOOK_PASSAGE = TextbookPassage()
