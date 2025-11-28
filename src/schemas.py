from __future__ import annotations

from datetime import datetime, date 
from enum import Enum
from typing import Annotated, List, Optional, Literal, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    EmailStr,
    field_validator,
    model_validator,
    StringConstraints,
    ConfigDict,
)

# ---- enums & constrained types ----

UrnStr = Annotated[
    str,
    StringConstraints(
        min_length=5, max_length=255, pattern=r"^urn:[a-z0-9][a-z0-9\-._:/]{2,}$"
    ),
]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
NonEmptyAbstract = Annotated[str, StringConstraints(min_length=1, max_length=15000)]
SlugStr = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$"
    ),
]
Iso639_1 = Annotated[
    str, StringConstraints(min_length=2, max_length=2, pattern=r"^[a-z]{2}$")
]
Iso3166_1a2 = Annotated[
    str, StringConstraints(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
]
SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
HexSha256 = Annotated[str, StringConstraints(pattern=r"^[A-Fa-f0-9]{64}$")]


class LoginSchema(BaseModel):
    username: str = Field(..., description="Username or email")
    password: str = Field(..., description="Password")


class SearchSchema(BaseModel):
    q: Optional[str] = Field(default=None, description="Search query string")
    limit: int = Field(
        default=10, ge=1, le=100, description="Maximum number of results to return"
    )
    offset: int = Field(
        default=0, ge=0, description="Number of results to skip for pagination"
    )
    fl: Optional[List[str]] = Field(
        default=None, description="List of fields to include in the response"
    )
    fq: Optional[List[str]] = Field(
        default=None, description="List of filter queries (e.g., 'status:active')"
    )
    sort: Optional[str] = Field(
        default=None, description="Sort order (e.g., 'created_at desc')"
    )
    fields: Optional[List[str]] = Field(
        default=None, description="List of fields to aggregate for faceting"
    )


class Status(str, Enum):
    active = "active"
    draft = "draft"
    archived = "archived"
    deleted = "deleted"
    deprecated = "deprecated"


class LicenseId(str, Enum):
    MIT = "MIT"
    Apache2 = "Apache-2.0"
    GPL3 = "GPL-3.0"
    CC_BY = "CC-BY-4.0"
    CC_BY_SA = "CC-BY-SA-4.0"
    Proprietary = "Proprietary"


class BaseSchema(BaseModel):
    """
    Common catalog metadata.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    urn: UrnStr = Field(
        ..., description="Stable URN identifier, e.g., 'urn:guides:nutrition-basics-gr'"
    )
    id: UUID = Field(..., description="Internal UUID")
    title: NonEmptyStr = Field(..., description="Human-readable title")
    description: Optional[NonEmptyStr] = Field(
        None, description="Summary/abstract of the resource (<= 2000 chars)"
    )
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=25)] = Field(
        default_factory=list, description="Topic tags"
    )
    status: Status = Field(default=Status.active, description="Lifecycle status")
    creator: Optional[str] = Field(
        None, description="Contact email for the creator/owner"
    )
    created_at: datetime = Field(..., description="Creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last-modified timestamp (UTC)")
    url: Optional[HttpUrl] = Field(
        None, description="Canonical public URL to the resource"
    )
    license: Optional[LicenseId] = Field(None, description="License identifier")
    language: Union[Iso639_1, None] = Field(
        default=None, description="Language code (ISO 639-1), e.g., 'en'"
    )

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v


class ArtifactSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )
    id: UUID = Field(..., description="Internal UUID")
    parent_urn: UrnStr = Field(
        ..., description="URN of the parent resource (e.g., guide)"
    )
    title: NonEmptyStr = Field(..., description="Human-readable title")
    description: NonEmptyStr = Field(
        ..., description="Summary/abstract of the resource (<= 2000 chars)"
    )
    type: Literal["artifact"] = Field(
        default="artifact", description="Resource type discriminator"
    )
    creator: Optional[str] = Field(
        None, description="Contact email for the creator/owner"
    )
    created_at: datetime = Field(..., description="Creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last-modified timestamp (UTC)")
    file_url: HttpUrl = Field(..., description="URL to download the artifact")
    file_s3_url: Optional[str] = Field(
        None, description="S3 URL for internal use (if applicable)"
    )
    file_type: str
    file_size: int
    language: Union[Iso639_1, None] = Field(
        default=None, description="Language code (ISO 639-1), e.g., 'en'"
    )

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["type"] = "artifact"
        return data


class ArtifactCreationSchema(BaseModel):
    """
    Schema for creating a new artifact. System generates: id, creator, created_at, updated_at.
    User provides URN of the parent resource (e.g., guide).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    parent_urn: UrnStr = Field(
        ..., description="URN of the parent resource (e.g., guide)"
    )
    title: NonEmptyStr = Field(..., description="Human-readable title")
    description: Optional[NonEmptyStr] = Field(
        None, description="Summary/abstract of the resource (<= 2000 chars)"
    )
    language: Union[Iso639_1, None] = Field(
        default=None, description="Language code (ISO 639-1), e.g., 'en'"
    )
    file_url: HttpUrl = Field(..., description="URL to download the artifact")
    file_type: str = Field(
        ..., description="MIME type of the artifact (e.g., 'application/pdf')"
    )
    file_size: int = Field(..., ge=0, description="Size of the artifact in bytes")


class ArtifactUpdateSchema(BaseModel):
    """
    Schema for updating an existing artifact. All fields optional.
    System fields (id, parent_urn, creator, created_at, updated_at) cannot be modified.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )
    file_type: str = Field(
        ..., description="MIME type of the artifact (e.g., 'application/pdf')"
    )
    title: NonEmptyStr | None = None
    description: NonEmptyStr | None = None


class GuideSchema(BaseSchema):
    type: Literal["guide"] = Field(
        default="guide", description="Resource type discriminator", exclude=True
    )
    region: Optional[Iso3166_1a2] = Field(
        None, description="Intended region (ISO 3166-1 alpha-2)"
    )
    organization_urn: Optional[UrnStr] = Field(
        None, description="URN of the publishing organization"
    )
    content: str
    topic: str | None = None
    audience: str | None = None
    artifacts: List[ArtifactSchema] = Field(default_factory=list)
    publication_year: Optional[int] = Field(
        None, description="Original publication year"
    )


class GuideCreationSchema(BaseModel):
    """
    Schema for creating a new guide. System generates: id, creator, created_at, updated_at.
    User provides URN as a slug (e.g., 'switzerland_calcium_intake_guide'),
    system prepends 'urn:guide:' internally.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    urn: SlugStr = Field(
        ..., description="URN slug (e.g., 'switzerland_calcium_intake_guide')"
    )
    title: NonEmptyStr = Field(..., description="Human-readable title")
    description: NonEmptyStr = Field(
        ..., description="Summary/abstract of the resource (<= 2000 chars)"
    )
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=25)] = Field(
        default_factory=list, description="Topic tags"
    )
    status: Status = Field(default=Status.active, description="Lifecycle status")
    url: HttpUrl = Field(..., description="Canonical public URL to the resource")
    license: LicenseId = Field(..., description="License identifier")
    region: Optional[Iso3166_1a2] = Field(
        None, description="Intended region (ISO 3166-1 alpha-2)"
    )
    organization_urn: Optional[UrnStr] = Field(
        None, description="URN of the publishing organization"
    )
    publication_date: Optional[datetime] = Field(
        None, description="Original publication date (UTC)"
    )
    content: str = Field(..., description="Guide content")
    topic: str | None = None
    audience: str | None = None
    language: Union[Iso639_1, None] = None
    artifacts: List[ArtifactSchema] = Field(
        default_factory=list, description="List of associated artifacts"
    )

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v


class GuideUpdateSchema(BaseModel):
    """
    Schema for updating an existing guide. All fields optional.
    System fields (id, urn, creator, created_at, updated_at) cannot be modified.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    title: NonEmptyStr | None = None
    description: NonEmptyStr | None = None
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=25)] | None = None
    status: Status | None = None
    url: HttpUrl | None = None
    license: LicenseId | None = None
    region: Optional[Iso3166_1a2] = None
    content: str | None = None
    topic: str | None = None
    audience: str | None = None
    language: Union[Iso639_1, None] = None
    artifacts: List[ArtifactSchema] | None = None
    organization_urn: Optional[UrnStr] = Field(
        None, description="URN of the publishing organization"
    )
    publication_date: Optional[datetime] = None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str] | None) -> List[str] | None:
        if v is not None and len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v


class ArticleSchema(BaseSchema):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    type: Literal["article"] = Field(
        default="article",
        description="Resource type discriminator",
        exclude=True,
    )
    organization_urn: Optional[UrnStr] = Field(
        None,
        description="URN of the publishing organization",
    )
    abstract: Optional[NonEmptyAbstract] = Field(
        None,
        description="Abstract of the article (<= 15000 chars)",
    )
    category: Optional[NonEmptyStr] = Field(
        None,
        description="Category of the article (e.g. nutrition, health)",
    )
    authors: Annotated[List[NonEmptyStr], Field(min_length=1, max_length=1000)] = Field(
        default_factory=list,
        description="List of authors",
    )
    publication_year: Optional[int] = Field(
        None,
        description="Publication year of the article (UTC)",
    )
    external_id: Optional[NonEmptyStr] = Field(
        None,
        description="External identifier (e.g., DOI, PubMed ID, Semantic Scholar ID)",
    )
    content: str = Field(
        ...,
        description="Full text content of the article",
    )
    venue: Optional[NonEmptyStr] = Field(
        None,
        description="Venue where the article was published",
    )
    artifacts: List[ArtifactSchema] = Field(
        default_factory=list,
        description="Associated artifacts (figures, tables, datasets, etc.)",
    )

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["type"] = "article"
        return data


class ArticleCreationSchema(BaseModel):
    """
    Schema for creating a new article. System generates: id, creator, created_at, updated_at.
    User provides URN as a slug (e.g., 'healthy_eating_article'),
    system prepends 'urn:article:' internally.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    urn: SlugStr = Field(
        ...,
        description="URN slug (e.g., 'healthy_eating_article')",
    )
    title: NonEmptyStr = Field(
        ...,
        description="Human-readable title",
    )
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=50)] = Field(
        default_factory=list,
        description="Topic tags",
    )
    url: Optional[HttpUrl] = Field(
        None,
        description="Canonical public URL to the resource",
    )
    external_id: Optional[NonEmptyStr] = Field(
        None,
        description="External identifier (e.g., DOI, PubMed ID, Semantic Scholar ID)",
    )
    license: Optional[LicenseId] = Field(
        None,
        description="License identifier",
    )
    organization_urn: Optional[UrnStr] = Field(
        None,
        description="URN of the publishing organization",
    )
    description: Optional[NonEmptyStr] = Field(
        None,
        description="Summary/abstract of the resource (<= 2000 chars)",
    )
    abstract: Optional[NonEmptyAbstract] = Field(
        None,
        description="Abstract of the article (<= 15000 chars)",
    )
    category: Optional[NonEmptyStr] = Field(
        None,
        description="Category of the article (e.g. nutrition, health)",
    )
    authors: Annotated[List[NonEmptyStr], Field(min_length=1, max_length=1000)] = Field(
        default_factory=list,
        description="List of authors",
    )
    publication_year: Optional[date] = Field(
        None,
        description="Publication year as integer or full date; integers normalized to YYYY-01-01"
    )
    content: str = Field(
        ...,
        description="Full text content of the article",
    )
    venue: NonEmptyStr = Field(
        ...,
        description="Venue where the article was published",
    )

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_publication_year(v)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v


class ArticleUpdateSchema(BaseModel):
    """
    Schema for updating an existing article. All fields optional.
    System fields (id, urn, creator, created_at, updated_at) cannot be modified.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    title: Optional[NonEmptyStr] = None
    description: Optional[NonEmptyStr] = None
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=50)] | None = None
    external_id: Optional[NonEmptyStr] = None
    url: Optional[HttpUrl] = None
    license: Optional[LicenseId] = None
    abstract: Optional[NonEmptyAbstract] = None
    category: Optional[NonEmptyStr] = None
    authors: (
        Annotated[List[NonEmptyStr], Field(min_length=1, max_length=1000)] | None
    ) = None
    publication_year: Optional[int] = Field(
        default=None,
        description="Publication year of the article (UTC)",
    )
    content: Optional[str] = None
    venue: Optional[NonEmptyStr] = None
    organization_urn: Optional[UrnStr] = Field(
        None,
        description="URN of the publishing organization",
    )

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str] | None) -> List[str] | None:
        if v is not None and len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_publication_year(v)
    

class FoodCompositionTableSchema(BaseSchema):
    """
    Schema representing a Food Composition Table resource (e.g. Swiss FCT v7.0),
    including metadata about the database itself, not individual food items.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    type: Literal["food_composition_table"] = Field(
        default="food_composition_table",
        description="Resource type discriminator",
        exclude=True,
    )

    # Core metadata
    compiling_institution: NonEmptyStr = Field(
        ...,
        description="Institution responsible for compiling the Food Composition Table "
                    "(e.g. 'Federal Food Safety and Veterinary Office, Switzerland')",
    )
    database_name: NonEmptyStr = Field(
        ...,
        description="Name and version of the food composition database "
                    "(e.g. 'Swiss Food Composition Database, Version 7.0')",
    )

    # Classification / standardization schemes
    classification_schemes: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Food classification schemes used (e.g. LanguaL, FoodEx2).",
    )
    standardization_schemes: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Nutrient standardization schemes (e.g. INFOODS Tags, EuroFIR).",
    )

    # Units, portions
    measurement_units: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Measurement units used in the database "
                    "(e.g. 'mg per 100g', 'µg per 100g', 'kcal per 100g', 'g per portion').",
    )
    reference_portions: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Reference portions or units used (e.g. '1 slice (40 g)', '1 cup (250 mL)', "
                    "'1 tablespoon (15 mL)', '100 g edible portion').",
    )

    # Completeness / coverage
    completeness_percent: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Estimated completeness of nutrient coverage as percentage (e.g. 92.0).",
    )
    completeness_description: Optional[NonEmptyStr] = Field(
        None,
        description="Free-text description of completeness (e.g. '92% nutrient coverage').",
    )
    nutrient_coverage: List[NonEmptyStr] = Field(
        default_factory=list,
        description="High-level nutrient coverage categories "
                    "(e.g. 'Energy', 'Macronutrients', 'Vitamins', 'Minerals', 'Fatty Acids').",
    )

    # Formats / tasks
    data_formats: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Available data formats (e.g. 'CSV', 'HTML', 'Web Tool').",
    )
    tasks_supported: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Supported use cases (e.g. 'Dietary Assessment', 'Research', 'Industry').",
    )

    # Scale of the database
    number_of_entries: Optional[int] = Field(
        None,
        ge=0,
        description="Approximate number of food items in the table (e.g. ~1,200).",
    )
    min_nutrients_per_item: Optional[int] = Field(
        None,
        ge=0,
        description="Approximate minimum number of nutrients per item (e.g. 250).",
    )
    max_nutrients_per_item: Optional[int] = Field(
        None,
        ge=0,
        description="Approximate maximum number of nutrients per item (e.g. 400).",
    )

    # Optional linking / generic metadata
    organization_urn: Optional[UrnStr] = Field(
        None,
        description="URN of the organization responsible for or owning the table.",
    )
    url: Optional[str] = Field(
        None,
        description="Public URL of the food composition database or its documentation.",
    )
    license: Optional[LicenseId] = Field(
        None,
        description="License identifier for the database.",
    )
    language: Optional[NonEmptyStr] = Field(
        None,
        description="Primary language of the database (e.g. 'de', 'fr', 'en').",
    )
    region: Optional[NonEmptyStr] = Field(
        None,
        description="Region/country to which the database applies (e.g. 'CH', 'Switzerland').",
    )
    description: Optional[NonEmptyStr] = Field(
        None,
        description="Short description or abstract of the food composition table.",
    )
    tags: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Free-form tags for categorization and search.",
    )

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["type"] = "food_composition_table"
        return data


class FoodCompositionTableCreationSchema(BaseModel):
    """
    Schema for creating a Food Composition Table resource.
    System generates: id, creator, created_at, updated_at.
    User provides URN as slug; system prepends 'urn:food_composition_table:' internally.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    urn: SlugStr = Field(
        ...,
        description="URN slug (e.g. 'swiss_fct_v7_0'); system prepends 'urn:food_composition_table:'.",
    )
    title: NonEmptyStr = Field(
        ...,
        description="Human-readable title of the food composition table.",
    )
    description: Optional[NonEmptyStr] = Field(
        None,
        description="Short description or abstract of the food composition table.",
    )
    tags: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Free-form tags for categorization and search.",
    )

    compiling_institution: NonEmptyStr = Field(
        ...,
        description="Institution responsible for compiling the table.",
    )
    database_name: NonEmptyStr = Field(
        ...,
        description="Database name and version.",
    )

    classification_schemes: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Food classification schemes used (e.g. LanguaL, FoodEx2).",
    )
    standardization_schemes: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Nutrient standardization schemes (e.g. INFOODS Tags, EuroFIR).",
    )

    measurement_units: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Measurement units used in the database.",
    )
    reference_portions: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Reference portions or units.",
    )

    completeness_percent: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Estimated completeness of nutrient coverage as percentage.",
    )
    completeness_description: Optional[NonEmptyStr] = Field(
        None,
        description="Free-text description of completeness.",
    )
    nutrient_coverage: List[NonEmptyStr] = Field(
        default_factory=list,
        description="High-level nutrient coverage categories.",
    )

    data_formats: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Available data formats (e.g. CSV, HTML, Web Tool).",
    )
    tasks_supported: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Supported tasks (e.g. Dietary Assessment, Research, Industry).",
    )

    number_of_entries: Optional[int] = Field(
        None,
        ge=0,
        description="Approximate number of food items.",
    )
    min_nutrients_per_item: Optional[int] = Field(
        None,
        ge=0,
        description="Approximate minimum number of nutrients per item.",
    )
    max_nutrients_per_item: Optional[int] = Field(
        None,
        ge=0,
        description="Approximate maximum number of nutrients per item.",
    )

    organization_urn: Optional[UrnStr] = Field(
        None,
        description="URN of the compiling/owning organization.",
    )
    url: Optional[str] = Field(
        None,
        description="Public URL of the database or its documentation.",
    )
    license: Optional[LicenseId] = Field(
        None,
        description="License identifier.",
    )
    language: Optional[NonEmptyStr] = Field(
        None,
        description="Primary language of the database.",
    )
    region: Optional[NonEmptyStr] = Field(
        None,
        description="Region/country of applicability.",
    )

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v


class FoodCompositionTableUpdateSchema(BaseModel):
    """
    Schema for updating an existing Food Composition Table.
    All fields optional. System fields (id, urn, creator, created_at, updated_at)
    cannot be modified.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    title: Optional[NonEmptyStr] = None
    description: Optional[NonEmptyStr] = None
    tags: Optional[List[NonEmptyStr]] = None

    compiling_institution: Optional[NonEmptyStr] = None
    database_name: Optional[NonEmptyStr] = None

    classification_schemes: Optional[List[NonEmptyStr]] = None
    standardization_schemes: Optional[List[NonEmptyStr]] = None

    measurement_units: Optional[List[NonEmptyStr]] = None
    reference_portions: Optional[List[NonEmptyStr]] = None

    completeness_percent: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Updated completeness percentage.",
    )
    completeness_description: Optional[NonEmptyStr] = None
    nutrient_coverage: Optional[List[NonEmptyStr]] = None

    data_formats: Optional[List[NonEmptyStr]] = None
    tasks_supported: Optional[List[NonEmptyStr]] = None

    number_of_entries: Optional[int] = Field(None, ge=0)
    min_nutrients_per_item: Optional[int] = Field(None, ge=0)
    max_nutrients_per_item: Optional[int] = Field(None, ge=0)

    organization_urn: Optional[UrnStr] = None
    url: Optional[str] = None
    license: Optional[LicenseId] = None
    language: Optional[NonEmptyStr] = None
    region: Optional[NonEmptyStr] = None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

class OrganizationSchema(BaseModel):
    urn: UrnStr = Field(
        ..., description="Stable URN identifier, e.g., 'urn:organizations:fao-org'"
    )
    id: NonEmptyStr = Field(..., description="Unique identifier for the organization")
    title: NonEmptyStr = Field(..., description="Human-readable organization name")
    description: NonEmptyStr = Field(
        ..., description="Summary/abstract of the organization (<= 2000 chars)"
    )
    url: HttpUrl = Field(..., description="Canonical public URL to the organization")
    contact_email: EmailStr = Field(..., description="Contact email address")
    image_url: Optional[HttpUrl] = Field(
        None, description="URL to the organization's logo/image"
    )
    created_at: datetime = Field(..., description="Creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last-modified timestamp (UTC)")
    type: Literal["organization"] = Field(
        default="organization", description="Resource type discriminator", exclude=True
    )


class OrganizationCreationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )
    urn: SlugStr = Field(
        ..., description="URN slug (e.g., 'switzerland_ministry_of_health')"
    )
    status: Status = Field(default=Status.active, description="Lifecycle status")
    title: NonEmptyStr = Field(..., description="Human-readable organization name")
    description: NonEmptyStr = Field(
        ..., description="Summary/abstract of the organization (<= 2000 chars)"
    )
    url: HttpUrl = Field(..., description="Canonical public URL to the organization")
    contact_email: EmailStr = Field(..., description="Contact email address")
    image_url: Optional[HttpUrl] = Field(
        None, description="URL to the organization's logo/image"
    )


class OrganizationUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    title: NonEmptyStr | None = None
    description: NonEmptyStr | None = None
    status: Status | None = None
    url: HttpUrl | None = None
    contact_email: EmailStr | None = None
    image_url: Optional[HttpUrl] = None



@field_validator("publication_year", mode="before")
@classmethod
def normalize_publication_year(cls, v):
    if v is None:
        return None

    # Case 1: integer year
    if isinstance(v, int):
        return date(v, 1, 1)

    # Case 2: string that is an integer year
    if isinstance(v, str) and v.isdigit():
        year = int(v)
        return date(year, 1, 1)

    # Case 3: full date string → parse
    if isinstance(v, str):
        try:
            # Try ISO parse
            parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return parsed.date()
        except Exception:
            raise ValueError("publication_year must be an integer year or ISO date string")

    # Case 4: already a date/datetime
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v

    raise ValueError("Invalid publication_year format")