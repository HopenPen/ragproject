# Назначение файла: единый каталог typed entities, CSV, единиц и правил.
from app.schemas.graphs import (Material, Device, Layer, Measurement, SolarResult, Configuration,
                                Dataset, Task, Experiment, RagResult, SolarGraph, RagGraph, Bibliography)
from app.domain import UNITS, RULES_VERSION

ENTITIES = {
    'material': ('solar-v1', 'materials', 'material_id', Material),
    'device': ('solar-v1', 'devices', 'device_id', Device),
    'layer': ('solar-v1', 'layers', 'layer_id', Layer),
    'measurement': ('solar-v1', 'measurements', 'measurement_id', Measurement),
    'solar_result': ('solar-v1', 'results', 'result_id', SolarResult),
    'configuration': ('rag-v1', 'configurations', 'config_id', Configuration),
    'dataset': ('rag-v1', 'datasets', 'dataset_id', Dataset),
    'task': ('rag-v1', 'tasks', 'task_id', Task),
    'experiment': ('rag-v1', 'experiments', 'experiment_id', Experiment),
    'rag_result': ('rag-v1', 'results', 'result_id', RagResult),
}
GRAPHS = {'solar-v1': SolarGraph, 'rag-v1': RagGraph}
PUBLICATION_COLUMNS = 'publication_id,title,year,DOI,authors,in_scope,exclusion_reason'.split(',')
ISSUE_COLUMNS = 'publication_id,issue_id,record_ids,check_name,description,source_page,source_fragment'.split(',')
# CSV order is the exact order in the active specification, independent of DTO inheritance.
RESULT_COLUMNS = {
    'solar-v1': 'result_id,device_id,measurement_id,material_id,metric_name,metric_value,metric_unit,aggregation,spread_value,n_devices,time_point,time_unit,raw_value,raw_unit,normalized_value,normalized_unit,result_origin,cited_publication_id,source_page,source_section,source_table,source_figure,source_fragment,extraction_status,duplicate_of,note',
    'rag-v1': 'result_id,experiment_id,config_id,dataset_id,task_id,metric_group,metric_name,metric_variant,metric_direction,metric_k,metric_value,metric_unit,baseline_value,aggregation,sample_size,raw_value,raw_unit,normalized_value,normalized_unit,result_origin,cited_publication_id,source_page,source_section,source_table,source_figure,source_fragment,extraction_status,duplicate_of,note',
}


def csv_columns(profile):
    cols = {'publications': PUBLICATION_COLUMNS}
    for p, collection, key, model in ENTITIES.values():
        if p == profile:
            cols[collection] = ['publication_id'] + (RESULT_COLUMNS[p].split(',') if collection == 'results' else list(model.model_fields))
    cols['issues'] = ISSUE_COLUMNS
    return cols


def rules(profile):
    common = ['schema', 'links', 'duplicate_cycles', 'source', 'normalization', 'contradiction']
    defined = (['jv_consistency', 'voc_limit', 'eqe_consistency', 'champion_vs_mean', 'hysteresis_index', 'comparability'] if profile == 'solar-v1'
               else ['metric_scale', 'metric_k', 'protocol_mismatch', 'baseline_comparability'])
    result = [{'rule': x, 'version': RULES_VERSION, 'status': 'project_defined', 'applicability': 'requires explicit source conditions'} for x in common + defined]
    if profile == 'solar-v1':
        result += [{'rule': x, 'version': RULES_VERSION, 'status': 'awaiting_definition'} for x in ('official_Jsc_limits', 'official_FF_limits', 'official_PCE_limits')]
    return {'rules': result, 'thresholds': {'jv_relative': '0.03', 'eqe_relative': '0.05'} if profile == 'solar-v1' else {}}


def passport(profile):
    return {'domain_profile': profile, 'schema_version': '1.0.0',
            'status': 'official_template' if profile == 'solar-v1' else 'project_defined_recommended',
            'fields': GRAPHS[profile].model_json_schema(), 'csv': csv_columns(profile),
            'units': UNITS if profile == 'solar-v1' else {'metric_scale': 'explicit unit only'},
            'relations': {'solar-v1': {'devices.absorber_material_id': 'materials.material_id', 'layers.device_id': 'devices.device_id',
                         'measurements.device_id[]': 'devices.device_id', 'results.measurement_id': 'measurements.measurement_id'},
                         'rag-v1': {'results.config_id': 'configurations.config_id', 'results.dataset_id': 'datasets.dataset_id',
                         'results.task_id': 'tasks.task_id', 'results.experiment_id': 'experiments.experiment_id'}}[profile],
            'rules': rules(profile)}
