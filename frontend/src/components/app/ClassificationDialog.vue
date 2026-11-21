<!-- Назначение файла: ручное решение по теме статьи (POST /documents/{id}/classifications/review):
     темы, рамки профиля и обязательная причина. Показывает оценку модели и фрагмент, на который она опиралась. -->
<script setup>
import { computed, ref, watch } from 'vue'
import Modal from '../ui/Modal.vue'
import { documents } from '../../api/index.js'
import { notify } from '../../stores/toasts.js'
import { kickJobs } from '../../stores/workspace.js'
import { fmtNum } from '../../lib/format.js'

const props = defineProps({ open: Boolean, documentId: String, code: String })
const emit = defineEmits(['close', 'done'])
const cur = ref(null)
const labels = ref([])
const scope = ref({ 'solar-v1': true, 'rag-v1': true })
const reason = ref('')
const busy = ref(false)
const error = ref('')

watch(() => [props.open, props.documentId], async ([open]) => {
  if (!open) return
  error.value = ''
  reason.value = ''
  cur.value = null
  try {
    const res = await documents.classifications(props.documentId)
    cur.value = res.current
    labels.value = [...(res.current?.labels || [])]
    scope.value = { 'solar-v1': res.current?.scope?.['solar-v1'] ?? true, 'rag-v1': res.current?.scope?.['rag-v1'] ?? true }
  } catch (e) { error.value = e.message }
}, { immediate: true })

const TOPICS = [
  { label: 'solar', profile: 'solar-v1', title: 'Солнечные элементы', hint: 'однопереходные тонкоплёночные приборы' },
  { label: 'rag', profile: 'rag-v1', title: 'RAG-системы', hint: 'поиск плюс генерация, с оценкой качества' }
]
const valid = computed(() => reason.value.trim().length > 2)
async function submit () {
  if (!valid.value) { error.value = 'Укажите причину решения.'; return }
  busy.value = true
  error.value = ''
  try {
    const sc = {}
    for (const t of TOPICS) if (labels.value.includes(t.label)) sc[t.profile] = scope.value[t.profile]
    await documents.reviewClassification(props.documentId, { expected_revision: cur.value?.revision_id, labels: labels.value, scope: sc, reason: reason.value.trim(), replace_reviewed: cur.value?.origin === 'manual' })
    notify.ok(labels.value.length ? 'Тема сохранена, обработка продолжается' : 'Статья отмечена как вне тем')
    kickJobs()
    emit('done')
    emit('close')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="`Тема статьи ${code || ''}`" width="560px" @close="emit('close')">
    <div v-if="cur" class="stack cls">
      <div class="cls__model">
        <p class="muted">Оценка модели</p>
        <ul class="cls__scores">
          <li v-for="t in TOPICS" :key="t.label"><span>{{ t.title }}</span><b class="num">{{ fmtNum(cur.scores?.[t.label], 2) }}</b></li>
        </ul>
        <p v-if="cur.note" class="cls__note">{{ cur.note }}</p>
        <blockquote v-if="cur.evidence?.[0]" class="quote">{{ cur.evidence[0].fragment }}</blockquote>
        <p v-if="cur.evidence?.[0]" class="faint cls__where">стр. {{ cur.evidence[0].page }}</p>
      </div>
      <fieldset class="cls__topics">
        <legend class="field__label">Ваше решение</legend>
        <div v-for="t in TOPICS" :key="t.label" class="cls__topic">
          <label class="check"><input v-model="labels" type="checkbox" class="cb" :value="t.label"><span>{{ t.title }}<span class="faint">, {{ t.hint }}</span></span></label>
          <div v-if="labels.includes(t.label)" class="cls__scope">
            <label class="check"><input v-model="scope[t.profile]" type="radio" :value="true">в рамках профиля</label>
            <label class="check"><input v-model="scope[t.profile]" type="radio" :value="false">вне рамок (например, тандем)</label>
          </div>
        </div>
        <p v-if="!labels.length" class="field__hint">Без отмеченных тем статья попадёт в выгрузку только библиографией.</p>
      </fieldset>
      <label class="field">
        <span class="field__label">Причина</span>
        <textarea v-model="reason" class="textarea" rows="2" placeholder="Например: в разделе 2 есть устройство и J-V, тема подтверждена" />
      </label>
      <p v-if="error" class="field__error" role="alert">{{ error }}</p>
    </div>
    <div v-else-if="error" class="field__error">{{ error }}</div>
    <div v-else class="skeleton" style="height: 220px" />
    <template #footer>
      <button class="btn" type="button" @click="emit('close')">Отмена</button>
      <button class="btn btn--primary" type="button" :disabled="busy || !cur" @click="submit">Сохранить решение</button>
    </template>
  </Modal>
</template>

<style>
.cls { gap: 18px; }
.cls__model > .muted { color: var(--u-soft); }
.cls__scores { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0 10px; }
.cls__scores li { display: grid; gap: 2px; padding: 8px 12px; border-radius: 8px; background: var(--u-fill); border: 1px solid var(--u-line); }
.cls__scores span { font-size: 12px; line-height: 16px; color: var(--u-muted); }
.cls__scores b { font-size: 15px; line-height: 20px; font-weight: 500; }
.cls__note { display: flex; gap: 8px; margin-bottom: 10px; color: var(--u-ink); }
.cls__note::before { content: ""; width: 6px; height: 6px; margin-top: 7px; border-radius: 50%; background: var(--ochre); flex: none; }
.cls__where { margin-top: 4px; font-size: 12px; line-height: 16px; }
.cls__topics { border: 0; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.cls__topics legend { margin-bottom: 8px; }
.cls__scope { display: flex; gap: 16px; margin: 6px 0 0 24px; flex-wrap: wrap; }
.cls__scope .check input { accent-color: var(--u-ink); }
</style>
