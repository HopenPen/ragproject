import re
from collections import defaultdict
from decimal import Decimal
from pydantic import ValidationError
from app.domain import Error, UNITS, RULES_VERSION, decimal_value, normalize_value, quote_normalize, uid
from app.profiles import GRAPHS, ENTITIES, rules


def issue(rule, description, records=None, severity='warning', **details):
    return {'issue_id': uid(), 'rule': rule, 'version': RULES_VERSION, 'severity': severity,
            'record_ids': records or [], 'description': description, **details}


def typed_graph(value):
    profile = value.get('domain_profile')
    if profile not in GRAPHS:
        raise Error(422, 'unknown_profile', 'Unknown domain profile')
    try:
        return GRAPHS[profile].model_validate(value).model_dump(mode='json')
    except ValidationError as exc:
        raise Error(422, 'invalid_graph', 'Invalid graph schema', exc.errors(include_context=False))


def structural(graph, page_count=None):
    profile = graph['domain_profile']
    errors, ids, collections = [], {}, {}
    for p, collection, key, dto in ENTITIES.values():
        if p != profile:
            continue
        rows = graph[collection]
        values = [r[key] for r in rows]
        if len(set(values)) != len(values):
            errors.append(issue('schema', f'Duplicate ids in {collection}', severity='error'))
        ids[collection] = set(values)
        collections[collection] = {r[key]: r for r in rows}
    if graph['scope']['in_scope'] is not True and any(collections.values()):
        errors.append(issue('excluded_graph', 'Unknown or excluded scope must have empty subject collections', severity='error'))
    if graph['scope']['in_scope'] is False and not graph['scope']['exclusion_reason']:
        errors.append(issue('excluded_graph', 'Exclusion reason is required', severity='error'))
    links = ({'devices': {'absorber_material_id': 'materials'}, 'layers': {'device_id': 'devices'},
              'measurements': {'device_id': 'devices'}, 'results': {'device_id': 'devices', 'measurement_id': 'measurements', 'material_id': 'materials', 'duplicate_of': 'results'}}
             if profile == 'solar-v1' else {'results': {'config_id': 'configurations', 'dataset_id': 'datasets', 'task_id': 'tasks', 'experiment_id': 'experiments', 'duplicate_of': 'results'}})
    for collection, fields in links.items():
        for row in graph[collection]:
            for field, target in fields.items():
                value = row.get(field)
                values = value if isinstance(value, list) else [value]
                for val in values:
                    if val is not None and val not in ids[target]:
                        errors.append(issue('links', f'{collection}.{field} references missing {target}: {val}', severity='error'))
    all_ids = set().union(*ids.values())
    if sum(len(values) for values in ids.values()) != len(all_ids):
        errors.append(issue('schema', 'Entity ids must be unique across this publication/profile to avoid ambiguous evidence', severity='error'))
    ev_ids = set()
    for ev in graph['evidence']:
        if ev['evidence_id'] in ev_ids:
            errors.append(issue('schema', 'Duplicate evidence id', severity='error'))
        ev_ids.add(ev['evidence_id'])
        if ev['entity_id'] is not None and ev['entity_id'] not in all_ids:
            errors.append(issue('links', 'Evidence references missing entity', severity='error'))
        entity = next((row for collection in collections.values() for entity_id, row in collection.items() if entity_id == ev['entity_id']), None)
        field = re.split(r'[.\[\]/]', ev['field_path'])[-1]
        if not field or (entity and field not in entity) or (not entity and ev['field_path'].split('.')[0] not in ('bibliography', 'scope')):
            errors.append(issue('links', 'Evidence field_path does not identify a graph/entity field', severity='error'))
        elif not entity:
            cursor = graph
            for part in ev['field_path'].split('.'):
                if not isinstance(cursor, dict) or part not in cursor:
                    errors.append(issue('links', 'Evidence field_path does not exist', severity='error'))
                    break
                cursor = cursor[part]
        if page_count and ev['source_page'] > page_count:
            errors.append(issue('source_page', 'Evidence page out of range', severity='error'))
    measurement_map = collections.get('measurements', {})
    layer_orders = set()
    for layer in graph.get('layers', []):
        order = (layer['device_id'], layer['layer_order'])
        if order in layer_orders:
            errors.append(issue('links', 'Duplicate layer order within device', severity='error'))
        layer_orders.add(order)
    result_map = collections['results']
    for result in graph['results']:
        rid = result['result_id']
        def error(rule, description):
            errors.append(issue(rule, description, [rid], severity='error', source_page=result['source_page']))
        if page_count and result['source_page'] > page_count:
            error('source_page', 'Result page out of range')
        evidence = [e for e in graph['evidence'] if e['entity_id'] == rid]
        if not (result.get('source_fragment') or '').strip() and not evidence:
            error('source', 'Every result requires source evidence')
        if result['result_origin'] == 'cited':
            if not result['cited_publication_id']:
                error('links', 'Cited result needs a literature reference')
            if profile == 'solar-v1' and (result['device_id'] or result['measurement_id']):
                error('links', 'Cited solar result must not reference local devices/measurements')
        elif profile == 'rag-v1' and any(result.get(f) is None for f in ('config_id', 'dataset_id', 'task_id', 'experiment_id')):
            error('links', 'Primary RAG result requires configuration/dataset/task/experiment')
        if profile == 'solar-v1' and result['measurement_id'] in measurement_map and result['device_id']:
            if result['device_id'] not in measurement_map[result['measurement_id']]['device_id']:
                error('links', 'Measurement does not include the result device')
        if decimal_value(result['metric_value']) != decimal_value(result['normalized_value']) or result['metric_unit'] != result['normalized_unit']:
            error('normalization', 'metric value/unit must equal normalized value/unit')
        expected = UNITS.get(result['metric_name']) if profile == 'solar-v1' else None
        if expected and result['normalized_value'] is not None and expected != result['normalized_unit']:
            error('normalization', f'Target unit must be {expected}')
        converted = normalize_value(result['raw_value'], result['raw_unit'], result['normalized_unit'])
        if result['normalized_value'] is not None:
            if converted is None:
                error('normalization', 'Normalization is not supported by unambiguous raw value/unit')
            elif abs(converted - Decimal(result['normalized_value'])) > max(abs(converted), Decimal(1)) * Decimal('1e-10'):
                error('normalization', 'Raw/normalized values disagree')
        seen, cursor = {rid}, result.get('duplicate_of')
        while cursor and cursor in result_map:
            if cursor in seen:
                error('duplicate_cycles', 'Duplicate self-link or cycle')
                break
            seen.add(cursor)
            cursor = result_map[cursor].get('duplicate_of')
        duplicate = result_map.get(result.get('duplicate_of'))
        local_fields = ('device_id', 'measurement_id') if profile == 'solar-v1' else ('config_id', 'experiment_id', 'dataset_id', 'task_id')
        if duplicate and (comparison_key(graph, result) != comparison_key(graph, duplicate) or result['normalized_value'] != duplicate['normalized_value'] or
                          any(result.get(k) != duplicate.get(k) for k in (*local_fields, 'result_origin', 'cited_publication_id'))):
            error('links', 'Duplicates must have the same semantic conditions and normalized value')
    return errors


def enforce_graph(value, page_count=None):
    graph = typed_graph(value)
    errors = structural(graph, page_count)
    if errors:
        raise Error(422, 'structural_errors', 'Graph failed structural validation', errors)
    return graph


def source_checks(graph, pages, artifacts=None):
    findings = []
    page_map = {p['number']: p for p in pages}
    artifact_map = {a['id']: a for a in artifacts or []}
    for ev in graph['evidence']:
        p = page_map.get(ev['source_page'])
        if ev.get('artifact_ref') and artifacts is not None and ev['artifact_ref'] not in artifact_map:
            findings.append(issue('source', 'Artifact reference is missing or belongs to another document', [ev.get('entity_id')], 'error'))
        artifact = artifact_map.get(ev.get('artifact_ref'))
        if artifact and artifact['page'] != ev['source_page']:
            findings.append(issue('source', 'Artifact and evidence page disagree', [ev.get('entity_id')], 'error'))
        if artifact and ev['method']=='vision' and not artifact['content_type'].startswith('image/'):
            findings.append(issue('source', 'Visual evidence requires an image artifact', [ev.get('entity_id')], 'error'))
        if ev['bbox'] and p and (Decimal(ev['bbox'][2]) > Decimal(str(p['width'])) or Decimal(ev['bbox'][3]) > Decimal(str(p['height']))):
            findings.append(issue('source', 'BBox exceeds PDF page dimensions', [ev.get('entity_id')], 'error'))
        fragment = ev.get('fragment')
        if ev['review'] == 'rejected':
            findings.append(issue('source', 'Rejected evidence needs replacement', [ev.get('entity_id')], 'needs_review', source_page=ev['source_page']))
        elif ev['method'] == 'vision' and ev['review'] == 'confirmed':
            continue
        elif ev['method'] == 'vision' or not fragment:
            findings.append(issue('source', 'Visual source requires human confirmation', [ev.get('entity_id')], 'needs_review', source_page=ev['source_page']))
        elif not p or not quote_normalize(fragment) or quote_normalize(fragment) not in quote_normalize(p['text']):
            findings.append(issue('source', 'Literal source fragment not found on indicated page', [ev.get('entity_id')], 'needs_review', source_page=ev['source_page'], source_fragment=fragment))
    for result in graph['results']:
        if result['source_fragment']:
            p = page_map.get(result['source_page'])
            if not p or not quote_normalize(result['source_fragment']) or quote_normalize(result['source_fragment']) not in quote_normalize(p['text']):
                findings.append(issue('source', 'Result fragment not textually confirmed', [result['result_id']], 'needs_review', source_page=result['source_page'], source_fragment=result['source_fragment']))
    return findings


def comparison_key(graph, r):
    if graph['domain_profile'] == 'rag-v1':
        lookup = lambda col, key, val: next((x for x in graph[col] if x[key] == val), {})
        dataset = lookup('datasets', 'dataset_id', r.get('dataset_id'))
        task = lookup('tasks', 'task_id', r.get('task_id'))
        exp = lookup('experiments', 'experiment_id', r.get('experiment_id'))
        return tuple([task.get('task_type'), dataset.get('dataset_name'), dataset.get('dataset_version'), dataset.get('data_split'),
                      r['metric_name'], r.get('metric_variant'), r['normalized_unit'], r.get('metric_k'), exp.get('evaluation_protocol'), r.get('aggregation')])
    device = next((x for x in graph['devices'] if x['device_id'] == r.get('device_id')), {})
    mat = next((x for x in graph['materials'] if x['material_id'] == device.get('absorber_material_id')), {})
    measurement = next((x for x in graph['measurements'] if x['measurement_id'] == r.get('measurement_id')), {})
    return tuple([mat.get('formula_normalized') or mat.get('material_name_raw'), device.get('device_type'), measurement.get('spectrum'),
                  measurement.get('light_intensity'), measurement.get('intensity_unit'), device.get('active_area'), device.get('area_definition'),
                  r.get('aggregation'), measurement.get('scan_direction'), measurement.get('certified'), measurement.get('stability_protocol'),
                  measurement.get('stress_conditions'), r.get('time_point'), r.get('time_unit'), r['metric_name'], r['normalized_unit']])


def scientific(graph):
    findings = []
    results = [r for r in graph['results'] if r['normalized_value'] is not None and r['result_origin'] == 'primary']
    if graph['domain_profile'] == 'solar-v1':
        groups = defaultdict(dict)
        for r in results:
            groups[(r['device_id'], r['measurement_id'], r['aggregation'], r['time_point'], r['time_unit'])].setdefault(r['metric_name'], []).append(r)
        for (device_id, measurement_id, *_), metrics in groups.items():
            measurement = next((m for m in graph['measurements'] if m['measurement_id'] == measurement_id), {})
            if all(k in metrics and len(metrics[k]) == 1 for k in ('PCE', 'Voc', 'Jsc', 'FF')):
                vals = {k: Decimal(metrics[k][0]['normalized_value']) for k in ('PCE', 'Voc', 'Jsc', 'FF')}
                pin = decimal_value(measurement.get('light_intensity'))
                if pin is not None and pin > 0 and measurement.get('intensity_unit') == 'mW/cm2' and vals['PCE'] > 0:
                    calc = 100 * vals['Voc'] * vals['Jsc'] * (vals['FF'] / 100) / pin
                    delta = abs(calc - vals['PCE']) / vals['PCE']
                    if delta > Decimal('.03'):
                        findings.append(issue('jv_consistency', 'PCE differs by more than 3% under the same measurement', [metrics[k][0]['result_id'] for k in vals], calculated=str(calc), reported=str(vals['PCE']), relative_difference=str(delta)))
                else:
                    findings.append(issue('jv_consistency', 'Missing explicit Pin or positive reported PCE', severity='skipped'))
            if 'Jsc' in metrics and 'Jsc_EQE' in metrics:
                jv, eqe = Decimal(metrics['Jsc'][0]['normalized_value']), Decimal(metrics['Jsc_EQE'][0]['normalized_value'])
                if jv and abs(eqe-jv)/abs(jv) > Decimal('.05'):
                    findings.append(issue('eqe_consistency', 'EQE and JV currents differ by more than 5%', [metrics['Jsc'][0]['result_id'], metrics['Jsc_EQE'][0]['result_id']], relative_difference=str(abs(eqe-jv)/abs(jv))))
            device = next((d for d in graph['devices'] if d['device_id'] == device_id), {})
            material = next((m for m in graph['materials'] if m['material_id'] == device.get('absorber_material_id')), {})
            eg = decimal_value(material.get('bandgap_value'))
            if eg is not None and material.get('bandgap_unit') == 'eV':
                for r in metrics.get('Voc', []):
                    if Decimal(r['normalized_value']) > eg:
                        findings.append(issue('voc_limit', 'Voc exceeds Eg/q for the linked absorber', [r['result_id']], voc=r['normalized_value'], eg=str(eg)))
        batches = defaultdict(dict)
        for r in results:
            if r['aggregation'] in ('mean', 'champion'):
                batches[(r['device_id'], r['measurement_id'], r['metric_name'], r['time_point'])][r['aggregation']] = r
        for pair in batches.values():
            if 'mean' in pair and 'champion' in pair and pair['mean']['metric_name'] in ('PCE', 'Voc', 'Jsc', 'FF'):
                if Decimal(pair['mean']['normalized_value']) > Decimal(pair['champion']['normalized_value']):
                    findings.append(issue('champion_vs_mean', 'Mean exceeds champion under the same batch/device and conditions', [pair['mean']['result_id'], pair['champion']['result_id']]))
        # EQE and JV normally have distinct measurement IDs. Compare only explicitly
        # matching device/aggregation/time and illumination, never an assumed Pin.
        measurements = {m['measurement_id']:m for m in graph['measurements']}
        for eqe in [r for r in results if r['metric_name']=='Jsc_EQE']:
            for jv in [r for r in results if r['metric_name']=='Jsc' and r['measurement_id'] != eqe['measurement_id']]:
                if any(eqe[k] != jv[k] for k in ('device_id','aggregation','time_point','time_unit')):
                    continue
                a,b = measurements.get(eqe['measurement_id'],{}), measurements.get(jv['measurement_id'],{})
                fields = ('spectrum','light_intensity','intensity_unit')
                if any(a.get(k) is None or b.get(k) is None or a[k] != b[k] for k in fields):
                    findings.append(issue('eqe_consistency', 'EQE/JV illumination comparability is unknown', [eqe['result_id'],jv['result_id']], 'skipped'))
                    continue
                v = Decimal(jv['normalized_value'])
                if v and abs(Decimal(eqe['normalized_value'])-v)/abs(v)>Decimal('.05'):
                    findings.append(issue('eqe_consistency', 'EQE/JV currents under explicit matching illumination differ by more than 5%',
                        [eqe['result_id'],jv['result_id']], relative_difference=str(abs(Decimal(eqe['normalized_value'])-v)/abs(v))))
        findings += [issue(r['rule'], 'Official definition is not supplied', severity='skipped', definition_status='awaiting_definition') for r in rules('solar-v1')['rules'] if r['status'] == 'awaiting_definition']
        for hi in [r for r in results if r['metric_name']=='HI']:
            formula='hi=(pce_reverse-pce_forward)/pce_reverse'
            cited_formula=re.sub(r'\s+','', (hi.get('note') or '')).casefold()
            source_formula=re.sub(r'\s+','', ' '.join([hi.get('source_fragment') or '']+
                [e.get('fragment') or '' for e in graph['evidence'] if e['entity_id']==hi['result_id']])).casefold()
            if formula not in cited_formula or formula not in source_formula:
                findings.append(issue('hysteresis_index','No supported explicit source formula; HI is not recalculated',[hi['result_id']],'skipped',definition_status='source_formula_required'))
                continue
            candidates={'forward':[],'reverse':[]}
            for pce in [r for r in results if r['metric_name']=='PCE']:
                if any(pce[k]!=hi[k] for k in ('device_id','aggregation','time_point','time_unit')):
                    continue
                measurement=measurements.get(pce['measurement_id'],{})
                direction=measurement.get('scan_direction')
                if direction in candidates:
                    candidates[direction].append((pce,measurement))
            if any(len(v)!=1 for v in candidates.values()):
                findings.append(issue('hysteresis_index','Unique matching forward/reverse PCE measurements are unavailable',[hi['result_id']],'skipped'))
                continue
            fwd,mf=candidates['forward'][0];rev,mr=candidates['reverse'][0]
            fields=('spectrum','light_intensity','intensity_unit')
            denominator=Decimal(rev['normalized_value'])
            if not denominator or any(mf.get(k) is None or mf[k]!=mr.get(k) for k in fields):
                findings.append(issue('hysteresis_index','Illumination comparability or a nonzero reverse PCE is unavailable',[hi['result_id']],'skipped'))
                continue
            calculated=100*(denominator-Decimal(fwd['normalized_value']))/denominator
            if calculated!=Decimal(hi['normalized_value']):
                findings.append(issue('hysteresis_index','HI differs from the explicitly sourced formula; rounding/tolerance requires review',
                    [hi['result_id'],fwd['result_id'],rev['result_id']],'needs_review',formula=formula,calculated_percent=str(calculated),reported_percent=hi['normalized_value']))
    else:
        for r in results:
            val = Decimal(r['normalized_value'])
            scale = {'fraction': Decimal(1), '%': Decimal(100)}.get(r['normalized_unit'])
            if scale is not None and not 0 <= val <= scale:
                findings.append(issue('metric_scale', 'Value outside explicitly declared scale', [r['result_id']], value=str(val), scale=str(scale)))
            suffix = re.search(r'@(\d+)$', r['metric_name'])
            if suffix and r.get('metric_k') is not None and int(suffix[1]) != r['metric_k']:
                findings.append(issue('metric_k', 'Metric name and explicit metric_k disagree', [r['result_id']]))
            if r['baseline_value'] is not None:
                key = comparison_key(graph, r)
                if any(key[i] is None for i in (0, 1, 3, 6, 8)):
                    findings.append(issue('baseline_comparability', 'Baseline protocol/scale/dataset/task insufficiently specified', [r['result_id']], 'needs_review'))
        by_metric = defaultdict(list)
        for r in results:
            by_metric[(r['dataset_id'], r['task_id'], r['metric_name'])].append(r)
        for group in by_metric.values():
            protocols = {comparison_key(graph, r)[8] for r in group}
            if len(protocols) > 1:
                findings.append(issue('protocol_mismatch', 'Evaluation protocols differ; results cannot be ranked together', [r['result_id'] for r in group]))
    duplicates = defaultdict(list)
    for r in results:
        local = (r.get('device_id'), r.get('measurement_id')) if graph['domain_profile'] == 'solar-v1' else (r.get('config_id'), r.get('experiment_id'))
        duplicates[(comparison_key(graph, r), local)].append(r)
    for group in duplicates.values():
        if len({r['normalized_value'] for r in group}) > 1:
            findings.append(issue('contradiction', 'Different values for the same semantic conditions', [r['result_id'] for r in group], values=[r['normalized_value'] for r in group]))
    return findings


def validate(graph, page_count=None, pages=None, artifacts=None):
    findings = structural(graph, page_count) + scientific(graph)
    if pages is not None:
        findings += source_checks(graph, pages, artifacts)
    return {'rules_version': RULES_VERSION, 'issues': findings,
            'structural_errors': sum(i['severity'] == 'error' for i in findings)}
