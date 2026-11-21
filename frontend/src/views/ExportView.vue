<!-- Назначение файла: выгрузка корпуса (задание export): профили, строгий режим или с пропусками, сверка источников
     и внешний checker; список выгрузок со скачиванием ZIP, паспортом данных и отчётом проверки. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Download } from '@lucide/vue'
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
// состав архива строками: папка и её файлы, файлы корня архива отдельной строкой в конце
function groupsOf (j) {
  const groups = new Map()
  for (const f of j.result?.files || []) {
    const cut = f.lastIndexOf('/') + 1
    const dir = f.slice(0, cut)
    if (!groups.has(dir)) groups.set(dir, [])
    groups.get(dir).push(f.slice(cut))
  }
  return [...groups.entries()].sort((a, b) => (a[0] ? 0 : 1) - (b[0] ? 0 : 1)).map(([dir, files]) => ({ dir, files }))
}
const latest = computed(() => exports.value.find(j => j.status === 'succeeded'))
watch(() => ws.jobsVersion, () => {})
onMounted(() => kickJobs())
</script>

<template>
  <div class="page exp">
    <div class="page__head"><h1 class="page__title">Выгрузка</h1></div>
    <div class="exp__grid">
      <section class="exp__form" aria-labelledby="exp-new">
        <h2 id="exp-new">Новая выгрузка</h2>
        <fieldset class="exp__set">
          <legend>Профили</legend>
          <label class="check"><input v-model="profiles" type="checkbox" class="cb" value="solar-v1">Солнечные элементы</label>
          <label class="check"><input v-model="profiles" type="checkbox" class="cb" value="rag-v1">RAG-системы</label>
        </fieldset>
        <fieldset class="exp__set">
          <legend>Режим</legend>
          <label class="exp__mode"><input v-model="mode" type="radio" class="rb" value="strict"><span><b>Строгая</b>Только принятые статьи и значения с источником</span></label>
          <label class="exp__mode"><input v-model="mode" type="radio" class="rb" value="incomplete"><span><b>С пропусками</b>Всё готовое, пропуски перечислены в manifest.json</span></label>
        </fieldset>
        <fieldset class="exp__set">
          <legend>Перед сборкой</legend>
          <label class="check"><input v-model="checkSources" type="checkbox" class="cb">Сверить источники значений</label>
          <label class="check" :class="{ 'is-off': !profiles.includes('solar-v1') }"><input v-model="checker" type="checkbox" class="cb" :disabled="!profiles.includes('solar-v1')">Внешний checker для solar</label>
        </fieldset>
        <button class="btn btn--accent btn--block btn--lg" type="button" :disabled="busy || !editable || !profiles.length" @click="create()">Собрать выгрузку</button>
        <p v-if="!editable" class="exp__note">Собирать выгрузку может редактор корпуса.</p>
      </section>

      <section class="exp__list" aria-labelledby="exp-list">
        <h2 id="exp-list">Архивы корпуса</h2>
        <div v-if="!exports.length" class="empty"><p>Выгрузок пока не было. Настройте состав слева и соберите первый архив.</p></div>
        <ol v-else class="exp__jobs">
          <li v-for="j in exports" :key="j.id" class="exp__job">
            <header class="exp__jhead">
              <h3>{{ j.target_profiles.map(profileShort).join(' и ') }}<span class="exp__mode-t">, {{ j.options?.allow_incomplete ? 'с пропусками' : 'строгая' }}</span></h3>
              <span class="exp__date">{{ fmtDate(j.created_at) }}</span>
              <span class="grow" />
              <Chip :tone="JOB_STATUS[j.status]?.tone" :text="JOB_STATUS[j.status]?.text || j.status" />
            </header>
            <div v-if="active(j)" class="exp__run">
              <p>{{ STAGE[j.stage] || 'В очереди' }}</p>
              <Progress :value="value(j)" />
            </div>
            <template v-else-if="j.status === 'succeeded'">
              <p class="exp__meta">{{ j.result.file_name }}, {{ fmtBytes(j.result.size_bytes) }}, {{ countText(j.result.documents, ['статья', 'статьи', 'статей']) }} с данными</p>
              <p v-if="j.result.gaps?.length" class="exp__gaps" :title="j.result.gaps.map(g => `${g.publication_code}: ${g.reason}`).join('\n')">Пропущено {{ countText(j.result.gaps.length, ['статья', 'статьи', 'статей']) }}: {{ j.result.gaps.map(g => g.publication_code).join(', ') }}. Причины в manifest.json</p>
              <dl class="exp__tree" aria-label="Состав архива">
                <template v-for="g in groupsOf(j)" :key="g.dir">
                  <dt>{{ g.dir || 'в корне' }}</dt>
                  <dd>{{ g.files.join(', ') }}</dd>
                </template>
              </dl>
              <div class="exp__actions">
                <button class="btn btn--primary btn--sm" type="button" @click="download(j)"><Download />Скачать ZIP</button>
                <button class="btn btn--ghost btn--sm" type="button" @click="show(j, 'passport')">Паспорт данных</button>
                <button class="btn btn--ghost btn--sm" type="button" @click="show(j, 'report')">Отчёт проверки</button>
              </div>
            </template>
            <template v-else-if="j.status === 'failed'">
              <p class="exp__err">{{ j.error?.message }}</p>
              <ul v-if="j.error?.details?.blockers" class="exp__blockers">
                <li v-for="(b, i) in j.error.details.blockers" :key="i"><b>{{ b.publication_code }}</b>{{ b.reason }}</li>
              </ul>
              <div v-if="editable" class="exp__actions">
                <button class="btn btn--sm" type="button" @click="router.push(`/corpora/${ws.corpus.id}/checks`)">Открыть проверки</button>
                <button class="btn btn--ghost btn--sm" type="button" :disabled="busy" @click="profiles = j.target_profiles; create({ mode: 'incomplete' })">Собрать с пропусками</button>
              </div>
            </template>
          </li>
        </ol>
      </section>
    </div>

    <Drawer :open="panel.open" :title="panel.title" width="680px" @close="panel.open = false">
      <template v-if="panel.kind === 'passport'">
        <section v-for="t in tables" :key="t.profile + t.file" class="pass">
          <h3>{{ t.file }}<span class="pass__sub">{{ profileShort(t.profile) }}, ключ <code>{{ t.id_field }}</code></span></h3>
          <table class="table pass__table">
            <thead><tr><th>Поле</th><th>Тип</th><th>Единица</th><th>Обязательное</th><th>Ссылка</th></tr></thead>
            <tbody>
              <tr v-for="f in t.fields" :key="f.name"><td><code>{{ f.name }}</code></td><td>{{ f.type }}<span v-if="f.vocabulary" class="muted" :title="f.vocabulary.join(', ')">, словарь {{ f.vocabulary.length }}</span></td><td>{{ f.unit || '' }}</td><td>{{ f.required ? 'да' : '' }}</td><td><code v-if="f.references">{{ f.references }}</code></td></tr>
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
        <table class="table rep__rules">
          <thead><tr><th>Правило</th><th>Профиль и порог</th><th class="t-num">Замечаний</th></tr></thead>
          <tbody>
            <tr v-for="r in panel.data.rules" :key="r.profile + r.id"><td>{{ ruleLabel(r.id) === r.id && r.id === 'jsc_limit' ? 'Пределы Jsc, FF и PCE' : ruleLabel(r.id) }}</td><td class="muted">{{ profileShort(r.profile) }}, {{ r.status === 'defined' ? `версия ${r.version}${r.threshold && r.threshold !== '-' ? `, порог ${r.threshold}` : ''}` : 'ждёт утверждения, пропущено' }}</td><td class="t-num">{{ panel.data.by_rule?.[r.id] || '' }}</td></tr>
          </tbody>
        </table>
      </template>
    </Drawer>
  </div>
</template>

<style>
/* выгрузка: слева состав новой выгрузки без рамки, справа архивы списком с линейками */
.exp__grid { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 56px; align-items: start; max-width: 1180px; }
.exp h2 { font-size: var(--t-17); line-height: 24px; font-weight: 600; letter-spacing: -0.01em; margin-bottom: 14px; }
.exp__form { position: sticky; top: 80px; }
.exp__set { border: 0; margin: 0 0 22px; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.exp__set legend { margin-bottom: 10px; color: var(--pencil); }
.exp__mode { display: flex; gap: 10px; cursor: pointer; }
.exp__mode .rb { margin-top: 2px; }
.exp__mode > span { display: flex; flex-direction: column; color: var(--pencil); font-size: 13px; line-height: 18px; }
.exp__mode b { font-size: var(--t-14); line-height: 20px; font-weight: 600; color: var(--ink); }
.check.is-off { color: var(--pencil); }
.exp__note { margin-top: 10px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.exp__list { min-width: 0; }
.exp__list .empty { padding-top: 0; }
.exp__jobs { box-shadow: inset 0 1.5px 0 var(--rule-strong); }
.exp__job { padding: 18px 0 20px; }
.exp__job + .exp__job { box-shadow: inset 0 1px 0 var(--rule); }
.exp__jhead { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.exp__jhead h3 { font-size: var(--t-14); line-height: 20px; font-weight: 600; }
.exp__mode-t { font-weight: 400; color: var(--pencil); }
.exp__date { color: var(--pencil); }
.exp__run { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; max-width: 420px; color: var(--pencil); }
.exp__meta { margin-top: 4px; color: var(--pencil); }
.exp__gaps { margin-top: 2px; color: var(--warn); }
.exp__tree { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 20px; margin-top: 14px; font-size: 13px; line-height: 18px; }
.exp__tree dt { font-weight: 600; }
.exp__tree dd { color: var(--pencil); max-width: 72ch; }
.exp__actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 16px; }
.exp__err { margin-top: 8px; max-width: 72ch; }
.exp__blockers { margin-top: 8px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.exp__blockers li { display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: 12px; padding: 3px 0; }
.exp__blockers b { font-weight: 600; color: var(--ink); }
.pass { margin-bottom: 28px; }
.pass h3 { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; font-size: var(--t-14); line-height: 20px; font-weight: 600; margin-bottom: 8px; }
.pass__sub { font-weight: 400; color: var(--pencil); }
.pass__table td, .pass__table th { height: 34px; font-size: 13px; }
.exp code, .drawer code { font-family: var(--mono); font-size: 12.5px; }
.rep { margin-bottom: 24px; }
.rep__rules td { height: 40px; }
@media (max-width: 1100px) { .exp__grid { grid-template-columns: 1fr; gap: 32px; } .exp__form { position: static; max-width: 420px; } }
</style>
