------------------------------------------------------------
-- GLOBAL FOOD COMPOSITION DATABASE SCHEMA
-- Supports:
--  - Multiple FCT datasets
--  - Canonical food concepts
--  - Nutrient ontology
--  - Composition values
--  - Portions
--  - Ambiguous mappings
--  - Quality scoring
--  - JSONB for flexibility
------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

------------------------------------------------------------
-- 1. FCT Sources Table
------------------------------------------------------------
CREATE TABLE fct_source (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    acronym TEXT,
    country_iso3 CHAR(3),
    version TEXT,
    publication_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

------------------------------------------------------------
-- 2. Canonical Food Concepts
------------------------------------------------------------
CREATE TABLE food_concept (
    id UUID PRIMARY KEY,
    scientific_name TEXT,
    group_system TEXT,
    group_code TEXT,
    group_label TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

------------------------------------------------------------
-- 3. Food Identifiers (External Codes)
------------------------------------------------------------
CREATE TABLE food_identifier (
    id UUID PRIMARY KEY,
    food_concept_id UUID NOT NULL REFERENCES food_concept(id) ON DELETE CASCADE,
    system TEXT NOT NULL,
    code TEXT NOT NULL,
    uri TEXT
);

CREATE INDEX idx_food_identifier_food ON food_identifier(food_concept_id);
CREATE INDEX idx_food_identifier_system_code ON food_identifier(system, code);

------------------------------------------------------------
-- 4. Food Names (Multilingual)
------------------------------------------------------------
CREATE TABLE food_name (
    id UUID PRIMARY KEY,
    food_concept_id UUID NOT NULL REFERENCES food_concept(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    lang TEXT,
    is_primary BOOLEAN DEFAULT FALSE,
    name_type TEXT
);

CREATE INDEX idx_food_name_food ON food_name(food_concept_id);
CREATE INDEX idx_food_name_text ON food_name USING gin (to_tsvector('simple', name));

------------------------------------------------------------
-- 5. Food Composition Records (Core Table)
------------------------------------------------------------
CREATE TABLE food_composition_record (
    id UUID PRIMARY KEY,
    fct_id UUID NOT NULL REFERENCES fct_source(id) ON DELETE CASCADE,
    food_concept_id UUID NOT NULL REFERENCES food_concept(id) ON DELETE CASCADE,
    basis TEXT NOT NULL, -- enum in Pydantic, text in SQL
    preparation JSONB DEFAULT '{}'::jsonb,
    fingerprint TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_fcr_fct ON food_composition_record(fct_id);
CREATE INDEX idx_fcr_food ON food_composition_record(food_concept_id);
CREATE INDEX idx_fcr_fingerprint ON food_composition_record(fingerprint);

------------------------------------------------------------
-- 6. Nutrient Reference Table (Ontology)
------------------------------------------------------------
CREATE TABLE nutrient_ref (
    id TEXT PRIMARY KEY,
    name TEXT,
    unit TEXT NOT NULL,
    source_code TEXT,
    source_name TEXT,
    ontology_uri TEXT
);

------------------------------------------------------------
-- 7. Nutrient Amount Values
------------------------------------------------------------
CREATE TABLE nutrient_amount (
    id UUID PRIMARY KEY,
    record_id UUID NOT NULL REFERENCES food_composition_record(id) ON DELETE CASCADE,
    nutrient_id TEXT NOT NULL REFERENCES nutrient_ref(id),
    value DOUBLE PRECISION,
    unit TEXT NOT NULL,
    basis TEXT NOT NULL,
    amount_type TEXT NOT NULL,
    original_value_raw TEXT,
    std_error DOUBLE PRECISION,
    n_samples INT,
    detection_limit DOUBLE PRECISION
);

CREATE INDEX idx_nutrient_amount_record ON nutrient_amount(record_id);
CREATE INDEX idx_nutrient_amount_nutrient ON nutrient_amount(nutrient_id);

------------------------------------------------------------
-- 8. Portion Measures
------------------------------------------------------------
CREATE TABLE portion_measure (
    id UUID PRIMARY KEY,
    record_id UUID NOT NULL REFERENCES food_composition_record(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    mass_g DOUBLE PRECISION,
    volume_ml DOUBLE PRECISION,
    description TEXT
);

CREATE INDEX idx_portion_record ON portion_measure(record_id);

------------------------------------------------------------
-- 9. Record Quality Metadata
------------------------------------------------------------
CREATE TABLE record_quality (
    id UUID PRIMARY KEY,
    record_id UUID NOT NULL REFERENCES food_composition_record(id) ON DELETE CASCADE,
    completeness_score DOUBLE PRECISION,
    source_priority INT,
    notes TEXT
);

CREATE INDEX idx_quality_record ON record_quality(record_id);

------------------------------------------------------------
-- 10. Alternative Mapping (Ambiguity Resolution)
------------------------------------------------------------
CREATE TABLE alternative_mapping (
    id UUID PRIMARY KEY,
    record_id UUID NOT NULL REFERENCES food_composition_record(id) ON DELETE CASCADE,
    food_concept_id UUID NOT NULL REFERENCES food_concept(id),
    confidence DOUBLE PRECISION NOT NULL,
    rationale TEXT
);

CREATE INDEX idx_alt_map_record ON alternative_mapping(record_id);
CREATE INDEX idx_alt_map_food ON alternative_mapping(food_concept_id);