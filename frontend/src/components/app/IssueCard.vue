<!-- Назначение файла: замечание научной проверки: правило, числа, место в статье и решение редактора
     (подтвердить, отклонить с причиной, вернуть в открытые). Исходное значение в графе не меняется. -->
<script setup>
import { computed, ref } from 'vue'
import { Check, X, RotateCcw } from '@lucide/vue'
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
  ['reported', 'calculated', 'PCE в статье', 'PCE по Voc, Jsc, FF', '%'],
  ['jsc_jv', 'jsc_eqe', 'Jsc по J-V', 'Jsc по EQE', 'мА/см²'],
  ['Voc', 'Eg', 'Voc', 'Eg/q', 'В'],
  ['voc', 'eg', 'Voc', 'Eg/q', 'В']
]
const nums = computed(() => ({ ...props.issue, ...(props.issue.numbers || {}) }))
const isNum = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v))
// строка с сервера ('21.0') сохраняет свою точность, число из демо показывается не точнее сотых
const pairNum = v => {
  const d = typeof v === 'string' && v.includes('.') ? Math.min(3, v.split('.')[1].length) : null
  return new Intl.NumberFormat('ru-RU', d === null ? { maximumFractionDigits: 2 } : { minimumFractionDigits: d, maximumFractionDigits: d }).format(Number(v))
}
const pair = computed(() => {
  for (const [a, b, ka, kb, unit] of PAIRS) {
    if (isNum(nums.value[a]) && isNum(nums.value[b])) return [{ k: ka, v: pairNum(nums.value[a]), unit }, { k: kb, v: pairNum(nums.value[b]), unit }]
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
    placeholder: status === 'confirmed' ? 'Например: расхождение есть в самой статье' : 'Например: значение FF взято из другой таблицы'
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
  <article class="issue" :class="[`issue--${issue.severity}`, `issue--${issue.status}`, { 'issue--compact': compact }]">
    <header class="issue__head">
      <span class="issue__dot" :title="sev.text" aria-hidden="true" />
      <h3 class="issue__rule">
        <button v-if="showDoc" type="button" class="issue__link" @click="emit('open', issue)">{{ ruleLabel(issue.rule) }}</button>
        <template v-else>{{ ruleLabel(issue.rule) }}</template>
      </h3>
      <span v-if="issue.severity === 'error'" class="issue__sev">{{ sev.text }}</span>
      <Chip v-if="issue.status !== 'open'" :tone="st.tone" :text="st.text" />
    </header>
    <p class="issue__text">{{ issue.description }}</p>
    <div v-if="pair && !compact" class="issue__pair">
      <div v-for="x in pair" :key="x.k" class="issue__rec"><span class="issue__k">{{ x.k }}</span><span class="issue__v num">{{ x.v }} {{ x.unit }}</span></div>
      <p v-if="delta" class="issue__delta">{{ delta }}</p>
    </div>
    <p v-if="issue.review" class="issue__review">{{ issue.review.by }}, {{ fmtDate(issue.review.at) }}: {{ issue.review.reason }}</p>
    <footer v-if="editable || !compact" class="issue__foot">
      <span class="issue__meta"><template v-if="showDoc"><b>{{ issue.publication_code }}</b>, </template><template v-if="issue.source_page">стр. {{ issue.source_page }}, </template>записи {{ issue.record_ids.join(', ') }}</span>
      <span class="grow" />
      <template v-if="editable">
        <template v-if="issue.status === 'open'">
          <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('confirmed')"><Check />Подтвердить</button>
          <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('dismissed')"><X />Отклонить</button>
        </template>
        <button v-else class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('open')"><RotateCcw />Вернуть</button>
      </template>
    </footer>
  </article>
</template>

<style>
/* замечание: точка правила и название-ссылка, текст, пара чисел; решения тихими кнопками в нижней строке */
.issue { padding: 12px 12px 8px 16px; background: var(--u-bg); border: 1px solid var(--u-border); border-radius: 12px; }
.issue__head { display: flex; align-items: center; gap: 8px; min-width: 0; }
.issue__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ochre); flex: none; }
.issue--error .issue__dot { background: var(--red); }
.issue--info .issue__dot, .issue--dismissed .issue__dot { background: var(--u-soft); }
.issue__rule { flex: 1; min-width: 0; font-size: 13px; line-height: 20px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.issue__sev { flex: none; color: var(--danger); font-size: 12px; }
.issue__text { margin-top: 4px; color: var(--u-text-2); }
.issue__pair { display: grid; grid-template-columns: repeat(2, minmax(0, 200px)) auto; align-items: center; gap: 8px 12px; margin-top: 10px; }
.issue__rec { display: grid; gap: 2px; padding: 6px 10px; border-radius: 8px; background: var(--u-fill); border: 1px solid var(--u-line); }
.issue__k { font-size: 12px; line-height: 16px; color: var(--u-muted); }
.issue__v { font-size: 15px; line-height: 20px; font-weight: 500; }
.issue__delta { font-weight: 500; }
.issue__review { margin-top: 8px; padding-left: 10px; box-shadow: inset 2px 0 0 var(--u-line-2); font-size: 12px; line-height: 16px; color: var(--u-muted); }
.issue__foot { display: flex; align-items: center; gap: 4px; min-height: 28px; margin-top: 6px; }
.issue__meta { min-width: 0; font-size: 12px; line-height: 16px; color: var(--u-soft); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.issue__meta b { color: var(--u-text-2); font-weight: 500; }
.issue__link { max-width: 100%; padding: 0; border: 0; background: none; font: inherit; color: inherit; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-decoration: underline; text-decoration-color: transparent; text-underline-offset: 3px; transition: text-decoration-color 160ms var(--u-ease); }
.issue__link:hover { text-decoration-color: currentColor; }
.issue--compact { padding: 8px 8px 4px 12px; }
.issue--compact .issue__text { font-size: 12px; line-height: 16px; }
.issue--compact .issue__meta { display: none; }
@media (max-width: 719px) {
  .issue__rule, .issue__link { white-space: normal; }
  .issue__pair { grid-template-columns: 1fr 1fr; }
  .issue__delta { grid-column: 1 / 3; }
  .issue__foot { flex-wrap: wrap; }
  .issue__meta { flex-basis: 100%; }
  .issue__foot .grow { display: none; }
  .issue__foot .btn { flex: 1; }
}
</style>
