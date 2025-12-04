# schemas/fct.py
from __future__ import annotations

from typing import Any, Optional, List, Dict, Literal
from uuid import UUID, uuid4
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict, field_validator


# ============================================================
# ENUMS
# ============================================================

class LangCode(str, Enum):
    EN = "en"
    FR = "fr"
    ES = "es"
    DE = "de"


class ValueBasis(str, Enum):
    PER_100G = "per_100g"
    PER_100ML = "per_100ml"
    PER_SERVING = "per_serving"
    PER_100KCAL = "per_100kcal"
    PER_100KJ = "per_100kJ"


class QuantityUnit(str, Enum):
    G = "g"
    MG = "mg"
    UG = "µg"
    KCAL = "kcal"
    KJ = "kJ"
    IU = "IU"
    UNKNOWN = "unknown"


class AmountType(str, Enum):
    ANALYTICAL = "analytical"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    IMPUTED = "imputed"
    MISSING = "missing"
    TRACE = "trace"


# ============================================================
# SOURCE & PROVENANCE
# ============================================================

class SourceInfo(BaseModel):
    """
    Provenance information about the data source (FCT).
    """
    model_config = ConfigDict(extra="allow")

    id: UUID = Field(default_factory=uuid4)
    name: str
    acronym: Optional[str] = None
    country_iso3: Optional[str] = None
    version: Optional[str] = None
    url: Optional[str] = None
    publication_date: Optional[date] = None


# ============================================================
# FOOD IDENTITY MODELS
# ============================================================

class FoodIdentifier(BaseModel):
    system: str
    code: str
    uri: Optional[str] = None


class FoodName(BaseModel):
    name: str
    lang: Optional[str] = None
    is_primary: bool = False
    name_type: Optional[Literal["scientific", "common", "local", "brand"]] = None


class FoodGroupRef(BaseModel):
    system: Optional[str] = None
    code: Optional[str] = None
    label: Optional[str] = None


class FoodConcept(BaseModel):
    """
    Canonical food identity representing a unique food item across FCTs.
    """
    id: UUID = Field(default_factory=uuid4)
    identifiers: List[FoodIdentifier] = []
    names: List[FoodName] = Field(default_factory=list)
    group: Optional[FoodGroupRef] = None
    scientific_name: Optional[str] = None

    @field_validator("names")
    @classmethod
    def ensure_primary(cls, names: List[FoodName]) -> List[FoodName]:
        if names and not any(n.is_primary for n in names):
            names[0].is_primary = True
        return names


# ============================================================
# NUTRIENT SCHEMA
# ============================================================

class NutrientRef(BaseModel):
    """
    Canonical nutrient identifier with optional source mapping.
    """
    id: str
    name: Optional[str] = None
    unit: QuantityUnit = QuantityUnit.UNKNOWN
    source_code: Optional[str] = None
    source_name: Optional[str] = None
    ontology_uri: Optional[str] = None


class NutrientAmount(BaseModel):
    """
    Nutrient value and metadata for interpretation.
    """
    nutrient: NutrientRef
    value: Optional[float]
    unit: QuantityUnit
    basis: ValueBasis = ValueBasis.PER_100G
    amount_type: AmountType = AmountType.ANALYTICAL
    original_value_raw: Optional[str] = None
    std_error: Optional[float] = None
    n_samples: Optional[int] = None
    detection_limit: Optional[float] = None


# ============================================================
# PORTION / HOUSEHOLD MEASURES
# ============================================================

class PortionMeasure(BaseModel):
    """
    Represents a named portion and its mass/volume equivalent.
    """
    label: str
    mass_g: Optional[float] = None
    volume_ml: Optional[float] = None
    description: Optional[str] = None


# ============================================================
# PREPARATION & CONTEXT
# ============================================================

class PreparationContext(BaseModel):
    """
    Cooking, processing, and measurement context.
    """
    country_iso3: Optional[str] = None
    edible_portion_desc: Optional[str] = None
    cooking_method: Optional[str] = None
    processing: Optional[str] = None
    moisture_adjusted: Optional[bool] = None
    remarks: Optional[str] = None


# ============================================================
# QUALITY & AMBIGUITY HANDLING
# ============================================================

class MappingCandidate(BaseModel):
    """
    Alternative matches for food mapping with confidence score.
    """
    food_concept_id: UUID
    confidence: float = Field(..., ge=0, le=1)
    rationale: Optional[str] = None


class RecordQuality(BaseModel):
    completeness_score: Optional[float] = Field(None, ge=0, le=1)
    source_priority: Optional[int] = None
    notes: Optional[str] = None


# ============================================================
# CANONICAL FOOD COMPOSITION RECORD
# ============================================================

class FoodCompositionRecord(BaseModel):
    """
    Canonical representation of one composition entry from any FCT.
    """
    model_config = ConfigDict(extra="allow")

    id: UUID = Field(default_factory=uuid4)
    source: SourceInfo
    source_row_id: Optional[str] = None

    food_concept: FoodConcept
    preparation: PreparationContext

    basis: ValueBasis = ValueBasis.PER_100G

    nutrients: List[NutrientAmount] = Field(default_factory=list)
    portions: List[PortionMeasure] = Field(default_factory=list)

    quality: Optional[RecordQuality] = None
    alternative_mappings: List[MappingCandidate] = Field(default_factory=list)

    fingerprint: Optional[str] = None

    created_at: Optional[date] = None
    updated_at: Optional[date] = None


# ============================================================
# RAW INGESTION MODEL (for importing ANY FCT)
# ============================================================

class RawFCTEntry(BaseModel):
    """
    Raw entry as received from any Food Composition Table.
    The mapping layer converts this into a FoodCompositionRecord.
    """
    source: SourceInfo
    payload: Dict[str, Any] = Field(
        ..., description="Arbitrary key/value pairs from the source FCT row."
    )
