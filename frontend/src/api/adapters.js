import { ID_FIELD, RESULT_ENTITY, fieldLabel } from '../lib/labels.js'

export const COLLECTIONS = { material: 'materials', device: 'devices', layer: 'layers', measurement: 'measurements', solar_result: 'results', configuration: 'configurations', dataset: 'datasets', task: 'tasks', experiment: 'experiments', rag_result: 'results' }
const entityTypes = profile => profile === 'solar-v1' ? ['material', 'device', 'layer', 'measurement', 'solar_result'] : ['configuration', 'dataset', 'task', 'experiment', 'rag_result']
export const normalizeCorpus = c => ({ ...c, status: c.archived ? 'archived' : 'active', updated_at: c.updated_at || c.created_at })
export const normalizeEvidence = e => ({ ...e, page: e.source_page, bbox: e.bbox?.map(Number), review_status: e.review === 'open' ? 'pending' : e.review })
export function normalizeGraph(data) {
  const graph = data.graph || data
  return { ...graph, revision_id: data.revision_id, revision_number: data.revision_number, entities: Object.fromEntries(entityTypes(graph.domain_profile).map(t => [t, graph[COLLECTIONS[t]] || []])), evidence: (graph.evidence || []).map(normalizeEvidence) }
}
export function normalizeClassification(row) {
  if (!row) return null
  const d = row.decision
  return { ...row, ...d, revision_id: row.id, origin: row.reviewed ? 'manual' : 'model', scores: { solar: d.labels.includes('solar') ? d.confidence : null, rag: d.labels.includes('rag') ? d.confidence : null }, scope: { 'solar-v1': d.solar.in_scope, 'rag-v1': d.rag.in_scope }, evidence: (d.evidence || []).map(normalizeEvidence) }
}
export function normalizeIssue(i, ctx = {}) {
  const pub = ctx.pubs?.find(p => p.id === i.publication_id)
  const doc = ctx.docs?.find(d => d.id === pub?.document_id)
  return { ...i, ...i.details, description: i.details.description || i.details.message || i.rule, status: i.review, review: i.details.review || null, record_ids: i.details.record_ids || [], document_id: doc?.id, publication_code: doc?.publication_code, title: doc?.display_name, stale: !!pub && pub.current[i.profile] !== i.revision_id, _etag: `"${i.details.review_revision || i.id}"` }
}
export function normalizeDocument(doc, ctx, classification, item) {
  const pub = ctx.pubs.find(p => p.document_id === doc.id)
  const cls = normalizeClassification(classification)
  const hasActiveGraph = Object.keys(pub?.current || {}).length > 0
  let status = cls?.outcome === 'outside' ? 'outside' : cls?.outcome === 'unreadable' ? 'unreadable' : cls?.outcome === 'needs_review' ? 'needs_review' : hasActiveGraph ? 'ready' : 'uploaded'
  if (cls?.outcome === 'resolved' && cls.labels.length && cls.labels.every(l => cls[l]?.in_scope === false)) status = 'excluded'
  if (item) {
    if (item.status === 'running') status = 'processing'
    else if (item.status === 'queued') status = 'queued'
    else if (item.status === 'waiting_review') status = 'needs_review'
    else if (item.status === 'failed' && !hasActiveGraph) status = 'failed'
    else if (item.status === 'blocked_external_configuration' && !hasActiveGraph) status = 'blocked'
  }
  return { ...doc, size_bytes: doc.byte_size, title: cls?.bibliography?.title || doc.display_name, publication_id: pub?.id, classification: cls, status, status_hint: status === 'blocked' ? processingErrorMessage(item.error) : null, issues_open: ctx.issues.filter(i => i.publication_id === pub?.id && i.review === 'open' && pub?.current[i.profile] === i.revision_id).length, processing: item ? { ...item, error: item.error ? { message: processingErrorMessage(item.error) } : null, progress: { ...item.progress, done: item.progress?.done ?? item.progress?.pages_done } } : null }
}
export function processingErrorMessage(error) {
  if (/OPENAI_API_KEY is not configured/.test(error || '')) return 'При запуске задания API-ключ ещё не был настроен. Повторите обработку.'
  if (/access unavailable|HTTP (401|403|404)/.test(error || '')) return 'В этой попытке сервис модели отказал в доступе. Проверьте ключ и повторите обработку.'
  if (error === 'invalid_candidate') return 'Извлечённые данные не прошли проверку связей. Повторите обработку.'
  if (error === 'provider_rejected') return 'Сервис модели отклонил запрос. Повторите обработку после исправления настроек.'
  return 'Предыдущая попытка обработки остановлена. Подробности доступны в задании.'
}
export function normalizeJob(job, items = []) {
  const counters = { ...(job.counters || {}) }
  if (items.length) for (const state of new Set(items.map(i => i.status))) counters[state] = items.filter(i => i.status === state).length
  counters.total = Object.entries(counters).reduce((n, [k, v]) => n + (k === 'total' ? 0 : v), 0)
  counters.blocked = counters.blocked_external_configuration || 0
  const running = items.find(i => i.status === 'running')
  const target_profiles = job.input?.target_profiles || job.result?.manifest?.profiles || []
  const manifest = job.result?.manifest
  const files = manifest ? target_profiles.flatMap(p => Object.keys(job.result.passport?.[p]?.csv || {}).map(name => `${target_profiles.length > 1 ? p + '/' : ''}submission/${name}.csv`).concat(['data_passport.json', 'manifest.json', 'validation_report.json'].map(name => `${target_profiles.length > 1 ? p + '/' : ''}submission/${name}`))) : []
  return { ...job, options: job.input, target_profiles, result: { ...job.result, file_name: `science-extract-${job.id}.zip`, files, documents: manifest?.documents?.length, gaps: manifest?.omissions || [] }, counters, stage: running?.stage || (job.kind === 'export' ? 'export' : job.kind === 'validate' ? 'validate' : null), error: typeof job.error === 'string' ? { message: job.error } : job.error }
}
export function normalizeProfile(passport) {
  const schema = passport.fields
  const defs = schema.$defs || {}
  const resolve = f => f?.$ref ? defs[f.$ref.split('/').pop()] : f
  const entities = entityTypes(passport.domain_profile).map(type => {
    const model = resolve(schema.properties[COLLECTIONS[type]].items)
    const fields = Object.entries(model.properties).map(([name, original]) => {
      const choices = original.anyOf || [original]
      const s = resolve(choices.find(x => x.type !== 'null')) || {}
      const multiple = s.type === 'array'
      const inner = multiple ? resolve(s.items) : s
      const vocab = inner?.enum
      const ref = Object.keys(ID_FIELD).find(t => ID_FIELD[t] === name && t !== type && !t.endsWith('_result'))
      const kind = s.type === 'boolean' ? 'boolean' : s.type === 'integer' ? 'integer' : choices.some(x => x.type === 'number') ? 'number' : name.endsWith('fragment') || name === 'note' ? 'text' : 'string'
      return { name, type: vocab ? 'enum' : ref ? 'ref' : kind, valueType: kind, multiple, vocab, ref, required: (model.required || []).includes(name), nullable: choices.some(x => x.type === 'null'), schema: original }
    })
    return { type, id_field: ID_FIELD[type], fields }
  })
  return { ...passport, id: passport.domain_profile, entities }
}
export function decodeRecord(values, schema) {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => {
    const f = schema?.fields.find(x => x.name === key)
    if (value == null || value === '') return [key, null]
    if (f?.multiple) return [key, Array.isArray(value) ? value : String(value).split(';').map(v => v.trim()).filter(Boolean)]
    if (f?.valueType === 'boolean') return [key, value === true || value === 'true']
    if (f?.valueType === 'integer') return [key, Number(value)]
    return [key, value]
  }))
}
export function normalizeResult(r, ctx) {
  const pub = ctx.pubs.find(p => p.id === r.publication_id)
  const doc = ctx.docs.find(d => d.id === pub?.document_id)
  return { ...r, document_id: doc?.id, publication_code: doc?.publication_code, title: doc?.display_name, profile: r.domain_profile, origin: r.result_origin, issues_open: r.has_issues ? 1 : 0, context: r, source: { page: r.source_page, table: r.source_table, figure: r.source_figure } }
}
export const comparisonConditions = values => values.map((value, i) => ({ field: `condition_${i}`, value: Array.isArray(value) ? value.join(', ') : value === null ? 'не указано' : String(value) }))
