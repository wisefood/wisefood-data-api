from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Annotated, List, Optional, Literal, Union, Dict, Any
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


class MTMSchema(BaseModel):
    client_id: str = Field(..., description="Client ID")
    client_secret: str = Field(..., description="Client Secret")

class AIEnhancedField(str, Enum):
    AI_TAGS = "ai_tags"
    AI_CATEGORY = "ai_category"
    AI_KEY_TAKEAWAYS = "ai_key_takeaways"

class SearchSchema(BaseModel):
    q: Optional[str] = Field(default=None, description="Search query string")
    limit: int = Field(
        default=10, ge=1, le=1000, description="Maximum number of results to return"
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
    facet_limit: int = Field(
        default=50, ge=1, le=1000, description="Max number of facet buckets per field"
    )

    highlight: bool = Field(
        default=False, description="Whether to return highlighted snippets"
    )
    highlight_fields: Optional[List[str]] = Field(
        default=None,
        description="Fields to highlight (defaults to fl or all if None)",
    )
    highlight_pre_tag: str = Field(
        default="<em>", description="HTML tag (or text) to prefix highlights"
    )
    highlight_post_tag: str = Field(
        default="</em>", description="HTML tag (or text) to suffix highlights"
    )


class Status(str, Enum):
    active = "active"
    draft = "draft"
    archived = "archived"
    deleted = "deleted"
    deprecated = "deprecated"


class ReviewStatus(str, Enum):
    unreviewed = "unreviewed"
    pending_review = "pending_review"
    in_review = "in_review"
    verified = "verified"
    changes_requested = "changes_requested"
    rejected = "rejected"


class Visibility(str, Enum):
    internal = "internal"
    public = "public"


class ApplicabilityStatus(str, Enum):
    current = "current"
    expired = "expired"
    superseded = "superseded"
    withdrawn = "withdrawn"
    unknown = "unknown"


class GuidelineActionType(str, Enum):
    eat = "eat"
    drink = "drink"
    use = "use"
    do = "do"
    avoid = "avoid"
    prepare = "prepare"
    limit = "limit"
    choose = "choose"
    increase = "increase"
    reduce = "reduce"


class GuidelineFrequency(str, Enum):
    per_meal = "per_meal"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    occasional = "occasional"


class GuidelineTargetPopulation(str, Enum):
    general_population = "general_population"
    infants = "infants"
    under_5_years = "under_5_years"
    ages_5_to_18 = "ages_5_to_18"
    adults = "adults"
    elderly = "elderly"
    pregnant_people = "pregnant_people"
    lactating_people = "lactating_people"
    other = "other"


class GuidelineFoodGroup(str, Enum):
    none = "none"
    fruits = "fruits"
    vegetables = "vegetables"
    grains = "grains"
    dairy = "dairy"
    protein_foods = "protein_foods"
    fats_and_oils = "fats_and_oils"
    beverages = "beverages"
    salt = "salt"
    sugars_and_sweets = "sugars_and_sweets"
    mixed = "mixed"
    other = "other"


class QuantityOperator(str, Enum):
    lt = "lt"
    lte = "lte"
    eq = "eq"
    gte = "gte"
    gt = "gt"
    approx = "approx"


def validate_editorial_state(
    data: Dict[str, Any], *, partial: bool = False
) -> Dict[str, Any]:
    visibility = getattr(data.get("visibility"), "value", data.get("visibility"))
    review_status = getattr(
        data.get("review_status"), "value", data.get("review_status")
    )
    status = getattr(data.get("status"), "value", data.get("status"))
    start = data.get("applicability_start_date")
    end = data.get("applicability_end_date")

    if start and end and end < start:
        raise ValueError(
            "applicability_end_date must be greater than or equal to applicability_start_date"
        )

    if visibility == Visibility.public.value:
        if not partial or "review_status" in data:
            if review_status != ReviewStatus.verified.value:
                raise ValueError("public resources must have review_status='verified'")

        if status in {Status.draft.value, Status.deleted.value}:
            raise ValueError("public resources cannot have status 'draft' or 'deleted'")

    return data


def validate_textbook_editorial_state(
    data: Dict[str, Any], *, partial: bool = False
) -> Dict[str, Any]:
    visibility = getattr(data.get("visibility"), "value", data.get("visibility"))
    review_status = getattr(
        data.get("review_status"), "value", data.get("review_status")
    )
    status = getattr(data.get("status"), "value", data.get("status"))
    start = data.get("applicability_start_date")
    end = data.get("applicability_end_date")

    if start and end and end < start:
        raise ValueError(
            "applicability_end_date must be greater than or equal to applicability_start_date"
        )

    if visibility == Visibility.public.value:
        if status in {Status.draft.value, Status.deleted.value}:
            raise ValueError("public resources cannot have status 'draft' or 'deleted'")

        allowed_review_statuses = {ReviewStatus.verified.value}
        if status == Status.active.value:
            allowed_review_statuses.add(ReviewStatus.unreviewed.value)

        if not partial or "review_status" in data or "status" in data:
            if review_status not in allowed_review_statuses:
                allowed_values = "', '".join(sorted(allowed_review_statuses))
                raise ValueError(
                    f"public textbooks with status='{status}' must have review_status in '{allowed_values}'"
                )

    return data


def validate_guide_publication(data: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    publication_date = data.get("publication_date")
    publication_year = data.get("publication_year")

    if isinstance(publication_date, str):
        try:
            publication_date = datetime.fromisoformat(
                publication_date.replace("Z", "+00:00")
            )
        except ValueError:
            publication_date = date.fromisoformat(publication_date)

    if isinstance(publication_year, str):
        publication_year = int(publication_year)

    if publication_date and publication_year and publication_date.year != publication_year:
        raise ValueError("publication_year must match publication_date.year")

    revision = data.get("revision")
    if revision:
        previous_guide_urn = (
            revision.get("previous_guide_urn")
            if isinstance(revision, dict)
            else getattr(revision, "previous_guide_urn", None)
        )
        current_urn = data.get("urn")
        if current_urn and previous_guide_urn and current_urn == previous_guide_urn:
            raise ValueError("revision.previous_guide_urn cannot reference the same guide")

    return data


def normalize_optional_year_int(v):
    if v is None:
        return None

    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        if v.isdigit():
            return int(v)

    return v


class LicenseId(str, Enum):
    MIT = "MIT"
    Apache2 = "Apache-2.0"
    GPL3 = "GPL-3.0"
    CC_BY = "CC-BY-4.0"
    CC_BY_SA = "CC-BY-SA-4.0"
    Proprietary = "Proprietary"
    CCBYNCSA = "CCBYNCSA"
    CCBYNC = "CCBYNC"
    CCBYNCND = "CCBYNCND"
    CCBYSA = "CCBYSA"
    CCBY = "CCBY"
    CC0 = "CC0"
    MIT_LOWERCASE = "mit"
    GPL = "gpl"
    PublisherSpecificOA = "publisher-specific-oa"
    PublicDomain = "public-domain"
    PD = "pd"
    UnspecifiedOA = "unspecified-oa"
    OtherOA = "other-oa"
    ImpliedOA = "implied-oa"
    PublisherSpecificManuscript = "publisher-specific, author manuscript"
    ElsevierSpecificLicense = "elsevier-specific: oa user license"


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
    version: Optional[SemVer] = Field(
        None, description="Resource version (Semantic Versioning)"
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
    file_type: str = Field(
        ..., description="File extension without the leading dot (e.g., 'pdf')"
    )
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
        ..., description="File extension without the leading dot (e.g., 'pdf')"
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
        ..., description="File extension without the leading dot (e.g., 'pdf')"
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
    short_title: Optional[NonEmptyStr] = Field(
        None, description="Short display title for the guide"
    )
    issuing_authority: Optional[NonEmptyStr] = Field(
        None, description="Authority that issued the guide"
    )
    responsible_ministry: Optional[NonEmptyStr] = Field(
        None, description="Responsible ministry or department"
    )
    document_type: Optional[NonEmptyStr] = Field(
        None, description="Type of guide document"
    )
    legal_status: Optional[NonEmptyStr] = Field(
        None, description="Legal or institutional status of the guide"
    )
    target_audiences: List[NonEmptyStr] = Field(
        default_factory=list, description="Structured target audiences for the guide"
    )
    graphical_model: Optional[NonEmptyStr] = Field(
        None, description="Graphical dietary model used by the guide"
    )
    evidence_basis: Optional[NonEmptyStr] = Field(
        None, description="Evidence basis used to develop the guide"
    )
    notes: Optional[NonEmptyAbstract] = Field(
        None, description="Additional notes about the guide"
    )
    review_status: ReviewStatus = Field(
        default=ReviewStatus.unreviewed,
        description="Editorial review state for this guide",
    )
    verifier_user_id: Optional[NonEmptyStr] = Field(
        None, description="User ID of the reviewer who verified the guide"
    )
    visibility: Visibility = Field(
        default=Visibility.internal,
        description="Whether the guide is internal-only or public",
    )
    applicability_status: ApplicabilityStatus = Field(
        default=ApplicabilityStatus.unknown,
        description="Real-world applicability state of the guide",
    )
    applicability_start_date: Optional[date] = Field(
        None, description="Date when the guide became applicable"
    )
    applicability_end_date: Optional[date] = Field(
        None, description="Date when the guide stopped being applicable"
    )
    publication_date: Optional[datetime] = Field(
        None, description="Original publication date (UTC)"
    )
    artifacts: List[ArtifactSchema] = Field(default_factory=list)
    guidelines: List[UUID] = Field(
        default_factory=list, description="List of linked guideline IDs"
    )
    publication_year: Optional[int] = Field(
        None, description="Original publication year"
    )
    revision: "GuideRevisionSchema | None" = Field(
        None, description="Reference to an older guide revised by this one"
    )
    identifiers: List["GuideIdentifierSchema"] = Field(
        default_factory=list, description="External identifiers linked to the guide"
    )

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_optional_year_int(v)

    @model_validator(mode="after")
    def validate_workflow_and_publication(self):
        validate_editorial_state(self.model_dump(mode="python", exclude_none=True))
        validate_guide_publication(self.model_dump(mode="python", exclude_none=True))
        return self


class GuideRevisionSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    previous_guide_urn: Optional[UrnStr] = Field(
        None, description="URN of the guide that this guide revises"
    )
    previous_guide_label: Optional[NonEmptyStr] = Field(
        None, description="Legacy label when no guide URN exists"
    )
    previous_publication_year: Optional[int] = Field(
        None, description="Publication year of the previous guide"
    )

    @field_validator("previous_publication_year", mode="before")
    @classmethod
    def normalize_previous_publication_year(cls, v):
        return normalize_optional_year_int(v)

    @model_validator(mode="after")
    def validate_reference(self):
        if not self.previous_guide_urn and not self.previous_guide_label:
            raise ValueError(
                "revision must include previous_guide_urn or previous_guide_label"
            )
        if self.previous_guide_urn and not self.previous_guide_urn.startswith("urn:guide:"):
            raise ValueError("revision.previous_guide_urn must reference a guide URN")
        return self


class GuideIdentifierSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    scheme: NonEmptyStr = Field(..., description="Identifier scheme, e.g. doi or isbn")
    value: NonEmptyStr = Field(..., description="Identifier value")
    url: Optional[HttpUrl] = Field(None, description="Resolvable URL for the identifier")

    @field_validator("scheme")
    @classmethod
    def normalize_scheme(cls, v: str) -> str:
        return v.lower()


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
    short_title: Optional[NonEmptyStr] = None
    issuing_authority: Optional[NonEmptyStr] = None
    responsible_ministry: Optional[NonEmptyStr] = None
    document_type: Optional[NonEmptyStr] = None
    legal_status: Optional[NonEmptyStr] = None
    target_audiences: List[NonEmptyStr] = Field(default_factory=list)
    graphical_model: Optional[NonEmptyStr] = None
    evidence_basis: Optional[NonEmptyStr] = None
    notes: Optional[NonEmptyAbstract] = None
    review_status: ReviewStatus = Field(default=ReviewStatus.unreviewed)
    visibility: Visibility = Field(default=Visibility.internal)
    applicability_status: ApplicabilityStatus = Field(
        default=ApplicabilityStatus.unknown
    )
    applicability_start_date: Optional[date] = None
    applicability_end_date: Optional[date] = None
    publication_year: Optional[int] = Field(
        None, description="Original publication year"
    )
    revision: GuideRevisionSchema | None = None
    identifiers: List[GuideIdentifierSchema] = Field(default_factory=list)
    artifacts: List[ArtifactSchema] = Field(
        default_factory=list, description="List of associated artifacts"
    )

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_optional_year_int(v)

    @model_validator(mode="after")
    def validate_workflow_and_publication(self):
        validate_editorial_state(self.model_dump(mode="python", exclude_none=True))
        validate_guide_publication(self.model_dump(mode="python", exclude_none=True))
        return self


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
    short_title: NonEmptyStr | None = None
    issuing_authority: NonEmptyStr | None = None
    responsible_ministry: NonEmptyStr | None = None
    document_type: NonEmptyStr | None = None
    legal_status: NonEmptyStr | None = None
    target_audiences: List[NonEmptyStr] | None = None
    graphical_model: NonEmptyStr | None = None
    evidence_basis: NonEmptyStr | None = None
    notes: NonEmptyAbstract | None = None
    review_status: ReviewStatus | None = None
    visibility: Visibility | None = None
    applicability_status: ApplicabilityStatus | None = None
    applicability_start_date: date | None = None
    applicability_end_date: date | None = None
    publication_year: int | None = None
    revision: GuideRevisionSchema | None = None
    identifiers: List[GuideIdentifierSchema] | None = None
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

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_optional_year_int(v)

    @model_validator(mode="after")
    def validate_workflow_and_publication(self):
        validate_editorial_state(
            self.model_dump(mode="python", exclude_none=True), partial=True
        )
        validate_guide_publication(
            self.model_dump(mode="python", exclude_none=True), partial=True
        )
        return self


class GuidelineQuantitySchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    operator: QuantityOperator = Field(..., description="Comparison operator")
    value: float = Field(..., description="Numeric quantity value")
    unit: NonEmptyStr = Field(..., description="Measurement unit, e.g. g or servings")
    period: Optional[NonEmptyStr] = Field(
        None, description="Time period such as day, week, or meal"
    )
    raw_text: Optional[NonEmptyStr] = Field(
        None, description="Original raw quantity string from the source"
    )


class GuidelineSourceReferenceSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    artifact_id: Optional[UUID] = Field(
        None, description="Guide artifact ID that contains the referenced rule"
    )
    page_start: int = Field(..., ge=1, description="First page containing the rule")
    page_end: Optional[int] = Field(
        None, ge=1, description="Last page containing the rule"
    )
    section_label: Optional[NonEmptyStr] = Field(
        None, description="Section label or heading in the source document"
    )

    @model_validator(mode="after")
    def validate_page_range(self):
        if self.page_end is None:
            self.page_end = self.page_start
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class GuidelineSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    id: UUID = Field(..., description="Internal UUID")
    guide_urn: UrnStr = Field(..., description="URN of the parent guide")
    guide_region: Optional[Iso3166_1a2] = Field(
        None, description="Guide region inherited from the parent guide"
    )
    title: Optional[NonEmptyStr] = Field(
        None, description="Short title or heading for the guideline"
    )
    rule_text: NonEmptyAbstract = Field(
        ..., description="Full text of the dietary guideline"
    )
    sequence_no: int = Field(..., ge=1, description="Order of the guideline in the guide")
    page_no: int | None = Field(
        None,
        ge=1,
        description="Page number in the parent guide PDF where the guideline originates",
    )
    action_type: GuidelineActionType = Field(
        ..., description="Normalized action category for the guideline"
    )
    target_populations: List[GuidelineTargetPopulation] = Field(
        default_factory=list, description="Populations targeted by the guideline"
    )
    frequency: GuidelineFrequency | None = Field(
        None, description="Suggested repetition frequency"
    )
    quantity: GuidelineQuantitySchema | None = Field(
        None, description="Normalized quantitative recommendation, if present"
    )
    food_groups: List[GuidelineFoodGroup] = Field(
        default_factory=list, description="Food groups referenced by the guideline"
    )
    source_refs: List[GuidelineSourceReferenceSchema] = Field(
        default_factory=list,
        description="Page-level references into the parent guide's artifacts",
    )
    notes: Optional[NonEmptyAbstract] = Field(
        None, description="Additional notes about the guideline"
    )
    status: Status = Field(default=Status.active, description="Lifecycle status")
    review_status: ReviewStatus = Field(
        default=ReviewStatus.unreviewed,
        description="Editorial review state for this guideline",
    )
    verifier_user_id: Optional[NonEmptyStr] = Field(
        None, description="User ID of the reviewer who verified the guideline"
    )
    visibility: Visibility = Field(
        default=Visibility.internal,
        description="Whether the guideline is internal-only or public",
    )
    applicability_status: ApplicabilityStatus = Field(
        default=ApplicabilityStatus.unknown,
        description="Real-world applicability state of the guideline",
    )
    applicability_start_date: Optional[date] = Field(
        None, description="Date when the guideline became applicable"
    )
    applicability_end_date: Optional[date] = Field(
        None, description="Date when the guideline stopped being applicable"
    )
    creator: Optional[str] = Field(
        None, description="Contact email for the creator/owner"
    )
    created_at: datetime = Field(..., description="Creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last-modified timestamp (UTC)")

    @model_validator(mode="after")
    def validate_workflow(self):
        validate_editorial_state(self.model_dump(mode="python", exclude_none=True))
        return self


class GuidelineCreationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    guide_urn: UrnStr = Field(..., description="URN of the parent guide")
    title: Optional[NonEmptyStr] = None
    rule_text: NonEmptyAbstract = Field(
        ..., description="Full text of the dietary guideline"
    )
    sequence_no: Optional[int] = Field(
        None, ge=1, description="Order of the guideline in the guide"
    )
    page_no: int | None = Field(
        None,
        ge=1,
        description="Page number in the parent guide PDF where the guideline originates",
    )
    action_type: GuidelineActionType | None = Field(
        None, description="Normalized action category for the guideline"
    )
    target_populations: List[GuidelineTargetPopulation] = Field(default_factory=list)
    frequency: GuidelineFrequency | None = None
    quantity: GuidelineQuantitySchema | None = None
    food_groups: List[GuidelineFoodGroup] = Field(default_factory=list)
    source_refs: List[GuidelineSourceReferenceSchema] = Field(default_factory=list)
    notes: Optional[NonEmptyAbstract] = None
    status: Status = Field(default=Status.draft, description="Lifecycle status")
    review_status: ReviewStatus = Field(default=ReviewStatus.unreviewed)
    visibility: Visibility = Field(default=Visibility.internal)
    applicability_status: ApplicabilityStatus = Field(
        default=ApplicabilityStatus.unknown
    )
    applicability_start_date: Optional[date] = None
    applicability_end_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_workflow(self):
        validate_editorial_state(self.model_dump(mode="python", exclude_none=True))
        return self


class GuidelineUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    title: Optional[NonEmptyStr] = None
    rule_text: Optional[NonEmptyAbstract] = None
    sequence_no: Optional[int] = Field(None, ge=1)
    page_no: int | None = Field(None, ge=1)
    action_type: GuidelineActionType | None = None
    target_populations: List[GuidelineTargetPopulation] | None = None
    frequency: GuidelineFrequency | None = None
    quantity: GuidelineQuantitySchema | None = None
    food_groups: List[GuidelineFoodGroup] | None = None
    source_refs: List[GuidelineSourceReferenceSchema] | None = None
    notes: Optional[NonEmptyAbstract] = None
    status: Status | None = None
    review_status: ReviewStatus | None = None
    visibility: Visibility | None = None
    applicability_status: ApplicabilityStatus | None = None
    applicability_start_date: date | None = None
    applicability_end_date: date | None = None

    @model_validator(mode="after")
    def validate_workflow(self):
        validate_editorial_state(
            self.model_dump(mode="python", exclude_none=True), partial=True
        )
        return self


GuideSchema.model_rebuild()


class GeographicContextSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    country_or_region: Optional[NonEmptyStr] = None
    income_setting: Optional[NonEmptyStr] = None


class ArticleSchema(BaseSchema):
    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    # ----------------------------
    # System / embedding
    # ----------------------------
    embedded_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the article was embedded",
    )

    # ----------------------------
    # Bibliographic & content
    # ----------------------------
    organization_urn: Optional[UrnStr] = Field(
        None,
        description="URN of the publishing organization",
    )

    abstract: Optional[NonEmptyAbstract] = Field(
        None,
        description="Abstract of the article (<= 15000 chars)",
    )

    description: Optional[NonEmptyStr] = Field(
        None,
        description="Human-readable summary of the article",
    )

    content: str = Field(
        ...,
        description="Full text content of the article",
    )

    authors: Annotated[List[NonEmptyStr], Field(min_length=1, max_length=1000)] = Field(
        default_factory=list,
        description="List of authors",
    )

    venue: Optional[NonEmptyStr] = Field(
        None,
        description="Venue where the article was published",
    )

    publication_year: Optional[date] = Field(
        None,
        description="Publication year (normalized to YYYY-01-01 if year-only)",
    )

    external_id: Optional[NonEmptyStr] = Field(
        None,
        description="External identifier (e.g., PubMed ID, Semantic Scholar ID)",
    )

    doi: Optional[NonEmptyStr] = Field(
        None,
        description="Digital Object Identifier (DOI)",
    )

    open_access: Optional[bool] = Field(
        None, description="Whether the article is open access (if known)"
    )

    citation_count: Optional[int] = Field(
        None,
        description="Number of citations to the article",
    )

    reference_count: Optional[int] = Field(
        None,
        description="Number of references in the article",
    )

    influential_citation_count: Optional[int] = Field(
        None,
        description="Number of influential citations to the article",
    )

    type: Optional[str] = Field(
        None, description="Type of the article (e.g., 'JournalArticle', 'Review')"
    )

    # ----------------------------
    # Study metadata (structured, filterable)
    # ----------------------------
    keywords: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=250)] = (
        Field(default_factory=list, description="Keywords for the article/study")
    )

    reader_group: Optional[NonEmptyStr] = Field(
        None, description="Intended reader group (e.g., General Public)"
    )
    age_group: Optional[NonEmptyStr] = Field(None, description="Age group studied")
    population_group: Optional[NonEmptyStr] = Field(
        None, description="Population group studied"
    )
    geographic_context: Optional[GeographicContextSchema] = Field(
        None, description="Geographic and income context"
    )
    biological_model: Optional[NonEmptyStr] = Field(
        None, description="Biological model (e.g., Human)"
    )
    topics: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=100)] = Field(
        default_factory=list, description="High-level topics"
    )
    study_type: Optional[NonEmptyStr] = Field(None, description="Study design/type")
    hard_exclusion_flags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=50)] = (
        Field(default_factory=list, description="Hard exclusion flags")
    )
    annotation_confidence: Optional[float] = Field(
        None, ge=0, le=1, description="Confidence score for annotations (0..1)"
    )

    extras: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Arbitrary metadata (e.g., evaluation, annotations)",
    )

    # ----------------------------
    # Human-authoritative classification
    # ----------------------------
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=50)] = Field(
        default_factory=list,
        description="Authoritative topic tags",
    )

    category: Optional[NonEmptyStr] = Field(
        None,
        description="Authoritative article category",
    )

    region: Optional[NonEmptyStr] = Field(
        None,
        description="Authoritative geographic region",
    )

    language: Optional[NonEmptyStr] = Field(
        None,
        description="Detected language of the article (ISO code)",
    )

    # ----------------------------
    # AI-derived classification (read-only)
    # ----------------------------
    ai_tags: List[NonEmptyStr] = Field(
        default_factory=list,
        description="AI-derived topic tags (not human-reviewed)",
    )

    ai_category: Optional[NonEmptyStr] = Field(
        None,
        description="AI-derived article category",
    )

    key_takeaways: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=10)] = (
        Field(
        default_factory=list,
            description="Optional key takeaways written by the author/editor",
        )
    )

    ai_key_takeaways: List[NonEmptyStr] = Field(
        default_factory=list,
        description="AI-generated key takeaways (not human-reviewed)",
    )

    @field_validator("publication_year", mode="before")
    @classmethod
    def validate_publication_year(cls, v):
        return normalize_publication_year(v)


class ArticleCreationSchema(BaseModel):
    """
    Schema for creating a new article.
    System generates: id, creator, created_at, updated_at.
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

    content: str = Field(
        ...,
        description="Full text content of the article",
    )

    description: Optional[NonEmptyStr] = Field(
        None,
        description="Human-written summary",
    )

    abstract: Optional[NonEmptyAbstract] = Field(
        None,
        description="Abstract of the article",
    )

    # Structured metadata (often AI-assisted, but stored explicitly)
    keywords: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=250)] = Field(
        default_factory=list, description="Keywords for the article/study"
    )
    reader_group: Optional[NonEmptyStr] = None
    age_group: Optional[NonEmptyStr] = None
    population_group: Optional[NonEmptyStr] = None
    geographic_context: Optional[GeographicContextSchema] = None
    biological_model: Optional[NonEmptyStr] = None
    topics: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=100)] = Field(
        default_factory=list, description="High-level topics"
    )
    study_type: Optional[NonEmptyStr] = None
    hard_exclusion_flags: Annotated[
        List[NonEmptyStr], Field(min_length=0, max_length=50)
    ] = Field(default_factory=list)
    annotation_confidence: Optional[float] = Field(None, ge=0, le=1)

    extras: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Arbitrary metadata (e.g., evaluation, annotations)",
    )

    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=50)] = Field(
        default_factory=list,
        description="Authoritative topic tags",
    )

    category: Optional[NonEmptyStr] = Field(
        None,
        description="Authoritative article category",
    )

    authors: Annotated[List[NonEmptyStr], Field(min_length=1, max_length=1000)] = Field(
        default_factory=list,
        description="List of authors",
    )

    venue: NonEmptyStr = Field(
        ...,
        description="Venue where the article was published",
    )

    publication_year: Optional[date] = Field(
        None,
        description="Publication year",
    )

    url: Optional[HttpUrl] = Field(
        None,
        description="Canonical public URL",
    )

    external_id: Optional[NonEmptyStr] = Field(
        None,
        description="External identifier",
    )

    doi: Optional[NonEmptyStr] = Field(
        None,
        description="Digital Object Identifier (DOI)",
    )

    license: LicenseId | None = None
    open_access: Optional[bool] = Field(
        None, description="Whether the article is open access (if known)"
    )

    citation_count: Optional[int] = Field(
        None,
        description="Number of citations to the article",
    )

    reference_count: Optional[int] = Field(
        None,
        description="Number of references in the article",
    )

    influential_citation_count: Optional[int] = Field(
        None,
        description="Number of influential citations to the article",
    )

    type: Optional[str] = Field(
        None, description="Type of the article (e.g., 'JournalArticle', 'Review')"
    )

    organization_urn: Optional[UrnStr] = Field(
        None,
        description="Publishing organization URN",
    )

    key_takeaways: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=10)] = (
        Field(
            default_factory=list,
            description="Optional key takeaways written by the author/editor",
        )
    )

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    @field_validator("publication_year", mode="before")
    @classmethod
    def validate_publication_year(cls, v):
        return normalize_publication_year(v)


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
    keywords: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=250)] | None = (
        None
    )
    reader_group: Optional[NonEmptyStr] = None
    age_group: Optional[NonEmptyStr] = None
    population_group: Optional[NonEmptyStr] = None
    geographic_context: Optional[GeographicContextSchema] = None
    biological_model: Optional[NonEmptyStr] = None
    topics: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=100)] | None = (
        None
    )
    study_type: Optional[NonEmptyStr] = None
    hard_exclusion_flags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=50)] | None = (
        None
    )
    annotation_confidence: Optional[float] = Field(None, ge=0, le=1)
    extras: Optional[Dict[str, Any]] = None
    external_id: Optional[NonEmptyStr] = Field(
        None,
        description="External identifier (e.g., PubMed ID, Semantic Scholar ID)",
    )
    doi: Optional[NonEmptyStr] = Field(
        None,
        description="Digital Object Identifier (DOI)",
    )
    url: Optional[HttpUrl] = None
    license: Optional[LicenseId] = None
    open_access: Optional[bool] = Field(
        None, description="Whether the article is open access (if known)"
    )
    abstract: Optional[NonEmptyAbstract] = None
    category: Optional[NonEmptyStr] = None
    authors: (
        Annotated[List[NonEmptyStr], Field(min_length=1, max_length=1000)] | None
    ) = None
    publication_year: Optional[date] = Field(None, description="Publication year")
    content: Optional[str] = None
    venue: Optional[NonEmptyStr] = Field(
        None,
        description="Venue where the article was published",
    )
    organization_urn: Optional[UrnStr] = Field(
        None,
        description="URN of the publishing organization",
    )

    citation_count: Optional[int] = Field(
        None,
        description="Number of citations to the article",
    )

    reference_count: Optional[int] = Field(
        None,
        description="Number of references in the article",
    )

    influential_citation_count: Optional[int] = Field(
        None,
        description="Number of influential citations to the article",
    )

    type: Optional[str] = Field(
        None, description="Type of the article (e.g., 'JournalArticle', 'Review')"
    )

    key_takeaways: (
        Annotated[List[NonEmptyStr], Field(min_length=0, max_length=10)] | None
    ) = None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str] | None) -> List[str] | None:
        if v is not None and len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    @field_validator("publication_year", mode="before")
    @classmethod
    def validate_publication_year(cls, v):
        # here, normalize_publication_year refers to the module-level function
        return normalize_publication_year(v)


class ArticleEnhancementSchema(BaseModel):
    agent: SlugStr = Field(
        ..., description="Agent identifier (lowercase with dashes or underscores)"
    )

    fields: Dict[AIEnhancedField, Any] = Field(
        ...,
        description="AI-derived fields keyed by allowed enhancement field names",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_backcompat_payload(cls, v: Any) -> Any:
        """
        Backwards-compatible request-body handling.

        New shape:
          {"agent": "...", "fields": {"ai_tags": [...], "ai_category": "..."}}

        Legacy Wisefood client shape (wisefood-client sends flat kwargs):
          {"agent": "...", "ai_tags": [...], "ai_category": "..."}
        """
        if not isinstance(v, dict):
            return v

        # If caller already sent nested fields, keep them but also fold in any
        # top-level enhancement keys that were mistakenly sent.
        if isinstance(v.get("fields"), dict):
            merged_fields: Dict[str, Any] = dict(v["fields"])
            for k, val in v.items():
                if k in ("agent", "fields"):
                    continue
                merged_fields.setdefault(k, val)
            return {"agent": v.get("agent"), "fields": merged_fields}

        # Otherwise treat everything except `agent` as enhancement fields.
        agent = v.get("agent")
        flat_fields = {k: val for k, val in v.items() if k != "agent"}
        return {"agent": agent, "fields": flat_fields}

    @field_validator("fields")
    @classmethod
    def validate_fields_not_empty(cls, v):
        if not v:
            raise ValueError("fields must contain at least one AI enhancement")
        return v


class TextbookStructureNodeKind(str, Enum):
    part = "part"
    chapter = "chapter"
    section = "section"
    subsection = "subsection"
    appendix = "appendix"
    other = "other"


class TextbookStructureNodeSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    id: NonEmptyStr = Field(..., description="Stable identifier for this structure node")
    title: NonEmptyStr = Field(..., description="Display title for the structure node")
    kind: TextbookStructureNodeKind = Field(
        default=TextbookStructureNodeKind.other,
        description="Hierarchy node type",
    )
    page_start: int = Field(..., ge=1, description="First page covered by this node")
    page_end: Optional[int] = Field(
        None, ge=1, description="Last page covered by this node"
    )
    artifact_id: Optional[UUID] = Field(
        None, description="Textbook artifact ID this node belongs to, if scoped"
    )
    children: List["TextbookStructureNodeSchema"] = Field(
        default_factory=list, description="Nested structure nodes"
    )

    @model_validator(mode="after")
    def validate_page_range(self):
        if self.page_end is None:
            self.page_end = self.page_start
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class TextbookStructureTreeSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    roots: List[TextbookStructureNodeSchema] = Field(
        default_factory=list,
        description="Top-level chapter/section hierarchy for the textbook",
    )


class TextbookSchema(BaseSchema):
    type: Literal["textbook"] = Field(
        default="textbook", description="Resource type discriminator", exclude=True
    )
    organization_urn: Optional[UrnStr] = Field(
        None, description="URN of the publishing organization"
    )
    subtitle: Optional[NonEmptyStr] = Field(
        None, description="Optional subtitle of the textbook"
    )
    authors: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=1000)] = Field(
        default_factory=list, description="Authors of the textbook"
    )
    editors: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=1000)] = Field(
        default_factory=list, description="Editors of the textbook"
    )
    publisher: Optional[NonEmptyStr] = Field(
        None, description="Publisher of the textbook"
    )
    edition: Optional[NonEmptyStr] = Field(
        None, description="Edition label, e.g. 2nd edition"
    )
    isbn10: Optional[NonEmptyStr] = Field(None, description="ISBN-10 identifier")
    isbn13: Optional[NonEmptyStr] = Field(None, description="ISBN-13 identifier")
    doi: Optional[NonEmptyStr] = Field(None, description="DOI identifier")
    topics: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=100)] = Field(
        default_factory=list, description="High-level topics covered by the textbook"
    )
    keywords: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=250)] = Field(
        default_factory=list, description="Keywords for textbook discovery"
    )
    audience: Optional[NonEmptyStr] = Field(
        None, description="Intended audience of the textbook"
    )
    region: Optional[NonEmptyStr] = Field(
        None, description="Geographic region relevant to the textbook"
    )
    review_status: ReviewStatus = Field(
        default=ReviewStatus.unreviewed,
        description="Editorial review state for this textbook",
    )
    verifier_user_id: Optional[NonEmptyStr] = Field(
        None, description="User ID of the reviewer who verified the textbook"
    )
    visibility: Visibility = Field(
        default=Visibility.internal,
        description="Whether the textbook is internal-only or public",
    )
    applicability_status: ApplicabilityStatus = Field(
        default=ApplicabilityStatus.unknown,
        description="Real-world applicability state of the textbook",
    )
    applicability_start_date: Optional[date] = Field(
        None, description="Date when the textbook became applicable"
    )
    applicability_end_date: Optional[date] = Field(
        None, description="Date when the textbook stopped being applicable"
    )
    publication_date: Optional[datetime] = Field(
        None, description="Original publication date (UTC)"
    )
    publication_year: Optional[int] = Field(
        None, description="Original publication year"
    )
    page_count: Optional[int] = Field(
        None, ge=1, description="Total page count for the textbook"
    )
    structure_tree: TextbookStructureTreeSchema | None = Field(
        None,
        description="Hierarchical table-of-contents style structure anchored to page ranges",
    )
    artifacts: List[ArtifactSchema] = Field(default_factory=list)

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_optional_year_int(v)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    @model_validator(mode="after")
    def validate_workflow_and_publication(self):
        payload = self.model_dump(mode="python", exclude_none=True)
        validate_textbook_editorial_state(payload)
        validate_guide_publication(payload)
        return self


class TextbookCreationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    urn: SlugStr = Field(..., description="URN slug for the textbook")
    title: NonEmptyStr = Field(..., description="Human-readable title")
    description: Optional[NonEmptyStr] = Field(
        None, description="Summary/abstract of the textbook"
    )
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=25)] = Field(
        default_factory=list, description="Topic tags"
    )
    status: Status = Field(default=Status.draft, description="Lifecycle status")
    url: Optional[HttpUrl] = Field(None, description="Canonical public URL")
    license: Optional[LicenseId] = Field(None, description="License identifier")
    language: Union[Iso639_1, None] = None
    organization_urn: Optional[UrnStr] = Field(
        None, description="URN of the publishing organization"
    )
    subtitle: Optional[NonEmptyStr] = None
    authors: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=1000)] = Field(
        default_factory=list
    )
    editors: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=1000)] = Field(
        default_factory=list
    )
    publisher: Optional[NonEmptyStr] = None
    edition: Optional[NonEmptyStr] = None
    isbn10: Optional[NonEmptyStr] = None
    isbn13: Optional[NonEmptyStr] = None
    doi: Optional[NonEmptyStr] = None
    topics: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=100)] = Field(
        default_factory=list
    )
    keywords: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=250)] = Field(
        default_factory=list
    )
    audience: Optional[NonEmptyStr] = None
    region: Optional[NonEmptyStr] = None
    review_status: ReviewStatus = Field(default=ReviewStatus.unreviewed)
    visibility: Visibility = Field(default=Visibility.internal)
    applicability_status: ApplicabilityStatus = Field(
        default=ApplicabilityStatus.unknown
    )
    applicability_start_date: Optional[date] = None
    applicability_end_date: Optional[date] = None
    publication_date: Optional[datetime] = None
    publication_year: Optional[int] = Field(
        None, description="Original publication year"
    )
    page_count: Optional[int] = Field(None, ge=1)
    structure_tree: TextbookStructureTreeSchema | None = None
    artifacts: List[ArtifactSchema] = Field(default_factory=list)

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_optional_year_int(v)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str]) -> List[str]:
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    @model_validator(mode="after")
    def validate_workflow_and_publication(self):
        payload = self.model_dump(mode="python", exclude_none=True)
        validate_textbook_editorial_state(payload)
        validate_guide_publication(payload)
        return self


class TextbookUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    title: Optional[NonEmptyStr] = None
    description: Optional[NonEmptyStr] = None
    tags: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=25)] | None = None
    status: Status | None = None
    url: Optional[HttpUrl] = None
    license: Optional[LicenseId] = None
    language: Union[Iso639_1, None] = None
    organization_urn: Optional[UrnStr] = None
    subtitle: Optional[NonEmptyStr] = None
    authors: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=1000)] | None = None
    editors: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=1000)] | None = None
    publisher: Optional[NonEmptyStr] = None
    edition: Optional[NonEmptyStr] = None
    isbn10: Optional[NonEmptyStr] = None
    isbn13: Optional[NonEmptyStr] = None
    doi: Optional[NonEmptyStr] = None
    topics: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=100)] | None = None
    keywords: Annotated[List[NonEmptyStr], Field(min_length=0, max_length=250)] | None = None
    audience: Optional[NonEmptyStr] = None
    region: Optional[NonEmptyStr] = None
    review_status: ReviewStatus | None = None
    visibility: Visibility | None = None
    applicability_status: ApplicabilityStatus | None = None
    applicability_start_date: date | None = None
    applicability_end_date: date | None = None
    publication_date: Optional[datetime] = None
    publication_year: int | None = None
    page_count: Optional[int] = Field(None, ge=1)
    structure_tree: TextbookStructureTreeSchema | None = None
    artifacts: List[ArtifactSchema] | None = None

    @field_validator("publication_year", mode="before")
    @classmethod
    def normalize_publication_year(cls, v):
        return normalize_optional_year_int(v)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v: List[str] | None) -> List[str] | None:
        if v is not None and len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v

    @model_validator(mode="after")
    def validate_workflow_and_publication(self):
        payload = self.model_dump(mode="python", exclude_none=True)
        validate_textbook_editorial_state(payload, partial=True)
        validate_guide_publication(payload, partial=True)
        return self


class TextbookPassageSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    id: UUID = Field(..., description="Internal UUID")
    textbook_urn: UrnStr = Field(..., description="URN of the parent textbook")
    artifact_id: UUID = Field(..., description="Textbook artifact ID containing the passage")
    page_no: int = Field(..., ge=1, description="Page number of the passage")
    sequence_no: int = Field(..., ge=1, description="Order of the passage in the page stream")
    text: NonEmptyAbstract = Field(..., description="Extracted passage text")
    char_start: int = Field(..., ge=0, description="Start character offset on the page")
    char_end: int = Field(..., ge=0, description="End character offset on the page")
    structure_node_id: Optional[NonEmptyStr] = Field(
        None, description="Matched structure tree node ID for this passage"
    )
    structure_path: List[NonEmptyStr] = Field(
        default_factory=list, description="Human-readable path into the textbook structure"
    )
    extractor_name: Optional[NonEmptyStr] = Field(
        None, description="Extractor service or model name"
    )
    extractor_run_id: Optional[NonEmptyStr] = Field(
        None, description="Extractor run identifier"
    )
    creator: Optional[str] = Field(
        None, description="Contact email for the creator/owner"
    )
    created_at: datetime = Field(..., description="Creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last-modified timestamp (UTC)")

    @model_validator(mode="after")
    def validate_offsets(self):
        if self.char_end < self.char_start:
            raise ValueError("char_end must be greater than or equal to char_start")
        return self


class TextbookPassageCreationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    textbook_urn: UrnStr = Field(..., description="URN of the parent textbook")
    artifact_id: UUID = Field(..., description="Textbook artifact ID containing the passage")
    page_no: int = Field(..., ge=1, description="Page number of the passage")
    sequence_no: Optional[int] = Field(
        None, ge=1, description="Order of the passage in the page stream"
    )
    text: NonEmptyAbstract = Field(..., description="Extracted passage text")
    char_start: int = Field(..., ge=0, description="Start character offset on the page")
    char_end: int = Field(..., ge=0, description="End character offset on the page")
    extractor_name: Optional[NonEmptyStr] = None
    extractor_run_id: Optional[NonEmptyStr] = None

    @model_validator(mode="after")
    def validate_offsets(self):
        if self.char_end < self.char_start:
            raise ValueError("char_end must be greater than or equal to char_start")
        return self


class TextbookPassageUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    page_no: int | None = Field(None, ge=1, description="Page number of the passage")
    sequence_no: Optional[int] = Field(
        None, ge=1, description="Order of the passage in the page stream"
    )
    text: Optional[NonEmptyAbstract] = Field(
        None, description="Extracted passage text"
    )
    char_start: int | None = Field(
        None, ge=0, description="Start character offset on the page"
    )
    char_end: int | None = Field(
        None, ge=0, description="End character offset on the page"
    )
    extractor_name: Optional[NonEmptyStr] = None
    extractor_run_id: Optional[NonEmptyStr] = None

    @model_validator(mode="after")
    def validate_offsets(self):
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must be greater than or equal to char_start")
        return self


class TextbookPassageImportItemSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    page_no: int = Field(..., ge=1, description="Page number of the passage")
    sequence_no: Optional[int] = Field(
        None, ge=1, description="Order of the passage in the page stream"
    )
    text: NonEmptyAbstract = Field(..., description="Extracted passage text")
    char_start: int = Field(..., ge=0, description="Start character offset on the page")
    char_end: int = Field(..., ge=0, description="End character offset on the page")

    @model_validator(mode="after")
    def validate_offsets(self):
        if self.char_end < self.char_start:
            raise ValueError("char_end must be greater than or equal to char_start")
        return self


class TextbookPassageBulkReplaceSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    artifact_id: UUID = Field(..., description="Textbook artifact ID these passages belong to")
    page_count: Optional[int] = Field(
        None, ge=1, description="Optional page count to write back to the textbook"
    )
    structure_tree: TextbookStructureTreeSchema | None = Field(
        None,
        description="Optional structure tree to write back to the textbook before anchoring passages",
    )
    extractor_name: Optional[NonEmptyStr] = Field(
        None, description="Extractor service or model name applied to all passages"
    )
    extractor_run_id: Optional[NonEmptyStr] = Field(
        None, description="Extractor run identifier applied to all passages"
    )
    passages: List[TextbookPassageImportItemSchema] = Field(
        default_factory=list, description="Extracted passages to replace for this artifact"
    )


TextbookStructureNodeSchema.model_rebuild()


class FoodCompositionTableSchema(BaseSchema):
    """
    Full representation of a Food Composition Table (e.g. Swiss FCT 7.0).
    Inherits common catalog metadata from BaseSchema.
    """

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    type: Literal["food_composition_table"] = Field(
        default="food_composition_table",
        description="Resource type discriminator",
        exclude=True,
    )

    # Specific metadata
    compiling_institution: NonEmptyStr = Field(
        ..., description="Institution responsible for compiling the table."
    )
    database_name: NonEmptyStr = Field(..., description="Name + version of database.")

    classification_schemes: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Food classification schemes (LanguaL, FoodEx2).",
    )
    standardization_schemes: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Standardization schemes (INFOODS Tags, EuroFIR).",
    )

    measurement_units: List[NonEmptyStr] = Field(
        default_factory=list, description="Units used (e.g., mg/100g, kcal/100g)."
    )
    reference_portions: List[NonEmptyStr] = Field(
        default_factory=list, description="Reference units/portions."
    )

    completeness_percent: Optional[float] = Field(
        None, ge=0, le=100, description="Percent completeness (e.g. 92%)."
    )
    completeness_description: Optional[NonEmptyStr] = Field(
        None, description="Text description of completeness."
    )
    nutrient_coverage: List[NonEmptyStr] = Field(
        default_factory=list, description="Categories covered (Energy, Vitamins, etc.)."
    )

    data_formats: List[NonEmptyStr] = Field(
        default_factory=list, description="Available formats (CSV, HTML, Web Tool)."
    )
    tasks_supported: List[NonEmptyStr] = Field(
        default_factory=list,
        description="Supported tasks (Assessment, Research, etc.).",
    )

    number_of_entries: Optional[int] = Field(
        None, ge=0, description="Approximate number of food items."
    )
    min_nutrients_per_item: Optional[int] = Field(
        None, ge=0, description="Minimum nutrients per item."
    )
    max_nutrients_per_item: Optional[int] = Field(
        None, ge=0, description="Maximum nutrients per item."
    )

    artifacts: List[ArtifactSchema] = Field(default_factory=list)

    region: Optional[NonEmptyStr] = Field(None, description="Region (e.g. CH).")

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data["type"] = "food_composition_table"
        return data


class FoodCompositionTableCreationSchema(BaseModel):
    """
    Schema for creating a Food Composition Table.
    System generates: id, urn, creator, created_at, updated_at.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )
    urn: SlugStr = Field(
        ..., description="Slug for URN (system prefixes 'urn:food_composition_table:')."
    )

    title: NonEmptyStr = Field(..., description="Human-readable title.")
    description: Optional[NonEmptyStr] = None
    tags: List[NonEmptyStr] = Field(default_factory=list)

    compiling_institution: NonEmptyStr = Field(...)
    database_name: NonEmptyStr = Field(...)

    classification_schemes: List[NonEmptyStr] = Field(default_factory=list)
    standardization_schemes: List[NonEmptyStr] = Field(default_factory=list)

    measurement_units: List[NonEmptyStr] = Field(default_factory=list)
    reference_portions: List[NonEmptyStr] = Field(default_factory=list)

    completeness_percent: Optional[float] = Field(None, ge=0, le=100)
    completeness_description: Optional[NonEmptyStr] = None
    nutrient_coverage: List[NonEmptyStr] = Field(default_factory=list)

    data_formats: List[NonEmptyStr] = Field(default_factory=list)
    tasks_supported: List[NonEmptyStr] = Field(default_factory=list)

    number_of_entries: Optional[int] = Field(None, ge=0)
    min_nutrients_per_item: Optional[int] = Field(None, ge=0)
    max_nutrients_per_item: Optional[int] = Field(None, ge=0)

    url: Optional[HttpUrl] = None
    license: Optional[LicenseId] = None
    language: Optional[Iso639_1] = None
    region: Optional[NonEmptyStr] = None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v):
        if len(set(map(str.lower, v))) != len(v):
            raise ValueError("tags must be unique (case-insensitive)")
        return v


class FoodCompositionTableUpdateSchema(BaseModel):
    """
    Schema for updating an existing Food Composition Table.
    All fields optional; system fields cannot be modified.
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

    completeness_percent: Optional[float] = Field(None, ge=0, le=100)
    completeness_description: Optional[NonEmptyStr] = None
    nutrient_coverage: Optional[List[NonEmptyStr]] = None

    data_formats: Optional[List[NonEmptyStr]] = None
    tasks_supported: Optional[List[NonEmptyStr]] = None

    number_of_entries: Optional[int] = Field(None, ge=0)
    min_nutrients_per_item: Optional[int] = Field(None, ge=0)
    max_nutrients_per_item: Optional[int] = Field(None, ge=0)

    url: Optional[HttpUrl] = None
    license: Optional[LicenseId] = None
    language: Optional[Iso639_1] = None
    region: Optional[NonEmptyStr] = None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, v):
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


def normalize_publication_year(v):
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
            raise ValueError(
                "publication_year must be an integer year or ISO date string"
            )

    # Case 4: already a date/datetime
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v

    raise ValueError("Invalid publication_year format")
