<!-- Назначение файла: загрузка PDF в корпус: перетаскивание или выбор файлов, код статьи для каждого файла
     (подставляется из имени D001.pdf), прогресс, понятные ошибки 409/413/415/422, повтор того же code+hash
     как «уже загружен». После загрузки можно сразу запустить обработку загруженных. -->
<script setup>
import { computed, ref, watch } from 'vue'
import { Upload, FileText, Check, CircleAlert } from '@lucide/vue'
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
      <Upload />
      <p><b>Перетащите PDF сюда</b> или нажмите, чтобы выбрать файлы</p>
      <p class="faint">До {{ limits.max_file_mb }} МБ и {{ limits.max_pages }} страниц на файл. Код статьи берётся из имени файла.</p>
      <input ref="input" type="file" accept="application/pdf,.pdf" multiple hidden @change="add([...$event.target.files]); $event.target.value = ''">
    </div>

    <ul v-if="rows.length" class="uprows">
      <li v-for="r in rows" :key="r.key" class="uprow" :class="`uprow--${r.state}`">
        <FileText class="uprow__icon" />
        <div class="uprow__main">
          <p class="ellipsis"><b>{{ r.file.name }}</b> <span class="faint">{{ fmtBytes(r.file.size) }}</span></p>
          <Progress v-if="r.state === 'uploading'" :value="r.progress" class="uprow__bar" />
          <p v-else-if="r.message" class="uprow__msg">{{ r.message }}</p>
        </div>
        <label class="uprow__code">
          <span class="visually-hidden">Код статьи</span>
          <input v-model="r.code" class="input input--sm" :disabled="!['ready', 'failed'].includes(r.state)" placeholder="D001" :aria-invalid="r.state === 'ready' && !!r.message">
        </label>
        <span class="uprow__state">
          <Check v-if="r.state === 'done' || r.state === 'same'" class="ok" />
          <CircleAlert v-else-if="r.state === 'failed' || r.state === 'error'" class="bad" />
          <button v-if="r.state === 'failed'" class="btn btn--sm btn--ghost" type="button" @click="retryRow(r)">Ещё раз</button>
        </span>
      </li>
    </ul>

    <template #footer>
      <button class="btn" type="button" @click="emit('close')">{{ uploaded.length ? 'Готово' : 'Отмена' }}</button>
      <button v-if="uploaded.length && !rows.some(r => r.state === 'ready')" class="btn btn--primary" type="button" :disabled="busy" @click="processUploaded">Обработать загруженные ({{ uploaded.length }})</button>
      <button v-else class="btn btn--primary" type="button" :disabled="busy || !rows.some(r => r.state === 'ready')" @click="start">Загрузить {{ rows.filter(r => r.state === 'ready').length || '' }}</button>
    </template>
  </Modal>
</template>

<style>
.drop { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 28px 20px; border: 1.5px dashed var(--line-strong); border-radius: var(--r-lg); background: var(--surface-2); text-align: center; cursor: pointer; transition: border-color .15s var(--ease), background-color .15s var(--ease); }
.drop:hover, .drop.is-over { border-color: var(--accent); background: var(--accent-soft); }
.drop svg { width: 24px; height: 24px; color: var(--muted); margin-bottom: 4px; }
.drop b { font-weight: 600; }
.drop .faint { font-size: var(--fs-sm); }
.uprows { margin-top: var(--s-4); display: flex; flex-direction: column; }
.uprow { display: flex; align-items: center; gap: 12px; padding: 10px 2px; border-bottom: 1px solid var(--line); }
.uprow:last-child { border-bottom: 0; }
.uprow__icon { width: 18px; height: 18px; color: var(--muted); flex: none; }
.uprow__main { flex: 1; min-width: 0; }
.uprow__bar { margin-top: 6px; }
.uprow__msg { margin-top: 2px; font-size: var(--fs-sm); color: var(--muted); }
.uprow--failed .uprow__msg, .uprow--error .uprow__msg, .uprow--ready .uprow__msg { color: var(--danger); }
.uprow__code { width: 92px; flex: none; }
.uprow__state { display: flex; align-items: center; gap: 4px; min-width: 24px; }
.uprow__state svg { width: 18px; height: 18px; }
.uprow__state .ok { color: var(--accent-text); }
.uprow__state .bad { color: var(--danger); }
</style>
