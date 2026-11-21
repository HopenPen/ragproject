<!-- Назначение файла: заметка к записи. На компьютере она стоит на полях рядом со страницей и связана линией
     с числом в рамке: показатель, значение, условия, источник и решение по нему, замечания. На телефоне
     та же заметка в нижней панели, а вместо страницы показан вырезанный фрагмент с рамкой. -->
<script setup>
import { computed, ref } from 'vue'
import Chip from '../ui/Chip.vue'
import IssueCard from './IssueCard.vue'
import SourceCrop from './SourceCrop.vue'
import Metric from '../ui/Metric.vue'
import { publications } from '../../api/index.js'
import { askReason } from '../../stores/dialogs.js'
import { notify } from '../../stores/toasts.js'
import { EVIDENCE_REVIEW, METHOD, ID_FIELD, fieldLabel, valueLabel } from '../../lib/labels.js'
import { evidenceOf, quoteParts, resultContext } from '../../lib/records.js'
import { rowLine } from '../../lib/rowline.js'
import { fmtNum, fmtValue, fmtUnit, fmtResult } from '../../lib/format.js'

const props = defineProps({
  type: String, item: Object, graph: Object, etag: String, profile: String, publicationId: String, documentId: String,
  issues: { type: Array, default: () => [] }, editable: Boolean, mobile: Boolean
})
const emit = defineEmits(['edit', 'changed', 'issues-changed', 'stale'])
const busy = ref(false)
const isResult = computed(() => props.type === 'solar_result' || props.type === 'rag_result')
const ev = computed(() => evidenceOf(props.graph, props.item[ID_FIELD[props.type]]))
const ctx = computed(() => isResult.value ? resultContext(props.type, props.item, props.graph) : { rows: [] })
const head = computed(() => rowLine(props.type, props.item, props.graph))
const rawDiffers = computed(() => isResult.value && props.item.raw_value && (Number(String(props.item.raw_value).split(' ')[0]) !== Number(props.item.metric_value) || /±/.test(props.item.raw_value) || (props.item.raw_unit && props.item.raw_unit !== props.item.metric_unit)))
const normDiffers = computed(() => isResult.value && props.item.normalized_value !== null && props.item.normalized_value !== undefined && (props.item.normalized_value !== props.item.metric_value || props.item.normalized_unit !== props.item.metric_unit))
// агрегация, разброс и число приборов: то, чего нет в строке записи
const extra = computed(() => {
  if (!isResult.value) return ''
  const it = props.item
  const text = [it.aggregation ? valueLabel('aggregation', it.aggregation) : null, it.spread_value !== null && it.spread_value !== undefined ? `разброс ±${fmtNum(it.spread_value)}` : null, it.n_devices ? `n = ${it.n_devices}` : null].filter(Boolean).join(', ')
  return text ? text[0].toUpperCase() + text.slice(1) : ''
})
const fields = computed(() => Object.entries(props.item).filter(([k, v]) => v !== null && v !== '' && k !== ID_FIELD[props.type] && !k.startsWith('source_')))
const openIssues = computed(() => props.issues.filter(i => !i.stale))
const tone = computed(() => openIssues.value.some(i => i.status === 'open' && i.severity === 'error') ? 'error' : openIssues.value.some(i => i.status === 'open') ? 'warn' : 'ok')

async function review (decision) {
  const reason = decision === 'confirmed' ? '' : await askReason({ title: 'Источник не подходит', text: 'Источник будет отмечен как отклонённый, исходная цитата сохранится в истории. Значение останется, пока его не исправят.', confirm: 'Отклонить источник', placeholder: 'Например: число взято из строки другого прибора' })
  if (reason === null) return
  busy.value = true
  try {
    const res = await publications.reviewEvidence(props.publicationId, ev.value.evidence_id, { decision, reason, profile: props.profile }, props.etag)
    notify.ok(decision === 'confirmed' ? 'Источник подтверждён' : 'Источник отклонён')
    emit('changed', res)
  } catch (e) {
    if (e.status === 412) emit('stale')
    notify.error(e)
  } finally { busy.value = false }
}
async function remove () {
  const id = props.item[ID_FIELD[props.type]]
  const reason = await askReason({ title: `Удалить запись ${id}?`, text: 'Запись исчезнет из активной версии графа. Прежние версии и аудит сохранят её.', confirm: 'Удалить', tone: 'danger', placeholder: 'Например: дубль результата R3' })
  if (reason === null) return
  busy.value = true
  try {
    const res = await publications.deleteEntity(props.publicationId, props.type, id, { profile: props.profile, reason }, props.etag)
    notify.ok(`Запись ${id} удалена, версия ${res.data.revision_number}`)
    emit('changed', res)
  } catch (e) {
    if (e.status === 412) emit('stale')
    notify.error(e)
  } finally { busy.value = false }
}
</script>

<template>
  <div class="note" :class="{ 'note--sheet': mobile }">
    <header v-if="!mobile" class="note__head">
      <span class="note__name"><Metric v-if="isResult" :name="item.metric_name" :k="item.metric_k" /><template v-else>{{ head.title }}</template></span>
      <span class="note__id">{{ item[ID_FIELD[type]] }}</span>
    </header>
    <p v-if="isResult && !mobile" class="note__value num">{{ fmtResult(item) }}</p>
    <p v-if="head.sub" class="note__ctx">{{ head.sub }}</p>
    <p v-if="extra" class="note__ctx">{{ extra }}</p>
    <p v-if="rawDiffers || normDiffers" class="note__small">
      <template v-if="rawDiffers">В статье: <span class="num">{{ item.raw_value }}</span> {{ item.raw_unit ? fmtUnit(item.raw_unit) : '' }}. </template>
      <template v-if="normDiffers">Нормализовано: <span class="num">{{ fmtValue(item.normalized_value, item.normalized_unit) }}</span>.</template>
    </p>
    <p v-if="item.result_origin === 'cited'" class="note__small">Цитата из работы {{ item.cited_publication_id }}, с результатами статьи не сравнивается.</p>
    <p v-if="item.duplicate_of" class="note__small">Повтор записи {{ item.duplicate_of }}.</p>

    <section class="note__src">
      <template v-if="ev">
        <SourceCrop v-if="mobile && ev.bbox" :document-id="documentId" :page="ev.page" :bbox="ev.bbox" :tone="tone" />
        <blockquote v-else-if="mobile" class="quote"><template v-for="(p, i) in quoteParts(ev.fragment, item.raw_value)" :key="i"><mark v-if="p.hit">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template></blockquote>
        <p class="note__where">Стр. {{ ev.page }}<template v-if="ev.table">, {{ ev.table }}</template><template v-if="ev.figure">, {{ ev.figure }}</template><template v-if="['ocr', 'vision'].includes(ev.method)">, {{ METHOD[ev.method] }}</template>, уверенность {{ fmtNum(ev.confidence, 2) }}</p>
        <div v-if="editable && ev.review_status === 'pending'" class="note__decide">
          <button class="btn btn--sm" type="button" :disabled="busy" @click="review('confirmed')">Источник верный</button>
          <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="review('rejected')">Не тот</button>
        </div>
        <p v-else-if="ev.review_status !== 'pending'" class="note__decided"><Chip :tone="EVIDENCE_REVIEW[ev.review_status]?.tone" :text="EVIDENCE_REVIEW[ev.review_status]?.text" /><template v-if="ev.review_reason">: {{ ev.review_reason }}</template></p>
      </template>
      <p v-else class="note__missing">Место в статье не найдено<template v-if="item.source_figure">, значение прочитано с рисунка {{ item.source_figure }}</template>. В строгую выгрузку запись не попадёт.</p>
    </section>

    <section v-if="openIssues.length" class="note__issues">
      <IssueCard v-for="i in openIssues" :key="i.id" :issue="i" :editable="editable" compact @changed="emit('issues-changed')" />
    </section>

    <details v-if="ctx.rows.length || !isResult" class="note__more" :open="!isResult || mobile">
      <summary>{{ isResult ? 'Условия измерения' : 'Все поля' }}</summary>
      <dl v-if="isResult" class="kv"><template v-for="[k, v] in ctx.rows" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template></dl>
      <dl v-else class="kv"><template v-for="[k, v] in fields" :key="k"><dt>{{ fieldLabel(k) }}</dt><dd>{{ valueLabel(k, v) }}</dd></template></dl>
    </details>
    <p v-if="item.note && isResult" class="note__small">{{ item.note }}</p>

    <footer v-if="editable && !mobile" class="note__foot">
      <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="emit('edit')">Изменить</button>
      <button class="btn btn--sm btn--ghost btn--danger" type="button" :disabled="busy" @click="remove">Удалить</button>
    </footer>
  </div>
</template>

<style>
/* заметка на полях: имя показателя и номер записи, крупное значение, условия, затем источник с решением */
.note { width: 100%; padding: 14px 16px 10px; background: var(--float); border-radius: 10px; box-shadow: var(--shadow); }
.note--sheet { padding: 0; background: none; border-radius: 0; box-shadow: none; }
.note__head { display: flex; align-items: baseline; gap: 10px; }
.note__name { font-weight: 600; }
.note__id { margin-left: auto; font-size: 13px; color: var(--pencil); }
.note__value { margin-top: 2px; font-size: var(--t-32); line-height: 38px; font-weight: 600; letter-spacing: -0.025em; }
.note__ctx { margin-top: 2px; color: var(--pencil); }
.note__small { margin-top: 6px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.note__src { margin-top: 14px; padding-top: 12px; box-shadow: inset 0 1px 0 var(--rule); }
.note--sheet .note__src { margin-top: 4px; padding-top: 0; box-shadow: none; }
.note__src .crop, .note__src .quote { margin-bottom: 10px; }
.note__where { font-size: 13px; line-height: 18px; color: var(--pencil); }
.note__decide { display: flex; gap: 6px; margin-top: 10px; }
.note__decided { margin-top: 8px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.note__missing { color: var(--danger); font-size: 13px; line-height: 18px; }
.note__issues { margin-top: 14px; padding-top: 12px; box-shadow: inset 0 1px 0 var(--rule); display: flex; flex-direction: column; gap: 12px; }
.note__more { margin-top: 12px; }
.note__more summary { display: flex; align-items: center; gap: 8px; height: 28px; color: var(--pencil); font-size: 13px; list-style: none; cursor: pointer; }
.note__more summary::-webkit-details-marker { display: none; }
.note__more summary::after { content: ""; width: 5px; height: 5px; border: solid currentColor; border-width: 0 1.5px 1.5px 0; transform: rotate(45deg) translateY(-2px); transition: transform 160ms var(--ease); }
.note__more[open] summary::after { transform: rotate(225deg) translateY(-1px); }
.note__more summary:hover { color: var(--ink); }
.note__more .kv { margin: 6px 0 4px; }
.note__foot { display: flex; gap: 2px; margin: 8px -6px 0; }
@media (max-width: 719px) {
  .note__decide .btn { flex: 1; }
}
</style>
