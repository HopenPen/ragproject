from typing import Literal, Annotated
from pydantic import Field, model_validator
from app.schemas.graphs import Strict, Classification, SolarGraph, RagGraph, Bibliography, Scope


class CorpusCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str = ''
    split: str = Field(default='custom', max_length=32)
    classification_mode: Literal['auto'] = 'auto'


class CorpusPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    split: str | None = Field(default=None, max_length=32)


class DocumentPatch(Strict):
    display_name: str | None = Field(default=None, max_length=255)
    note: str | None = None


class JobCreate(Strict):
    kind: Literal['process', 'classify', 'validate', 'export']
    document_ids: list[str] | None = None
    all_documents: bool = False
    target_profiles: list[Literal['solar-v1', 'rag-v1']] | None = Field(default=None, min_length=1)
    allow_incomplete: bool = False
    check_sources: bool = True
    run_external_checker: bool = True
    force: bool = False
    reason: str | None = None

    @model_validator(mode='after')
    def applicable(self):
        if bool(self.document_ids) == self.all_documents:
            raise ValueError('Specify document_ids or all_documents')
        if self.document_ids and len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError('Duplicate document ids')
        if self.target_profiles and len(set(self.target_profiles)) != len(self.target_profiles):
            raise ValueError('Duplicate target profiles')
        fields = self.model_fields_set
        if self.kind in ('process', 'classify') and fields & {'target_profiles', 'allow_incomplete', 'check_sources', 'run_external_checker'}:
            raise ValueError('Validation/export fields are not applicable')
        if self.kind in ('validate', 'export') and fields & {'force', 'reason'}:
            raise ValueError('Force/reason apply only to classification reprocessing')
        if self.force and not self.reason:
            raise ValueError('Force requires a reason')
        return self


class ClassificationReview(Strict):
    expected_revision: str
    decision: Classification
    reason: str = Field(min_length=1)
    replace_reviewed: bool = False


class GraphWrite(Strict):
    graph: Annotated[SolarGraph | RagGraph, Field(discriminator='domain_profile')]
    reason: str = Field(min_length=1)


class PublicationCreate(GraphWrite):
    document_id: str


class MetadataPatch(Strict):
    bibliography: Bibliography | None = None
    scope: Scope | None = None
    reason: str = Field(min_length=1)


class Reason(Strict):
    reason: str = Field(min_length=1)


class Review(Reason):
    review: Literal['confirmed', 'rejected', 'dismissed', 'open']


class Comparison(Strict):
    profile: Literal['solar-v1', 'rag-v1']
    results: list[dict] = Field(min_length=1, max_length=100)
    area_tolerance: str | None = None


class EntityWrite(Reason):
    record: dict
