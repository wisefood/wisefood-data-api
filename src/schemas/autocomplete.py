from __future__ import annotations

from datetime import date
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class GuideAutocompleteSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)
    urn: str
    title: str
    short_title: Optional[str] = None
    region: Optional[str] = None
    publication_year: Optional[int] = None


class GuidelineAutocompleteSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)
    id: UUID
    guide_urn: str
    title: Optional[str] = None
    action_type: Optional[str] = None


class ArticleAutocompleteSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)
    urn: str
    title: str
    authors: List[str] = Field(default_factory=list)
    publication_year: Optional[date] = None
    venue: Optional[str] = None


class TextbookAutocompleteSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)
    urn: str
    title: str
    subtitle: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    publication_year: Optional[int] = None


class FoodCompositionTableAutocompleteSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)
    urn: str
    title: str
    compiling_institution: str
    region: Optional[str] = None


class OrganizationAutocompleteSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)
    urn: str
    title: str
    url: Optional[HttpUrl] = None


class RCollectionAutocompleteSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)
    urn: str
    title: str
    source_type: str
    recipe_count: Optional[int] = None
