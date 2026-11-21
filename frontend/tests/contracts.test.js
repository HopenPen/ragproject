import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeGraph, normalizeClassification, normalizeIssue, decodeRecord } from '../src/api/adapters.js'
import { metricParts, fmtResult } from '../src/lib/format.js'
import { http, setTokens, clearTokens } from '../src/api/http.js'
import { publications, catalog } from '../src/api/index.js'

globalThis.window = { location: { origin: 'http://localhost' } }

test('server graphs retain source coordinates, nulls, precision and Recall@0', () => {
  const graph = normalizeGraph({ revision_id: 'revision-1', graph: { domain_profile: 'rag-v1', bibliography: {}, results: [{ result_id: 'R1', metric_name: 'Recall', metric_k: 0, metric_value: '0.7000', metric_unit: 'fraction', normalized_value: null }], evidence: [{ evidence_id: 'E1', entity_id: 'R1', source_page: 7, bbox: ['10.5', '20', '90', '30'], fragment: 'Recall@0 = 0.7000', review: 'open' }] } })
  assert.equal(graph.entities.rag_result[0].metric_value, '0.7000')
  assert.equal(graph.entities.rag_result[0].normalized_value, null)
  assert.deepEqual(graph.evidence[0].bbox, [10.5, 20, 90, 30])
  assert.equal(graph.evidence[0].page, 7)
  assert.equal(graph.evidence[0].review_status, 'pending')
  assert.deepEqual(metricParts('Recall', 0), [{ text: 'Recall' }, { text: '@0' }])
  assert.match(fmtResult({ metric_value: 0, metric_unit: '%' }), /^0/)
})

test('manual classification retains accepted revision and independent profile scope', () => {
  const c = normalizeClassification({ id: 'rev-3', reviewed: true, decision: { labels: ['solar', 'rag'], outcome: 'resolved', confidence: 1, solar: { in_scope: false }, rag: { in_scope: true }, evidence: [] } })
  assert.equal(c.revision_id, 'rev-3')
  assert.equal(c.origin, 'manual')
  assert.deepEqual(c.scope, { 'solar-v1': false, 'rag-v1': true })
})

test('an issue on an inactive revision stays visibly stale', () => {
  const issue = normalizeIssue({ id: 'I1', publication_id: 'P1', profile: 'solar-v1', revision_id: 'old', review: 'open', details: { record_ids: ['R1'], review_revision: 'review-2', description: 'Mismatch' } }, { pubs: [{ id: 'P1', current: { 'solar-v1': 'new' } }] })
  assert.equal(issue.stale, true)
  assert.equal(issue._etag, '"review-2"')
  assert.equal(issue.description, 'Mismatch')
})

test('schema based form values preserve decimal precision, false and reference arrays', () => {
  const schema = { fields: [{ name: 'device_id', multiple: true }, { name: 'certified', valueType: 'boolean' }, { name: 'metric_k', valueType: 'integer' }] }
  assert.deepEqual(decodeRecord({ device_id: 'D1; D2', certified: 'false', metric_k: '0', metric_value: '22.000', note: null }, schema), { device_id: ['D1', 'D2'], certified: false, metric_k: 0, metric_value: '22.000', note: null })
})

test('parallel 401 responses rotate the refresh token exactly once', async () => {
  const previous = globalThis.fetch
  let rotations = 0
  setTokens({ access_token: 'expired', refresh_token: 'refresh-old' })
  globalThis.fetch = async (url, init) => {
    if (url.endsWith('/auth/refresh')) {
      rotations++
      await new Promise(resolve => setTimeout(resolve, 20))
      return Response.json({ access_token: 'fresh', refresh_token: 'refresh-new', expires_in: 900 })
    }
    return init.headers.Authorization === 'Bearer fresh' ? Response.json({ ok: true }) : Response.json({ error: { code: 'expired' } }, { status: 401 })
  }
  try {
    const values = await Promise.all([http.get('/one'), http.get('/two')])
    assert.equal(rotations, 1)
    assert.ok(values.every(v => v.data.ok))
  } finally { globalThis.fetch = previous; clearTokens() }
})

test('evidence and entity edits send exact server bodies and the displayed ETag', async () => {
  const previous = globalThis.fetch
  const captured = []
  globalThis.fetch = async (url, init) => { captured.push({ url, init }); return Response.json(url.includes('/issues/') ? { id: 'I1', review: 'dismissed', details: {} } : { domain_profile: 'rag-v1', revision_id: 'new', graph: { domain_profile: 'rag-v1', results: [], evidence: [] } }, { headers: { ETag: '"new"' } }) }
  try {
    await publications.reviewEvidence('P1', 'E1', { profile: 'rag-v1', decision: 'confirmed', reason: 'Checked PDF' }, '"old"')
    await publications.deleteEntity('P1', 'rag_result', 'R1', { profile: 'rag-v1', reason: 'Duplicate' }, '"old"')
    assert.equal(new URL(captured[0].url).searchParams.get('profile'), 'rag-v1')
    assert.deepEqual(JSON.parse(captured[0].init.body), { review: 'confirmed', reason: 'Checked PDF' })
    assert.equal(captured[0].init.headers['If-Match'], '"old"')
    assert.equal(captured[1].init.method, 'DELETE')
    assert.deepEqual(JSON.parse(captured[1].init.body), { reason: 'Duplicate' })
    assert.equal(captured[1].init.headers['If-Match'], '"old"')
    await catalog.reviewIssue('I1', { status: 'dismissed', reason: 'Not applicable' }, '"shown"')
    assert.equal(captured[2].init.headers['If-Match'], '"shown"')
    assert.deepEqual(JSON.parse(captured[2].init.body), { review: 'dismissed', reason: 'Not applicable' })
  } finally { globalThis.fetch = previous }
})
