from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[Decimal, Field(allow_inf_nan=False)]
PositivePage = Annotated[int, Field(gt=0)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[\w.:-]+$')]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


class Bibliography(Strict):
    title: str | None = None
    year: Annotated[int, Field(ge=1500, le=2200)] | None = None
    DOI: str | None = None
    authors: list[str] = []


class Scope(Strict):
    in_scope: bool | None = None
    exclusion_reason: str | None = None


class Evidence(Strict):
    evidence_id: Identifier
    entity_id: str | None = None
    field_path: str = Field(description='Exact field on the entity identified by entity_id, e.g. metric_value or top_k. With entity_id=null, use bibliography.title or scope.in_scope. Never a collection name alone.')
    source_page: PositivePage
    section: str | None = None
    table: str | None = None
    figure: str | None = None
    fragment: str | None = None
    bbox: tuple[Number, Number, Number, Number] | None = None
    method: Literal['text', 'table', 'ocr', 'vision', 'manual']
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    review: Literal['open', 'confirmed', 'rejected', 'needs_review'] = 'open'
    artifact_ref: str | None = None
    reading_method: str | None = None
    review_reason: str | None = None

    @model_validator(mode='after')
    def visual_source(self):
        if self.method == 'vision' and (not self.artifact_ref or not self.reading_method):
            raise ValueError('Vision evidence requires artifact_ref and reading_method')
        if self.method == 'vision' and not (self.figure or self.table or self.bbox):
            raise ValueError('Vision evidence requires a table/figure identifier or PDF bbox')
        if self.bbox and (min(self.bbox) < 0 or self.bbox[2] <= self.bbox[0] or self.bbox[3] <= self.bbox[1]):
            raise ValueError('Invalid top-left PDF bbox')
        return self


class Material(Strict):
    material_id: Identifier
    material_name_raw: str | None = None
    formula_normalized: str | None = None
    material_class: Literal['perovskite', 'CIGS', 'CdTe', 'kesterite', 'Sb2Se3', 'thin-film Si', 'other'] | None = None
    dimensionality: Literal['3D', '2D', '2D-3D'] | None = None
    additives: str | None = None
    bandgap_value: Number | None = None
    bandgap_unit: Literal['eV'] | None = None
    bandgap_method: Literal['Tauc', 'EQE', 'PL', 'cited'] | None = None
    note: str | None = None


class Device(Strict):
    device_id: Identifier
    absorber_material_id: str | None = None
    device_label: str | None = None
    device_role: Literal['control', 'target', 'record'] | None = None
    device_type: Literal['cell', 'minimodule', 'module'] | None = None
    architecture: Literal['n-i-p', 'p-i-n', 'substrate', 'superstrate'] | None = None
    substrate_type: Literal['rigid', 'flexible'] | None = None
    active_area: Number | None = None
    area_unit: Literal['cm2'] | None = None
    area_definition: Literal['designated illumination', 'aperture', 'total'] | None = None
    encapsulation: str | None = None
    note: str | None = None


class Layer(Strict):
    layer_id: Identifier
    device_id: str
    layer_order: Annotated[int, Field(gt=0)]
    layer_function: Literal['front_contact', 'ETL', 'absorber', 'passivation', 'HTL', 'interlayer', 'recombination', 'back_contact'] | None = None
    layer_material: str | None = None
    layer_thickness: Number | None = None
    thickness_unit: Literal['nm'] | None = None
    deposition_method: str | None = None
    annealing_temperature: Number | None = None
    annealing_time: str | None = None
    atmosphere: str | None = None
    note: str | None = None


class Measurement(Strict):
    measurement_id: Identifier
    device_id: list[str] = []
    measurement_type: Literal['J-V', 'MPP tracking', 'EQE', 'stability'] | None = None
    spectrum: str | None = None
    light_intensity: Number | None = None
    intensity_unit: str | None = None
    scan_direction: Literal['reverse', 'forward', 'average'] | None = None
    scan_rate: str | None = None
    mask_used: bool | None = None
    certified: bool | None = None
    certification_lab: str | None = None
    temperature: Number | None = None
    stability_protocol: Literal['ISOS-D', 'ISOS-L', 'ISOS-T', 'other'] | None = None
    stress_conditions: str | None = None
    note: str | None = None


class ResultBase(Strict):
    result_id: Identifier
    metric_name: str
    metric_value: Number | None = None
    metric_unit: str | None = None
    raw_value: str | None = None
    raw_unit: str | None = None
    normalized_value: Number | None = None
    normalized_unit: str | None = None
    result_origin: Literal['primary', 'cited']
    cited_publication_id: str | None = None
    source_page: PositivePage
    source_section: str | None = None
    source_table: str | None = None
    source_figure: str | None = None
    source_fragment: str | None = None
    extraction_status: Literal['extracted', 'present_not_extractable', 'absent']
    duplicate_of: str | None = None
    note: str | None = None


class SolarResult(ResultBase):
    metric_name: str = Field(description='Use canonical PCE, Voc, Jsc, FF, Rs, Rsh, HI, Jsc_EQE, stabilized_PCE, T80, retained_PCE for these quantities. Other metrics may retain their explicit source names.')
    device_id: str | None = None
    measurement_id: str | None = None
    material_id: str | None = None
    aggregation: Literal['champion', 'mean', 'median'] | None = None
    spread_value: Number | None = None
    n_devices: Annotated[int, Field(ge=1)] | None = None
    time_point: Number | None = None
    time_unit: str | None = None


class Configuration(Strict):
    config_id: Identifier
    rag_variant: str | None = None
    retrieval_method: str | None = None
    retriever_model: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    chunking_method: str | None = None
    chunk_size: Annotated[int, Field(ge=0)] | None = None
    chunk_overlap: Annotated[int, Field(ge=0)] | None = None
    chunk_unit: str | None = None
    index_type: str | None = None
    vector_store: str | None = None
    top_k: Annotated[int, Field(ge=0)] | None = None
    reranker_model: str | None = None
    generator_model: str | None = None
    generator_version: str | None = None
    prompt_strategy: str | None = None
    context_strategy: str | None = None
    note: str | None = None


class Dataset(Strict):
    dataset_id: Identifier
    dataset_name: str | None = None
    dataset_version: str | None = None
    language: str | None = None
    data_split: str | None = None
    scientific_domain: str | None = None
    note: str | None = None


class Task(Strict):
    task_id: Identifier
    task_type: str | None = None
    note: str | None = None


class Experiment(Strict):
    experiment_id: Identifier
    evaluation_protocol: str | None = None
    baseline_name: str | None = None
    hardware: str | None = None
    latency_ms: Number | None = None
    tokens_per_query: Number | None = None
    sample_size: Annotated[int, Field(ge=0)] | None = None
    note: str | None = None


class RagResult(ResultBase):
    experiment_id: str | None = None
    config_id: str | None = None
    dataset_id: str | None = None
    task_id: str | None = None
    metric_group: str | None = None
    metric_variant: str | None = None
    metric_direction: str | None = None
    metric_k: Annotated[int, Field(ge=0)] | None = None
    baseline_value: Number | None = None
    aggregation: str | None = None
    sample_size: Annotated[int, Field(ge=0)] | None = None


class GraphBase(Strict):
    schema_version: Literal['1.0.0'] = '1.0.0'
    bibliography: Bibliography
    scope: Scope
    evidence: list[Evidence] = []


class SolarGraph(GraphBase):
    domain_profile: Literal['solar-v1']
    materials: list[Material] = []
    devices: list[Device] = []
    layers: list[Layer] = []
    measurements: list[Measurement] = []
    results: list[SolarResult] = []


class RagGraph(GraphBase):
    domain_profile: Literal['rag-v1']
    configurations: list[Configuration] = []
    datasets: list[Dataset] = []
    tasks: list[Task] = []
    experiments: list[Experiment] = []
    results: list[RagResult] = []


class Classification(Strict):
    bibliography: Bibliography
    labels: list[Literal['solar', 'rag']]
    outcome: Literal['resolved', 'needs_review', 'outside', 'unreadable']
    solar: Scope
    rag: Scope
    confidence: Annotated[float, Field(ge=0, le=1)]
    evidence: list[Evidence]

    @model_validator(mode='after')
    def coherent(self):
        if len(set(self.labels)) != len(self.labels):
            raise ValueError('Duplicate labels')
        if self.outcome == 'outside' and self.labels:
            raise ValueError('Outside classification cannot contain labels')
        if self.outcome == 'resolved' and not self.labels:
            raise ValueError('Resolved classification requires a label')
        for label in ('solar', 'rag'):
            if label not in self.labels and getattr(self, label).in_scope is True:
                raise ValueError('In-scope profile must have a topic label')
        return self
