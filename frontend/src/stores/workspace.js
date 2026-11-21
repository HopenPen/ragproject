// Назначение файла: общие данные рабочего места: список корпусов, текущий корпус, настройки обработки,
// схемы профилей и опрос активных заданий корпуса (раз в 1,5 с, пока задание идёт).
import { reactive } from 'vue'
import { corpora, reference, jobs } from '../api/index.js'
import { TERMINAL } from '../lib/labels.js'

export const ws = reactive({
  corpora: [],
  corpus: null,
  processing: null,
  profiles: {},
  jobs: [],
  jobsVersion: 0
})

export async function loadCorpora () {
  const list = await corpora.list()
  ws.corpora = list.items
  return ws.corpora
}

export async function openCorpus (id) {
  if (ws.corpus?.id !== id) {
    ws.corpus = ws.corpora.find(c => c.id === id) || null
    ws.jobs = []
  }
  ws.corpus = await corpora.get(id)
  const i = ws.corpora.findIndex(c => c.id === id)
  if (i >= 0) ws.corpora[i] = ws.corpus
  else ws.corpora.push(ws.corpus)
  startJobsPolling(id)
  return ws.corpus
}

export async function refreshCorpus () {
  if (!ws.corpus) return
  ws.corpus = await corpora.get(ws.corpus.id)
}

export async function loadReference () {
  if (!ws.processing) ws.processing = await reference.processing().catch(() => null)
  if (!Object.keys(ws.profiles).length) {
    const [solar, rag] = await Promise.all([reference.profile('solar-v1'), reference.profile('rag-v1')])
    ws.profiles = { 'solar-v1': solar, 'rag-v1': rag }
  }
}

let pollTimer = null
let pollCorpus = null
let lastActive = 0
async function pollOnce () {
  if (!pollCorpus) return
  try {
    const list = await jobs.list(pollCorpus)
    const active = list.items.filter(j => !TERMINAL.has(j.status) && !['waiting_review', 'paused'].includes(j.status))
    const changed = JSON.stringify(list.items.map(j => [j.id, j.status, j.stage, j.counters, j.progress])) !== JSON.stringify(ws.jobs.map(j => [j.id, j.status, j.stage, j.counters, j.progress]))
    ws.jobs = list.items
    if (changed) ws.jobsVersion++
    lastActive = active.length
  } catch { /* следующий опрос повторит */ }
  pollTimer = setTimeout(pollOnce, lastActive ? 1500 : 6000)
}
export function startJobsPolling (corpusId) {
  if (pollCorpus === corpusId && pollTimer) return
  stopJobsPolling()
  pollCorpus = corpusId
  pollOnce()
}
export function stopJobsPolling () {
  clearTimeout(pollTimer)
  pollTimer = null
  pollCorpus = null
}
export function kickJobs () {
  clearTimeout(pollTimer)
  pollOnce()
}
