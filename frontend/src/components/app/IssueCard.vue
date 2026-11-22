<!-- Назначение файла: замечание проверки. Набрано строками без рамки: правило, пояснение, пара чисел
     с расхождением и решения. Цветом выделено только слово «Ошибка»; решения видны всегда. Сжатый вид
     стоит внутри заметки к записи. -->
<script setup>
import { computed, ref } from 'vue'
import Chip from '../ui/Chip.vue'
import { catalog } from '../../api/index.js'
import { askReason } from '../../stores/dialogs.js'
import { notify } from '../../stores/toasts.js'
import { SEVERITY, ISSUE_STATUS, ruleLabel } from '../../lib/labels.js'
import { fmtDate, fmtNum } from '../../lib/format.js'

const props = defineProps({ issue: Object, editable: Boolean, showDoc: Boolean, compact: Boolean })
const emit = defineEmits(['changed', 'open'])
const busy = ref(false)
const sev = computed(() => SEVERITY[props.issue.severity] || SEVERITY.warning)
const st = computed(() => ISSUE_STATUS[props.issue.status] || ISSUE_STATUS.open)
// пара чисел правила, как в карточке замечания на лендинге: значение из статьи и пересчёт.
// Поля приходят из numbers (демо) или из details сервера (reported, calculated, voc, eg, relative_difference).
const PAIRS = [
  ['reported', 'calculated', 'в статье', 'по Voc, Jsc и FF', '%'],
  ['jsc_jv', 'jsc_eqe', 'по J-V', 'по EQE', 'мА/см²'],
  ['Voc', 'Eg', 'Voc', 'Eg/q', 'В'],
  ['voc', 'eg', 'Voc', 'Eg/q', 'В']
]
const nums = computed(() => ({ ...props.issue, ...(props.issue.numbers || {}) }))
const isNum = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v))
// строка с сервера ('21.0') задаёт точность: пересчёт показывается с тем же числом знаков, что и значение статьи.
// Если точность неизвестна (числа из демо), не точнее сотых.
const decimals = v => typeof v === 'string' && v.includes('.') ? Math.min(3, v.split('.')[1].length) : null
const pairNum = (v, d) => new Intl.NumberFormat('ru-RU', d === null ? { maximumFractionDigits: 2 } : { minimumFractionDigits: d, maximumFractionDigits: d }).format(Number(v))
const pair = computed(() => {
  for (const [a, b, ka, kb, unit] of PAIRS) {
    const va = nums.value[a]
    const vb = nums.value[b]
    if (isNum(va) && isNum(vb)) {
      const d = decimals(va) ?? decimals(vb)
      return [{ k: ka, v: pairNum(va, d), unit }, { k: kb, v: pairNum(vb, d), unit }]
    }
  }
  return null
})
const delta = computed(() => {
  const n = nums.value
  const d = isNum(n.delta_pct) ? Number(n.delta_pct) : isNum(n.relative_difference) ? Number(n.relative_difference) * 100 : null
  if (d === null) return ''
  return `Расхождение ${fmtNum(d, 1)} %` + (isNum(n.threshold_pct) ? ` при допуске ${fmtNum(Number(n.threshold_pct), 1)} %` : '')
})

async function decide (status) {
  const reason = status === 'open' ? '' : await askReason({
    title: status === 'confirmed' ? 'Подтвердить замечание' : 'Отклонить замечание',
    text: status === 'confirmed' ? 'Замечание останется в выгрузке (issues.csv), значение в статье не меняется.' : 'Замечание уйдёт из выгрузки. При желании поясните, почему правило здесь не применимо.',
    confirm: status === 'confirmed' ? 'Подтвердить' : 'Отклонить',
    placeholder: status === 'confirmed' ? 'Например: "Расхождение есть в самой статье"' : 'Например: "Значение FF взято из другой таблицы"'
  })
  if (reason === null) return
  busy.value = true
  try {
    await catalog.reviewIssue(props.issue.id, { status, reason }, props.issue._etag)
    notify.ok(status === 'confirmed' ? 'Замечание подтверждено' : status === 'dismissed' ? 'Замечание отклонено' : 'Замечание снова открыто')
    emit('changed')
  } catch (e) { notify.error(e) } finally { busy.value = false }
}
</script>

<template>
  <article class="finding" :class="[`finding--${issue.severity}`, `finding--${issue.status}`, { 'finding--compact': compact, 'finding--doc': showDoc }]">
    <p v-if="showDoc" class="finding__doc"><b>{{ issue.publication_code }}</b><span v-if="issue.source_page">стр. {{ issue.source_page }}</span></p>
    <div class="finding__body">
      <header class="finding__head">
        <h3 class="finding__rule">
          <button v-if="showDoc" type="button" class="finding__link" @click="emit('open', issue)">{{ ruleLabel(issue.rule) }}</button>
          <template v-else>{{ ruleLabel(issue.rule) }}</template>
        </h3>
        <span v-if="issue.severity === 'error'" class="finding__sev">Ошибка</span>
      </header>
      <p class="finding__text">{{ issue.description }}</p>
      <p v-if="pair && !compact" class="finding__nums">
        <span v-for="x in pair" :key="x.k" class="finding__num"><b class="num">{{ x.v }} {{ x.unit }}</b>{{ x.k }}</span>
        <span v-if="delta" class="finding__delta">{{ delta }}</span>
      </p>
      <p v-if="issue.review" class="finding__review">{{ st.text }}: {{ issue.review.by }}, {{ fmtDate(issue.review.at) }}. {{ issue.review.reason }}</p>
      <footer v-if="editable" class="finding__foot">
        <template v-if="issue.status === 'open'">
          <button class="btn btn--sm" type="button" :disabled="busy" @click="decide('confirmed')">Подтвердить</button>
          <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('dismissed')">Отклонить</button>
        </template>
        <button v-else class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('open')">Вернуть в открытые</button>
        <span v-if="!compact && !showDoc && issue.record_ids?.length" class="finding__recs">Записи {{ issue.record_ids.join(', ') }}</span>
      </footer>
    </div>
  </article>
</template>

<style>
.finding { padding: 18px 0 16px; }
.finding__head { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.finding__rule { min-width: 0; font-size: var(--t-17); line-height: 24px; font-weight: 600; letter-spacing: -0.01em; }
.finding__link { padding: 0; border: 0; background: none; font: inherit; color: inherit; text-align: left; text-decoration: underline; text-decoration-color: transparent; text-underline-offset: 4px; text-decoration-thickness: 1px; transition: text-decoration-color 140ms var(--ease); }
.finding__link:hover { text-decoration-color: currentColor; }
.finding__sev { flex: none; font-weight: 600; color: var(--danger); }
.finding--doc { display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: 0 24px; padding: 20px 0 18px; }
.finding__doc { display: flex; flex-direction: column; color: var(--pencil); }
.finding__doc b { font-size: var(--t-17); line-height: 24px; font-weight: 600; color: var(--ink); }
.finding__body { min-width: 0; }
@media (max-width: 719px) {
  .finding--doc { grid-template-columns: minmax(0, 1fr); }
  .finding__doc { flex-direction: row; align-items: baseline; gap: 8px; margin-bottom: 2px; }
  .finding__doc b { font-size: var(--t-14); line-height: 20px; }
}
.finding__text { margin-top: 4px; max-width: 72ch; color: var(--pencil); }
.finding__nums { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 28px; margin-top: 12px; }
.finding__num { display: inline-flex; align-items: baseline; gap: 8px; color: var(--pencil); }
.finding__num b { font-size: var(--t-21); line-height: 28px; font-weight: 600; letter-spacing: -0.015em; color: var(--ink); }
.finding__delta { color: var(--warn); font-weight: 600; }
.finding--error .finding__delta { color: var(--danger); }
.finding__review { margin-top: 10px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.finding__foot { display: flex; align-items: center; gap: 6px; margin-top: 12px; }
.finding__recs { margin-left: auto; font-size: 13px; color: var(--pencil); }
.finding--dismissed .finding__rule { color: var(--pencil); }
.finding--compact { padding: 0; }
.finding--compact .finding__rule { font-size: 13px; line-height: 18px; }
.finding--compact .finding__text { font-size: 13px; line-height: 18px; }
.finding--compact .finding__foot { margin-top: 8px; }
@media (max-width: 719px) {
  .finding__head { flex-wrap: wrap; }
  .finding__foot .btn { flex: 1; }
}
</style>
