<!-- Назначение файла: выгрузка корпуса (задание export): профили, строгий режим или с пропусками, сверка источников
     и внешний checker; список выгрузок со скачиванием ZIP, паспортом данных и отчётом проверки. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Download, FileJson, ClipboardList, PackageCheck } from '@lucide/vue'
import Chip from '../components/ui/Chip.vue'
import Progress from '../components/ui/Progress.vue'
import Drawer from '../components/ui/Drawer.vue'
import { jobs } from '../api/index.js'
import { ws, kickJobs } from '../stores/workspace.js'
import { canEdit } from '../stores/session.js'
import { notify } from '../stores/toasts.js'
import { JOB_STATUS, STAGE, TERMINAL, profileShort, ruleLabel } from '../lib/labels.js'
import { fmtDate, fmtBytes, countText } from '../lib/format.js'

const router = useRouter()
const profiles = ref(['solar-v1', 'rag-v1'])
const mode = ref('strict')
const checkSources = ref(true)
const checker = ref(true)
const busy = ref(false)
const panel = ref({ open: false, kind: '', title: '', data: null })
const editable = computed(() => canEdit(ws.corpus))
const exports = computed(() => ws.jobs.filter(j => j.kind === 'export'))

async function create (override = {}) {
  if (!profiles.value.length) { notify.info('Выберите хотя бы один профиль'); return }
  busy.value = true
  try {
    await jobs.create(ws.corpus.id, {
      kind: 'export', target_profiles: profiles.value, allow_incomplete: (override.mode || mode.value) === 'incomplete',
      check_sources: checkSources.value, run_external_checker: checker.value && profiles.value.includes('solar-v1')
    })
    notify.ok('Выгрузка собирается')
    kickJobs()
  } catch (e) { notify.error(e) } finally { busy.value = false }
}
async function download (j) {
  try { const name = await jobs.download(j.id, j.result?.file_name); notify.ok(`Скачан ${name}`) } catch (e) { notify.error(e) }
}
async function show (j, kind) {
  try {
    const data = kind === 'passport' ? await jobs.passport(j.id) : await jobs.report(j.id)
    panel.value = { open: true, kind, title: kind === 'passport' ? 'Паспорт данных' : 'Отчёт проверки', data }
  } catch (e) { notify.error(e) }
}
const tables = computed(() => {
  const d = panel.value.data
  if (!d || panel.value.kind !== 'passport') return []
  return (d.profiles || [d]).flatMap(p => p.tables.map(t => ({ ...t, profile: p.profile })))
})
const active = j => !TERMINAL.has(j.status)
const value = j => j.progress?.total ? j.progress.done / j.progress.total : null
function treeOf (j) {
  const groups = new Map()
  for (const f of j.result?.files || []) {
    const i = f.lastIndexOf('/')
    const dir = i >= 0 ? f.slice(0, i + 1) : ''
    if (!groups.has(dir)) groups.set(dir, [])
    groups.get(dir).push(f.slice(i + 1))
  }
  return [...groups.entries()].map(([dir, files]) => ({ dir, files }))
}
const latest = computed(() => exports.value.find(j => j.status === 'succeeded'))
watch(() => ws.jobsVersion, () => {})
onMounted(() => kickJobs())
</script>

<template>
  <div class="page exp">
    <div class="page__head"><h1 class="page__title">Выгрузка</h1></div>
    <div class="exp__grid">
      <section class="panel exp__form">
        <h2>Новая выгрузка</h2>
        <fieldset class="exp__set">
          <legend class="field__label">Профили</legend>
          <label class="check"><input v-model="profiles" type="checkbox" value="solar-v1">Солнечные элементы</label>
          <label class="check"><input v-model="profiles" type="checkbox" value="rag-v1">RAG-системы</label>
        </fieldset>
        <fieldset class="exp__set">
          <legend class="field__label">Режим</legend>
          <label class="exp__mode" :class="{ 'is-on': mode === 'strict' }"><input v-model="mode" type="radio" value="strict"><span><b>Строгая</b><span class="muted">Остановится, если есть статьи без принятой темы или результаты без источника.</span></span></label>
          <label class="exp__mode" :class="{ 'is-on': mode === 'incomplete' }"><input v-model="mode" type="radio" value="incomplete"><span><b>С пропусками</b><span class="muted">Соберёт всё готовое, пропуски перечислит в manifest.json.</span></span></label>
        </fieldset>
        <fieldset class="exp__set">
          <legend class="field__label">Проверки перед сборкой</legend>
          <label class="check"><input v-model="checkSources" type="checkbox">Сверить источники значений</label>
          <label class="check" :class="{ 'is-off': !profiles.includes('solar-v1') }"><input v-model="checker" type="checkbox" :disabled="!profiles.includes('solar-v1')">Внешний checker для solar</label>
        </fieldset>
        <button class="btn btn--primary btn--block" type="button" :disabled="busy || !editable || !profiles.length" @click="create()"><PackageCheck />Собрать выгрузку</button>
        <p v-if="!editable" class="field__hint">Собирать выгрузку может редактор корпуса.</p>
      </section>

      <section class="exp__list">
        <h2>Выгрузки корпуса</h2>
        <p v-if="!exports.length" class="muted">Выгрузок пока не было.</p>
        <article v-for="j in exports" :key="j.id" class="panel exp__job">
          <header class="exp__jhead">
            <b>{{ j.target_profiles.map(profileShort).join(' и ') }}</b>
            <span class="muted">{{ j.options?.allow_incomplete ? 'с пропусками' : 'строгая' }}, {{ fmtDate(j.created_at) }}</span>
            <span class="grow" />
            <Chip :tone="JOB_STATUS[j.status]?.tone" :text="JOB_STATUS[j.status]?.text || j.status" />
          </header>
          <div v-if="active(j)" class="exp__run">
            <p class="muted">{{ STAGE[j.stage] || 'В очереди' }}</p>
            <Progress :value="value(j)" />
          </div>
          <template v-else-if="j.status === 'succeeded'">
            <p class="exp__meta muted"><span class="mono">{{ j.result.file_name }}</span>, {{ fmtBytes(j.result.size_bytes) }}, {{ countText(j.result.documents, ['статья', 'статьи', 'статей']) }} с данными</p>
            <p v-if="j.result.gaps?.length" class="exp__gaps">Пропуски ({{ j.result.gaps.length }}): {{ j.result.gaps.map(g => `${g.publication_code}, ${g.reason}`).join('; ') }}</p>
            <div class="exp__tree">
              <ul v-for="g in treeOf(j)" :key="g.dir" class="exp__dir">
                <li v-if="g.dir" class="exp__dirname mono">{{ g.dir }}</li>
                <li v-for="f in g.files" :key="f" class="mono" :class="{ 'exp__in': g.dir }">{{ f }}</li>
              </ul>
            </div>
            <div class="exp__actions">
              <button class="btn btn--primary btn--sm" type="button" @click="download(j)"><Download />Скачать ZIP</button>
              <button class="btn btn--sm" type="button" @click="show(j, 'passport')"><FileJson />Паспорт данных</button>
              <button class="btn btn--sm" type="button" @click="show(j, 'report')"><ClipboardList />Отчёт проверки</button>
            </div>
          </template>
          <template v-else-if="j.status === 'failed'">
            <p class="exp__err">{{ j.error?.message }}</p>
            <ul v-if="j.error?.details?.blockers" class="exp__blockers">
              <li v-for="(b, i) in j.error.details.blockers" :key="i"><b>{{ b.publication_code }}</b>: {{ b.reason }}</li>
            </ul>
            <div v-if="editable" class="exp__actions">
              <button class="btn btn--sm" type="button" @click="router.push(`/corpora/${ws.corpus.id}/checks`)">Открыть проверки</button>
              <button class="btn btn--sm btn--primary" type="button" :disabled="busy" @click="profiles = j.target_profiles; create({ mode: 'incomplete' })">Собрать с пропусками</button>
            </div>
          </template>
        </article>
      </section>
    </div>

    <Drawer :open="panel.open" :title="panel.title" width="680px" @close="panel.open = false">
      <template v-if="panel.kind === 'passport'">
        <section v-for="t in tables" :key="t.profile + t.file" class="pass">
          <h3><span class="mono">{{ t.file }}</span> <span class="faint">{{ profileShort(t.profile) }}, ключ {{ t.id_field }}</span></h3>
          <table class="table pass__table">
            <thead><tr><th>Поле</th><th>Тип</th><th>Единица</th><th>Обяз.</th><th>Ссылка</th></tr></thead>
            <tbody>
              <tr v-for="f in t.fields" :key="f.name"><td class="mono">{{ f.name }}</td><td>{{ f.type }}<span v-if="f.vocabulary" class="faint" :title="f.vocabulary.join(', ')">, словарь {{ f.vocabulary.length }}</span></td><td>{{ f.unit || '' }}</td><td>{{ f.required ? 'да' : '' }}</td><td class="mono">{{ f.references || '' }}</td></tr>
            </tbody>
          </table>
        </section>
      </template>
      <template v-else-if="panel.data">
        <dl class="kv rep">
          <dt>Замечаний</dt><dd>{{ panel.data.issues_total }}</dd>
          <dt>По важности</dt><dd>{{ Object.entries(panel.data.by_severity || {}).map(([k, v]) => `${k === 'error' ? 'ошибки' : k === 'warning' ? 'замечания' : 'справки'} ${v}`).join(', ') || 'нет' }}</dd>
          <dt>По решению</dt><dd>{{ Object.entries(panel.data.by_status || {}).map(([k, v]) => `${k === 'open' ? 'открыто' : k === 'confirmed' ? 'подтверждено' : 'отклонено'} ${v}`).join(', ') || 'нет' }}</dd>
          <dt>Внешний checker</dt><dd>{{ (panel.data.external_checker || []).map(c => `${profileShort(c.profile)}: ${c.status === 'not_run_in_demo' ? 'не запускался в демо' : c.status === 'not_available_for_profile' ? 'для профиля нет' : c.status}`).join('; ') }}</dd>
        </dl>
        <h3 class="rep__h">Правила</h3>
        <ul class="rep__rules">
          <li v-for="r in panel.data.rules" :key="r.profile + r.id"><span>{{ ruleLabel(r.id) === r.id && r.id === 'jsc_limit' ? 'Пределы Jsc, FF и PCE' : ruleLabel(r.id) }}</span><span class="faint">{{ profileShort(r.profile) }}, {{ r.status === 'defined' ? `версия ${r.version}, порог ${r.threshold}` : 'ждёт утверждения, пропущено' }}</span><b class="num">{{ panel.data.by_rule?.[r.id] || '' }}</b></li>
        </ul>
      </template>
    </Drawer>
  </div>
</template>

<style>
.exp__grid { display: grid; grid-template-columns: 380px 1fr; gap: var(--s-6); align-items: start; }
.exp h2 { font-size: var(--fs-lg); margin-bottom: var(--s-4); }
.exp__form { padding: var(--s-5); position: sticky; top: calc(var(--header-h) + 16px); }
.exp__set { border: 0; margin: 0 0 var(--s-5); padding: 0; display: flex; flex-direction: column; gap: 8px; }
.exp__set legend { margin-bottom: 8px; }
.exp__mode { display: flex; gap: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--r-md); cursor: pointer; }
.exp__mode.is-on { border-color: var(--accent); background: var(--accent-soft); }
.exp__mode input { margin-top: 3px; accent-color: var(--accent); }
.exp__mode > span { display: flex; flex-direction: column; gap: 2px; }
.exp__mode .muted { font-size: var(--fs-sm); }
.check.is-off { opacity: .55; }
.exp__list { display: flex; flex-direction: column; gap: 12px; }
.exp__list h2 { margin-bottom: 4px; }
.exp__job { padding: 16px 18px; }
.exp__jhead { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.exp__jhead .muted { font-size: var(--fs-sm); }
.exp__run { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-sm); }
.exp__meta { margin-top: 8px; font-size: var(--fs-sm); }
.exp__gaps { margin-top: 6px; font-size: var(--fs-sm); color: var(--warn); }
.exp__tree { display: flex; flex-wrap: wrap; gap: 6px 32px; margin-top: 10px; padding: 10px 14px; border-radius: var(--r-md); background: var(--surface-2); border: 1px solid var(--line); font-size: var(--fs-sm); }
.exp__dir li { line-height: 1.7; }
.exp__dirname { color: var(--muted); }
.exp__in { padding-left: 14px; }
.exp__actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
.exp__err { margin-top: 10px; color: var(--danger); }
.exp__blockers { margin-top: 6px; font-size: var(--fs-sm); }
.exp__blockers li { padding: 3px 0; }
.pass { margin-bottom: 22px; }
.pass h3 { font-size: var(--fs-md); margin-bottom: 8px; font-weight: 600; }
.pass__table td, .pass__table th { height: 32px; font-size: var(--fs-sm); }
.rep { margin-bottom: 18px; }
.rep__h { font-size: var(--fs-md); margin: 6px 0 8px; }
.rep__rules li { display: grid; grid-template-columns: 1fr auto 40px; gap: 12px; padding: 8px 0; border-top: 1px solid var(--line); font-size: var(--fs-sm); }
.rep__rules b { text-align: right; }
@media (max-width: 1100px) { .exp__grid { grid-template-columns: 1fr; } .exp__form { position: static; } }
</style>
