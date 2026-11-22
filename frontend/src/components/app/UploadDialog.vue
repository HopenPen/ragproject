<!-- Назначение файла: загрузка PDF в корпус: перетаскивание или выбор файлов, код статьи для каждого файла
     (подставляется из имени D001.pdf), прогресс, понятные ошибки 409/413/415/422, повтор того же code+hash
     как «уже загружен». После загрузки можно сразу запустить обработку загруженных. -->
<script setup>
import { computed, ref, watch } from 'vue'
import Modal from '../ui/Modal.vue'
import Progress from '../ui/Progress.vue'
import { documents, jobs } from '../../api/index.js'
import { ws, kickJobs } from '../../stores/workspace.js'
import { notify } from '../../stores/toasts.js'
import { fmtBytes } from '../../lib/format.js'

const props = defineProps({ open: Boolean, corpusId: String })
const emit = defineEmits(['close', 'uploaded'])
const rows = ref([])
const over = ref(false)
const busy = ref(false)
const input = ref(null)
const limits = computed(() => ws.processing?.limits || { max_file_mb: 100, max_pages: 300 })

watch(() => props.open, o => { if (o) rows.value = [] })

function guessCode (name) {
  const m = /([A-Za-z]{1,3})[-_ ]?(\d{2,4})/.exec(name.replace(/\.pdf$/i, ''))
  return m ? (m[1] + m[2]).toUpperCase() : ''
}
function add (files) {
  for (const f of files) {
    const isPdf = f.type === 'application/pdf' || /\.pdf$/i.test(f.name)
    rows.value.push({
      key: `${f.name}-${f.size}-${Math.random()}`, file: f, code: guessCode(f.name), progress: 0,
      state: isPdf ? 'ready' : 'error', message: isPdf ? '' : 'Не PDF: такой файл не принимается', doc: null
    })
  }
}
function onDrop (e) { over.value = false; add([...e.dataTransfer.files]) }
const pending = computed(() => rows.value.filter(r => r.state === 'ready' || r.state === 'error' && r.file && /\.pdf$/i.test(r.file.name) && r.retry))
const uploaded = computed(() => rows.value.filter(r => r.doc && r.state === 'done'))
const codeOk = code => /^[A-Za-z]{1,3}\d{2,4}$/.test(code.trim())

async function start () {
  busy.value = true
  for (const r of rows.value.filter(x => x.state === 'ready')) {
    if (!codeOk(r.code)) { r.state = 'ready'; r.message = 'Код: буквы и цифры, например D001'; continue }
    r.state = 'uploading'
    r.message = ''
    try {
      const doc = await documents.upload(props.corpusId, r.file, r.code.trim().toUpperCase(), p => { r.progress = p })
      r.doc = doc
      r.state = doc._duplicate ? 'same' : 'done'
      r.message = doc._duplicate ? 'Уже был загружен: тот же код и файл' : ''
    } catch (e) {
      r.state = 'failed'
      r.message = e.message
    }
  }
  busy.value = false
  if (uploaded.value.length) emit('uploaded')
}
async function processUploaded () {
  busy.value = true
  try {
    await jobs.create(props.corpusId, { kind: 'process', document_ids: uploaded.value.map(r => r.doc.id) })
    notify.ok('Обработка запущена')
    kickJobs()
    emit('close')
  } catch (e) { notify.error(e) } finally { busy.value = false }
}
function retryRow (r) { r.state = 'ready'; r.message = ''; r.progress = 0 }
</script>

<template>
  <Modal :open="open" title="Загрузка PDF" width="640px" @close="emit('close')">
    <div
      class="drop" :class="{ 'is-over': over }" role="button" tabindex="0"
      @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop"
      @click="input?.click()" @keydown.enter.prevent="input?.click()"
    >
      <p>Перетащите PDF сюда или <u>выберите файлы</u></p>
      <p class="drop__sub">До {{ limits.max_file_mb }} МБ и {{ limits.max_pages }} страниц на файл. Код статьи берётся из имени файла.</p>
      <input ref="input" type="file" accept="application/pdf,.pdf" multiple hidden @change="add([...$event.target.files]); $event.target.value = ''">
    </div>

    <ul v-if="rows.length" class="uprows">
      <li v-for="r in rows" :key="r.key" class="uprow" :class="`uprow--${r.state}`">
        <div class="uprow__main">
          <p class="ellipsis"><b>{{ r.file.name }}</b><span class="uprow__size">{{ fmtBytes(r.file.size) }}</span></p>
          <Progress v-if="r.state === 'uploading'" :value="r.progress" class="uprow__bar" />
          <p v-else-if="r.message" class="uprow__msg">{{ r.message }}</p>
        </div>
        <label class="uprow__code">
          <span class="visually-hidden">Код статьи</span>
          <input v-model="r.code" class="input input--sm" :disabled="!['ready', 'failed'].includes(r.state)" placeholder='Например: "D001"' :aria-invalid="r.state === 'ready' && !!r.message">
        </label>
        <span class="uprow__state">
          <span v-if="r.state === 'done'" class="chip chip--ok uprow__ok">Загружен</span>
          <span v-else-if="r.state === 'same'" class="chip chip--plain">Уже есть</span>
          <span v-else-if="r.state === 'error'" class="chip chip--error">Не PDF</span>
          <button v-else-if="r.state === 'failed'" class="btn btn--sm btn--ghost" type="button" @click="retryRow(r)">Ещё раз</button>
        </span>
      </li>
    </ul>

    <template #footer>
      <button class="btn btn--ghost" type="button" @click="emit('close')">{{ uploaded.length ? 'Готово' : 'Отмена' }}</button>
      <button v-if="uploaded.length && !rows.some(r => r.state === 'ready')" class="btn btn--accent" type="button" :disabled="busy" @click="processUploaded">Обработать загруженные ({{ uploaded.length }})</button>
      <button v-else class="btn btn--primary" type="button" :disabled="busy || !rows.some(r => r.state === 'ready')" @click="start">Загрузить {{ rows.filter(r => r.state === 'ready').length || '' }}</button>
    </template>
  </Modal>
</template>

<style>
.drop { display: flex; flex-direction: column; gap: 2px; padding: 26px 22px; border-radius: 6px; background: var(--shelf); cursor: pointer; transition: box-shadow 140ms var(--ease), background-color 140ms var(--ease); }
.drop:hover { box-shadow: inset 0 0 0 1px var(--rule-mid); }
.drop.is-over { background: var(--picked); box-shadow: inset 0 0 0 2px var(--source); }
.drop p:first-child { font-weight: 600; }
.drop u { text-underline-offset: 3px; text-decoration-thickness: 1px; }
.drop__sub { font-size: 13px; line-height: 18px; color: var(--pencil); }
.uprows { margin-top: 14px; }
.uprow { display: flex; align-items: center; gap: 12px; padding: 10px 0; }
.uprow + .uprow { box-shadow: inset 0 1px 0 var(--rule); }
.uprow__main { flex: 1; min-width: 0; }
.uprow__main b { font-weight: 600; }
.uprow__size { margin-left: 8px; color: var(--pencil); }
.uprow__bar { margin-top: 6px; }
.uprow__msg { margin-top: 2px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.uprow--failed .uprow__msg, .uprow--error .uprow__msg, .uprow--ready .uprow__msg { color: var(--danger); }
.uprow__code { width: 156px; flex: none; }
.uprow__state { display: flex; justify-content: flex-end; min-width: 84px; }
.uprow__ok { color: var(--accent-text); }
</style>
