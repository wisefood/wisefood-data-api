FoodCompositionRecord
├── id : UUID
├── source : SourceInfo
│   ├── id : UUID
│   ├── name : str
│   ├── acronym : str?
│   ├── country_iso3 : str?
│   ├── version : str?
│   ├── url : str?
│   └── publication_date : date?
│
├── source_row_id : str?
│
├── food_concept : FoodConcept
│   ├── id : UUID
│   ├── identifiers : [FoodIdentifier]
│   │   ├── system : str
│   │   ├── code : str
│   │   └── uri : str?
│   │
│   ├── names : [FoodName]
│   │   ├── name : str
│   │   ├── lang : str?
│   │   ├── is_primary : bool
│   │   └── name_type : "scientific" | "common" | "local" | "brand"?
│   │
│   ├── group : FoodGroupRef?
│   │   ├── system : str?
│   │   ├── code : str?
│   │   └── label : str?
│   │
│   └── scientific_name : str?
│
├── preparation : PreparationContext
│   ├── country_iso3 : str?
│   ├── edible_portion_desc : str?
│   ├── cooking_method : str?
│   ├── processing : str?
│   ├── moisture_adjusted : bool?
│   └── remarks : str?
│
├── basis : ValueBasis (PER_100G | PER_100ML | PER_SERVING | PER_100KCAL | PER_100KJ)
│
├── nutrients : [NutrientAmount]
│   ├── nutrient : NutrientRef
│   │   ├── id : str
│   │   ├── name : str?
│   │   ├── unit : QuantityUnit
│   │   ├── source_code : str?
│   │   ├── source_name : str?
│   │   └── ontology_uri : str?
│   │
│   ├── value : float?
│   ├── unit : QuantityUnit
│   ├── basis : ValueBasis
│   ├── amount_type : AmountType (ANALYTICAL | CALCULATED | IMPUTED | ...)
│   ├── original_value_raw : str?
│   ├── std_error : float?
│   ├── n_samples : int?
│   └── detection_limit : float?
│
├── portions : [PortionMeasure]
│   ├── label : str
│   ├── mass_g : float?
│   ├── volume_ml : float?
│   └── description : str?
│
├── quality : RecordQuality?
│   ├── completeness_score : float? (0–1)
│   ├── source_priority : int?
│   └── notes : str?
│
├── alternative_mappings : [MappingCandidate]
│   ├── food_concept_id : UUID
│   ├── confidence : float (0–1)
│   └── rationale : str?
│
├── fingerprint : str?
│
├── created_at : date?
└── updated_at : date?
