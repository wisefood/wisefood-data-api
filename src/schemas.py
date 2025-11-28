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