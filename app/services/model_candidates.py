"""Conservative machine-only repairs; original provider responses remain in progress.outputs."""
import copy
from decimal import Decimal, InvalidOperation
from pydantic import Field, create_model
from app.domain import Error, quote_normalize
from app.profiles import GRAPHS, ENTITIES
from app.schemas.graphs import Strict, Identifier
from app.services.validation import structural, machine_graph, caption_index, caption_page


class RemovedRecord(Strict):
    id: Identifier
    reason: str = Field(min_length=1)


REPAIR_SCHEMAS = {profile: create_model('Repair_' + profile.replace('-', '_'), __base__=Strict,
    graph=(graph, ...), removed_entities=(list[RemovedRecord], []), removed_evidence=(list[RemovedRecord], []))
    for profile, graph in GRAPHS.items()}


def apply_graph_repair(previous, value):
    """Merge explicit upserts/deletions. Omitted facts cannot vanish during repair."""
    from app.services.pipeline import merge_extraction_graph
    if not isinstance(value, dict) or not isinstance(value.get('graph'), dict):
        raise Error(422, 'invalid_model_output', 'Repair envelope must contain a graph object')
    graph = machine_graph(value['graph'])
    patch = REPAIR_SCHEMAS[previous['domain_profile']].model_validate({**value, 'graph': graph}).model_dump(mode='json')
    base = copy.deepcopy(previous)
    collections = [(collection, key) for profile, collection, key, _ in ENTITIES.values()
                   if profile == previous['domain_profile']]
    for field, pairs in [('removed_entities', collections), ('removed_evidence', [('evidence', 'evidence_id')])]:
        known = {r[key] for collection, key in pairs for r in base[collection]}
        if field == 'removed_entities':
            # Idempotent removal of an orphan named by existing evidence is safe too.
            known.update(e['entity_id'] for e in base['evidence'] if e.get('entity_id'))
        updated = {r[key] for collection, key in pairs for r in graph[collection]}
        removed = {r['id'] for r in patch[field]}
        if not removed <= known or removed & updated:
            raise Error(422, 'invalid_candidate', 'Repair deletion must reference an existing record without an upsert')
        for collection, key in pairs:
            base[collection] = [r for r in base[collection] if r[key] not in removed]
    return merge_extraction_graph(base, graph)


def machine_sources(value, pages, artifacts, changes):
    value = copy.deepcopy(value)
    page_map = {p['number']: p for p in pages}
    artifact_map = {a['id']: a for a in artifacts}
    captions = caption_index(pages)
    for ev in value.get('evidence', []):
        caption = caption_page(captions, ev.get('figure'), ev.get('table')) if ev.get('method') == 'vision' else None
        if caption is not None and caption != ev.get('source_page'):
            changes.append({'evidence_id': ev.get('evidence_id'), 'field': 'source_page', 'original': ev.get('source_page'),
                            'replacement': caption, 'reason': 'Unique PDF figure/table caption locates the visual source'})
            ev['source_page'] = caption
            ev['review'] = 'needs_review'
        page = page_map.get(ev.get('source_page'))
        if not page:
            continue
        artifact = artifact_map.get(ev.get('artifact_ref'))
        # Resolve localization against the declared PDF page, never another document.
        if (ev.get('artifact_ref') or ev.get('method') == 'vision') and (not artifact or artifact['page'] != page['number'] or
                (ev.get('method') == 'vision' and not artifact['content_type'].startswith('image/'))):
            renders = [a for a in artifacts if a['page'] == page['number'] and a['kind'] == 'page']
            if renders:
                changes.append({'evidence_id': ev.get('evidence_id'), 'field': 'artifact_ref',
                                'original': ev.get('artifact_ref'), 'replacement': renders[0]['id'],
                                'reason': 'Use the actual render of the declared source page; localization needs review'})
                ev['artifact_ref'] = renders[0]['id']
                ev['review'] = 'needs_review'
        bbox = ev.get('bbox')
        try:
            invalid = bbox and (len(bbox) != 4 or min(map(Decimal, map(str, bbox))) < 0 or
                Decimal(str(bbox[2])) > Decimal(str(page['width'])) or
                Decimal(str(bbox[3])) > Decimal(str(page['height'])) or
                Decimal(str(bbox[2])) <= Decimal(str(bbox[0])) or Decimal(str(bbox[3])) <= Decimal(str(bbox[1])))
        except (InvalidOperation, TypeError, ValueError):
            invalid = True
        if invalid:
            changes.append({'evidence_id': ev.get('evidence_id'), 'field': 'bbox', 'original': bbox,
                            'replacement': None, 'reason': 'Invalid PDF coordinates; no guessed crop'})
            ev['bbox'] = None
            ev['review'] = 'needs_review'
        artifact = artifact_map.get(ev.get('artifact_ref'))
        if ev.get('method') == 'vision' and not (ev.get('table') or ev.get('figure') or ev.get('bbox')) and artifact and artifact['page'] == page['number'] and artifact['content_type'].startswith('image/'):
            ev['bbox'] = [0, 0, page['width'], page['height']]
            ev['review'] = 'needs_review'
            changes.append({'evidence_id': ev.get('evidence_id'), 'field': 'bbox', 'replacement': ev['bbox'],
                            'reason': 'Only the source page is localized; exact region needs review'})
        fragment = ev.get('fragment')
        if ev.get('method') == 'vision' and fragment and quote_normalize(fragment) not in quote_normalize(page.get('text') or ''):
            ev['reading_method'] = (ev.get('reading_method') or 'Visual reading') + '\nОписание модели, не цитата: ' + fragment
            ev['fragment'] = None
            ev['review'] = 'needs_review'
            changes.append({'evidence_id': ev.get('evidence_id'), 'field': 'fragment', 'original': fragment,
                            'replacement': None, 'reason': 'Visual paraphrase preserved as reading description, not a literal quote'})
    for row in value.get('results', []):
        caption = caption_page(captions, row.get('source_figure'), row.get('source_table'))
        page = page_map.get(row.get('source_page'))
        fragment = row.get('source_fragment')
        normalized_fragment = quote_normalize(fragment or '')
        literal = normalized_fragment and page and normalized_fragment in quote_normalize(page.get('text') or '')
        if caption is not None and caption != row.get('source_page') and not literal:
            changes.append({'result_id': row.get('result_id'), 'field': 'source_page', 'original': row.get('source_page'),
                            'replacement': caption, 'reason': 'Unique PDF caption locates result; a literal body quotation would retain its own page'})
            row['source_page'] = caption
    return value


def repair_duplicate_links(graph, changes):
    """An invalid deduplication hint must not discard or conflate scientific rows."""
    rows = {r['result_id']: r for r in graph['results']}
    for finding in structural(graph):
        if finding['description'] not in ('Duplicates must have the same semantic conditions and normalized value',
                                         'Duplicate self-link or cycle'):
            continue
        for rid in finding['record_ids']:
            row = rows[rid]
            if row.get('duplicate_of'):
                changes.append({'result_id': rid, 'field': 'duplicate_of', 'original': row['duplicate_of'],
                                'replacement': None, 'reason': finding['description']})
                row['duplicate_of'] = None
    return graph
