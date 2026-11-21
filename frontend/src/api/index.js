// Boundary adapters keep the uploaded Vue views independent of server DTOs.
import { http, upload, download, newIdempotencyKey, tokens } from './http.js'
import { normalizeCorpus, normalizeGraph, normalizeClassification, normalizeDocument, normalizeJob, normalizeIssue, normalizeProfile, normalizeResult, decodeRecord, comparisonConditions } from './adapters.js'

const enc = encodeURIComponent
const contexts = new Map()
const profiles = new Map()
const issueTags = new Map()
export const asList = data => Array.isArray(data) ? { items: data, total: data.length } : { ...data, items: data?.items || [], total: data?.total || 0 }
async function all(path, query = {}) {
  const first = asList((await http.get(path, { query: { ...query, page: 1, page_size: 200 } })).data)
  for (let page = 2; first.items.length < first.total; page++) {
    const next = asList((await http.get(path, { query: { ...query, page, page_size: 200 } })).data)
    if (!next.items.length) break
    first.items.push(...next.items)
  }
  return first
}
const invalidate = () => contexts.clear()
async function context(id) {
  const key = `${tokens.access}:${id}`
  const cached = contexts.get(key)
  if (cached && Date.now() - cached.at < 1200) return cached.promise
  const promise = Promise.all(['documents', 'publications', 'issues', 'jobs'].map(p => all(`/corpora/${enc(id)}/${p}`))).then(([docs, pubs, issues, jobs]) => ({ docs: docs.items, pubs: pubs.items, issues: issues.items, jobs: jobs.items.sort((a, b) => b.created_at.localeCompare(a.created_at)) }))
  contexts.set(key, { at: Date.now(), promise })
  promise.catch(() => contexts.delete(key))
  return promise
}
export function snippetParts(snippet) {
  if (Array.isArray(snippet)) return snippet
  return String(snippet || '').split(/(<mark>.*?<\/mark>)/gs).filter(Boolean).map(t => ({ text: t.startsWith('<mark>') ? t.slice(6, -7) : t, hit: t.startsWith('<mark>') }))
}
export const auth = {
  login: async (email, password) => { invalidate(); return (await http.post('/auth/login', { email, password }, { auth: false })).data },
  logout: async token => { try { return await http.post('/auth/logout', { refresh_token: token }, { auth: false }) } finally { invalidate(); issueTags.clear() } },
  logoutAll: async () => { try { return await http.post('/auth/logout-all') } finally { invalidate(); issueTags.clear() } },
  me: async () => { const r = (await http.get('/auth/me')).data; return { ...r, is_active: r.is_active ?? r.active } },
  changePassword: (old_password, new_password) => http.post('/auth/change-password', { old_password, new_password })
}
export const reference = {
  processing: async () => { const c = (await http.get('/processing/configuration')).data; return { ...c, limits: { ...c.limits, max_file_mb: c.limits.max_pdf_bytes / 1048576, max_pages: c.limits.max_pdf_pages } } },
  profiles: async () => (await all('/domain-profiles')).items.map(p => ({ ...p, id: p.domain_profile })),
  profile: async id => { const p = normalizeProfile((await http.get(`/domain-profiles/${enc(id)}`)).data); profiles.set(id, p); return p },
  rules: async id => (await http.get(`/domain-profiles/${enc(id)}/rules`)).data.rules
}
export const corpora = {
  list: async () => { const list = await all('/corpora'); return { ...list, items: list.items.map(normalizeCorpus).reverse() } },
  get: async id => normalizeCorpus((await http.get(`/corpora/${enc(id)}`)).data),
  create: async body => { invalidate(); return normalizeCorpus((await http.post('/corpora', body)).data) },
  update: async (id, body) => { invalidate(); return normalizeCorpus((await http.patch(`/corpora/${enc(id)}`, body)).data) },
  archive: async id => { const r = await http.post(`/corpora/${enc(id)}/archive`); invalidate(); return normalizeCorpus(r.data) }
}
async function decoratedDocs(c) {
  const processing = c.jobs.filter(j => ['process', 'classify'].includes(j.kind))
  const latestItems = new Map()
  // Read each document's latest attempt, including documents absent from recent jobs.
  for (const job of processing) {
    if (c.docs.every(d => latestItems.has(d.id))) break
    for (const item of (await all(`/jobs/${enc(job.id)}/items`)).items) if (!latestItems.has(item.document_id)) latestItems.set(item.document_id, item)
  }
  return Promise.all(c.docs.map(async doc => {
    const history = doc.classification_id ? await documents.classifications(doc.id) : null
    return normalizeDocument(doc, c, history?.current, latestItems.get(doc.id))
  }))
}
export const documents = {
  list: async id => { const c = await context(id); const items = await decoratedDocs(c); return { items, total: items.length } },
  get: async id => { const doc = (await http.get(`/documents/${enc(id)}`)).data; const c = await context(doc.corpus_id); return (await decoratedDocs({ ...c, docs: [doc] }))[0] },
  upload: async (id, file, code, onProgress) => { const fd = new FormData(); fd.append('file', file, file.name); fd.append('publication_code', code); const r = await upload(`/corpora/${enc(id)}/documents`, fd, { onProgress }); invalidate(); return { ...r.data, _duplicate: r.status === 200 } },
  update: async (id, body) => { await http.patch(`/documents/${enc(id)}`, body); invalidate(); return documents.get(id) },
  file: async id => (await http.get(`/documents/${enc(id)}/file`, { as: 'arrayBuffer' })).data,
  pages: async id => (await all(`/documents/${enc(id)}/pages`)).items.map(p => ({ ...p, page: p.number })),
  pageText: async (id, page) => (await http.get(`/documents/${enc(id)}/pages/${page}/text`)).data,
  classifications: async id => { const r = await all(`/documents/${enc(id)}/classifications`); return { current: normalizeClassification(r.items.find(c => c.id === r.current_revision_id)), history: r.items.map(normalizeClassification) } },
  reviewClassification: async (id, body) => {
    const history = await documents.classifications(id)
    const previous = history.history.find(r => r.id === body.expected_revision)?.decision || history.current?.decision
    const decision = { ...previous, labels: body.labels, outcome: body.labels.length ? 'resolved' : 'outside', confidence: 1 }
    for (const label of ['solar', 'rag']) decision[label] = { in_scope: body.labels.includes(label) ? body.scope[`${label}-v1`] : false, exclusion_reason: body.labels.includes(label) && body.scope[`${label}-v1`] ? null : body.reason }
    const r = await http.post(`/documents/${enc(id)}/classifications/review`, { expected_revision: body.expected_revision, decision, reason: body.reason, replace_reviewed: body.replace_reviewed })
    invalidate(); return r.data
  }
}
async function jobDetails(job) {
  const [detail, list] = await Promise.all([http.get(`/jobs/${enc(job.id)}`), all(`/jobs/${enc(job.id)}/items`)])
  return normalizeJob(detail.data, list.items)
}
export const jobs = {
  list: async (id, query = {}) => { const r = await all(`/corpora/${enc(id)}/jobs`); const rows = r.items.filter(j => !query.kind || query.kind === j.kind).sort((a, b) => b.created_at.localeCompare(a.created_at)); return { ...r, items: rows.map(j => normalizeJob(j)) } },
  get: async id => jobDetails({ id }),
  items: async id => { const r = await all(`/jobs/${enc(id)}/items`); const job = (await http.get(`/jobs/${enc(id)}`)).data; const c = await context(job.corpus_id); return r.items.map(i => ({ ...i, publication_code: c.docs.find(d => d.id === i.document_id)?.publication_code, error: i.error ? { message: i.error } : null })) },
  create: async (id, body, key = newIdempotencyKey()) => { const input = { ...body }; if (!input.document_ids?.length && !input.all_documents) input.all_documents = true; const r = await http.post(`/corpora/${enc(id)}/jobs`, input, { idempotencyKey: key }); invalidate(); return r.data },
  cancel: async id => { const r = await http.post(`/jobs/${enc(id)}/cancel`); invalidate(); return r.data },
  retry: async id => { const r = await http.post(`/jobs/${enc(id)}/retry`, undefined, { idempotencyKey: newIdempotencyKey() }); invalidate(); return r.data },
  report: async id => (await http.get(`/jobs/${enc(id)}/report`)).data,
  passport: async id => {
    const raw = (await http.get(`/jobs/${enc(id)}/passport`)).data
    return { profiles: Object.entries(raw).map(([profile, p]) => { const schema = normalizeProfile(p); return { profile, tables: Object.entries(p.csv).map(([name, columns]) => { const entity = schema.entities.find(e => e.type === ({ materials: 'material', devices: 'device', layers: 'layer', measurements: 'measurement', results: profile === 'solar-v1' ? 'solar_result' : 'rag_result', configurations: 'configuration', datasets: 'dataset', tasks: 'task', experiments: 'experiment' })[name]); return { file: `${name}.csv`, id_field: entity?.id_field || (name === 'issues' ? 'issue_id' : 'publication_id'), fields: columns.map(col => { const f = entity?.fields.find(x => x.name === col); return { name: col, type: f?.valueType || 'string', required: f?.required, vocabulary: f?.vocab, references: f?.ref } }) } }) } }) }
  },
  download: (id, name) => download(`/jobs/${enc(id)}/download`, name || `science-extract-${id}.zip`)
}
async function graphResponse(request) { const r = await request; invalidate(); return { ...r, data: normalizeGraph(r.data) } }
async function entityBody(type, body) { const p = profiles.get(body.profile) || await reference.profile(body.profile); return { record: decodeRecord(body.values, p.entities.find(e => e.type === type)), reason: body.reason } }
export const publications = {
  list: (id, query) => all(`/corpora/${enc(id)}/publications`, query),
  get: async id => { const p = (await http.get(`/publications/${enc(id)}`)).data; const doc = (await http.get(`/documents/${enc(p.document_id)}`)).data; return { ...p, publication_code: doc.publication_code, bibliography: { ...p.profiles[0]?.bibliography, doi: p.profiles[0]?.bibliography?.DOI }, profiles: Object.fromEntries(p.profiles.map(x => [x.domain_profile, { ...x, active_revision_id: x.revision_id, in_scope: x.scope.in_scope }])) } },
  graph: (id, profile, revision) => graphResponse(http.get(`/publications/${enc(id)}/graph`, { query: { profile, revision } })),
  versions: async (id, profile) => { const rows = (await all(`/publications/${enc(id)}/versions`, { profile })).items; const active = rows.find(v => v.active); return rows.map(v => ({ ...v, status: v.active ? 'active' : v.origin === 'machine' && v.number > (active?.number || 0) ? 'candidate' : 'previous', origin: v.origin === 'machine' ? 'model' : 'manual', author_name: v.author_id })).reverse() },
  activate: async (id, revision, profile, etag, reason) => { await http.post(`/publications/${enc(id)}/versions/${enc(revision)}/activate`, { reason }, { ifMatch: etag, query: { profile } }); return publications.graph(id, profile) },
  exclude: (id, profile, reason, etag) => graphResponse(http.post(`/publications/${enc(id)}/exclude`, { reason }, { ifMatch: etag, query: { profile } })),
  audit: async id => (await all(`/publications/${enc(id)}/audit`)).items.map(a => ({ ...a, at: a.created_at, author_name: a.author_id })),
  evidence: async (id, query) => (await all(`/publications/${enc(id)}/evidence`, query)).items.map(e => ({ ...e, page: e.source_page })),
  addEvidence: (id, body, etag) => { const { profile, reason, ...record } = body; return graphResponse(http.post(`/publications/${enc(id)}/evidence`, record, { ifMatch: etag, query: { profile, reason } })) },
  reviewEvidence: (id, evidenceId, body, etag) => graphResponse(http.post(`/publications/${enc(id)}/evidence/${enc(evidenceId)}/review`, { review: body.decision, reason: body.reason }, { ifMatch: etag, query: { profile: body.profile } })),
  createEntity: async (id, type, body, etag) => graphResponse(http.post(`/publications/${enc(id)}/entities/${enc(type)}`, await entityBody(type, body), { ifMatch: etag })),
  updateEntity: async (id, type, entityId, body, etag) => graphResponse(http.patch(`/publications/${enc(id)}/entities/${enc(type)}/${enc(entityId)}`, await entityBody(type, body), { ifMatch: etag })),
  deleteEntity: (id, type, entityId, body, etag) => graphResponse(http.del(`/publications/${enc(id)}/entities/${enc(type)}/${enc(entityId)}`, { body: { reason: body.reason }, ifMatch: etag }))
}
export const catalog = {
  results: async (id, query = {}) => {
    const { q, order, has_issues, sort, ...filters } = query
    if (has_issues) filters.issues = has_issues
    const [r, c] = await Promise.all([all(`/corpora/${enc(id)}/results`, { ...filters, sort: ['result_id', 'metric_value', 'year'].includes(sort) ? sort : 'result_id' }), context(id)])
    let rows = r.items.map(row => normalizeResult(row, c))
    const metrics = [...new Set(rows.map(row => row.metric_name))]
    if (q) rows = rows.filter(row => `${row.publication_code} ${row.title} ${row.metric_name} ${row.result_id}`.toLocaleLowerCase().includes(q.toLocaleLowerCase()))
    if (sort) rows.sort((a, b) => sort === 'metric_value' ? Number(a[sort]) - Number(b[sort]) : String(a[sort] ?? '').localeCompare(String(b[sort] ?? ''), 'ru', { numeric: true }))
    if (order === 'desc') rows.reverse()
    return { items: rows, total: rows.length, facets: { metrics } }
  },
  search: async (id, query) => { const [r, c] = await Promise.all([all(`/corpora/${enc(id)}/search`, query), context(id)]); return { ...r, items: r.items.map(row => ({ ...row, publication_code: c.docs.find(d => d.id === row.document_id)?.publication_code, title: c.docs.find(d => d.id === row.document_id)?.display_name, snippet: snippetParts(row.snippet), kind: row.page ? 'text' : 'metadata' })) } },
  compare: async (id, body) => {
    const [r, results] = await Promise.all([http.post(`/corpora/${enc(id)}/comparisons`, { profile: body.profile, results: body.result_refs }), catalog.results(id, { profile: body.profile })])
    const full = ref => results.items.find(x => x.publication_id === ref.publication_id && x.result_id === ref.result_id) || ref
    return { ...r.data, groups: r.data.groups.map((g, i) => ({ ...g, key: String(i), conditions: comparisonConditions(g.conditions), results: g.results.map(full) })), excluded: r.data.excluded.map(x => ({ ...full(x.ref), ...x })) }
  },
  issues: async (id, query = {}) => { const { status, publication_id, ...filters } = query; const [r, c] = await Promise.all([all(`/corpora/${enc(id)}/issues`, { ...filters, review: status, publication: publication_id }), context(id)]); const items = r.items.map(i => normalizeIssue(i, c)); items.forEach(i => issueTags.set(i.id, i._etag)); return { ...r, items, skipped: [] } },
  issue: async id => { const r = await http.get(`/issues/${enc(id)}`); issueTags.set(id, r.etag); return normalizeIssue(r.data) },
  reviewIssue: async (id, body, etag = issueTags.get(id)) => { if (!etag) throw new Error('Обновите замечание перед изменением'); const r = await http.patch(`/issues/${enc(id)}`, { review: body.status, reason: body.reason || 'Возвращено на проверку' }, { ifMatch: etag }); issueTags.set(id, r.etag); invalidate(); return normalizeIssue(r.data) },
  reviewItems: async (id, query) => { const [r, c] = await Promise.all([all(`/corpora/${enc(id)}/review-items`, query), context(id)]); return { ...r, items: r.items.map((it, i) => { const pub = c.pubs.find(p => p.id === it.publication_id); const doc = c.docs.find(d => d.id === (it.document_id || pub?.document_id)); return { ...it, id: `${it.kind}:${it.revision_id || it.entity_id || i}`, document_id: doc?.id, publication_code: doc?.publication_code, title: doc?.display_name, summary: it.kind === 'classification' ? 'Проверьте тему статьи' : it.kind === 'candidate' ? 'Сравните новую версию с активной' : 'Проверьте извлечённые данные' } }) } }
}
