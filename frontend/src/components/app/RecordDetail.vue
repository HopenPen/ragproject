<!-- Назначение файла: карточка выбранной записи: значение как в статье и нормализованное, источник с цитатой,
     решение по источнику, замечания, условия измерения, правка и удаление (новая версия графа с причиной). -->
<script setup>
import { computed, ref } from 'vue'
import { Pencil, Trash2, Check, X } from '@lucide/vue'
import Chip from '../ui/Chip.vue'
import IssueCard from './IssueCard.vue'
import SourceCrop from './SourceCrop.vue'
import { publications } from '../../api/index.js'
import { askReason } from '../../stores/dialogs.js'
import { notify } from '../../stores/toasts.js'
import { EVIDENCE_REVIEW, METHOD, ID_FIELD, fieldLabel, valueLabel } from '../../lib/labels.js'
import { evidenceOf, quoteParts, resultContext } from '../../lib/records.js'
import { fmtNum, fmtValue, fmtUnit } from '../../lib/format.js'

const props = defineProps({
  type: String, item: Object, graph: Object, etag: String, profile: String, publicationId: String, documentId: String,
  issues: { type: Array, default: () => [] }, editable: Boolean, mobile: Boolean
})
const emit = defineEmits(['edit', 'changed', 'issues-changed', 'stale'])
const busy = ref(false)
const isResult = computed(() => props.type === 'solar_result' || props.type === 'rag_result')
const ev = computed(() => evidenceOf(props.graph, props.item[ID_FIELD[props.type]]))
const ctx = computed(() => isResult.value ? resultContext(props.type, props.item, props.graph) : { rows: [] })
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
  <div class="rdetail">
    <section v-if="isResult && (extra || rawDiffers || normDiffers || item.result_origin === 'cited' || item.duplicate_of)" class="rdetail__value">
      <p v-if="extra" class="rdetail__what">{{ extra }}</p>
      <p v-if="rawDiffers || normDiffers" class="rdetail__raw">
        <template v-if="rawDiffers">В статье: <span class="num">{{ item.raw_value }}</span> {{ item.raw_unit ? fmtUnit(item.raw_unit) : '' }}. </template>
        <template v-if="normDiffers">Нормализовано: <span class="num">{{ fmtValue(item.normalized_value, item.normalized_unit) }}</span>.</template>
      </p>
      <p v-if="item.result_origin === 'cited'" class="rdetail__note">Цитата из другой работы {{ item.cited_publication_id }}: в сравнение с результатами статьи не входит.</p>
      <p v-if="item.duplicate_of" class="rdetail__note">Повтор записи {{ item.duplicate_of }} в другом месте статьи.</p>
    </section>

    <section class="rdetail__src">
      <h4>Источник</h4>
      <template v-if="ev">
        <SourceCrop v-if="mobile && ev.bbox" :document-id="documentId" :page="ev.page" :bbox="ev.bbox" :tone="tone" />
        <blockquote v-if="!(mobile && ev.bbox)" class="quote"><template v-for="(p, i) in quoteParts(ev.fragment, item.raw_value)" :key="i"><mark v-if="p.hit">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template></blockquote>
        <div class="rdetail__line">
          <span class="rdetail__where">стр. {{ ev.page }}<template v-if="ev.table">, {{ ev.table }}</template><template v-if="ev.figure">, {{ ev.figure }}</template><template v-if="['ocr', 'vision'].includes(ev.method)">, {{ METHOD[ev.method] }}</template>, уверенность {{ fmtNum(ev.confidence, 2) }}</span>
          <span class="grow" />
          <template v-if="editable && ev.review_status === 'pending'">
            <button class="btn btn--sm" type="button" :disabled="busy" @click="review('confirmed')"><Check />Верно</button>
            <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="review('rejected')"><X />Не тот</button>
          </template>
          <Chip v-else-if="ev.review_status !== 'pending'" :tone="EVIDENCE_REVIEW[ev.review_status]?.tone" :text="EVIDENCE_REVIEW[ev.review_status]?.text" />
        </div>
        <p v-if="ev.review_reason" class="rdetail__note">{{ ev.reviewed_by }}: {{ ev.review_reason }}</p>
      </template>
      <p v-else class="rdetail__missing">Место в статье не найдено<template v-if="item.source_figure">: значение прочитано с рисунка ({{ item.source_figure }})</template>. Без источника запись не попадёт в строгую выгрузку.</p>
    </section>

    <section v-if="openIssues.length" class="rdetail__issues">
      <h4>Замечания</h4>
      <IssueCard v-for="i in openIssues" :key="i.id" :issue="i" :editable="editable" compact @changed="emit('issues-changed')" />
    </section>

    <section v-if="ctx.rows.length" class="rdetail__ctx">
      <h4>Условия</h4>
      <dl class="kv"><template v-for="[k, v] in ctx.rows" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template></dl>
    </section>
    <section v-else-if="!isResult" class="rdetail__ctx">
      <dl class="kv"><template v-for="[k, v] in fields" :key="k"><dt>{{ fieldLabel(k) }}</dt><dd>{{ valueLabel(k, v) }}</dd></template></dl>
    </section>
    <p v-if="item.note && isResult" class="rdetail__note">{{ item.note }}</p>

    <footer v-if="editable && !mobile" class="rdetail__actions">
      <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="emit('edit')"><Pencil />Изменить</button>
      <button class="btn btn--sm btn--ghost btn--danger" type="button" :disabled="busy" @click="remove"><Trash2 />Удалить</button>
    </footer>
  </div>
</template>

<style>
/* карточка записи: только то, чего нет в строке; источник и решение по нему одной строкой */
.rdetail { display: flex; flex-direction: column; gap: 14px; }
.rdetail h4 { margin-bottom: 6px; font-size: 12px; line-height: 16px; font-weight: 400; color: var(--u-soft); }
.rdetail__what { color: var(--u-text-2); }
.rdetail__raw, .rdetail__note { margin-top: 4px; font-size: 12px; line-height: 16px; color: var(--u-muted); }
.rdetail__line { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.rdetail__where { font-size: 12px; line-height: 16px; color: var(--u-muted); }
.rdetail__missing { display: flex; gap: 10px; padding: 10px 12px; border-radius: 8px; background: var(--u-bg); box-shadow: inset 0 0 0 1px var(--u-line-2); color: var(--u-text-2); }
.rdetail__missing::before { content: ""; width: 6px; height: 6px; margin-top: 7px; border-radius: 50%; background: var(--red); flex: none; }
.rdetail__issues { display: flex; flex-direction: column; gap: 8px; }
.rdetail__issues h4 { margin-bottom: 0; }
.rdetail__src .crop { margin-bottom: 4px; }
.rdetail__actions { display: flex; gap: 4px; margin-left: -8px; }
@media (max-width: 719px) {
  .rdetail__where { flex-basis: 100%; }
  .rdetail__line .grow { display: none; }
  .rdetail__line .btn { flex: 1; }
}
</style>
