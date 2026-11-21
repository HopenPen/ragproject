<!-- Назначение файла: замечание научной проверки: правило, числа, место в статье и решение редактора
     (подтвердить, отклонить с причиной, вернуть в открытые). Исходное значение в графе не меняется. -->
<script setup>
import { computed, ref } from 'vue'
import { Check, X, RotateCcw, ArrowUpRight } from '@lucide/vue'
import Chip from '../ui/Chip.vue'
import { catalog } from '../../api/index.js'
import { ui } from '../../stores/ui.js'
import { askReason } from '../../stores/dialogs.js'
import { notify } from '../../stores/toasts.js'
import { SEVERITY, ISSUE_STATUS, ruleLabel, profileShort } from '../../lib/labels.js'
import { fmtDate } from '../../lib/format.js'

const props = defineProps({ issue: Object, editable: Boolean, showDoc: Boolean, compact: Boolean })
const emit = defineEmits(['changed', 'open'])
const busy = ref(false)
const sev = computed(() => SEVERITY[props.issue.severity] || SEVERITY.warning)
const st = computed(() => ISSUE_STATUS[props.issue.status] || ISSUE_STATUS.open)

async function decide (status) {
  const reason = status === 'open' ? '' : await askReason({
    title: status === 'confirmed' ? 'Подтвердить замечание' : 'Отклонить замечание',
    text: status === 'confirmed' ? 'Замечание останется в выгрузке (issues.csv), значение в статье не меняется.' : 'Замечание уйдёт из выгрузки. Объясните, почему правило здесь не применимо.',
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
      <Chip :tone="sev.tone" :text="sev.text" />
      <h3 class="issue__rule"><button v-if="showDoc && ui.mobile" type="button" class="issue__link" @click="emit('open', issue)">{{ ruleLabel(issue.rule) }}</button><template v-else>{{ ruleLabel(issue.rule) }}</template></h3>
      <Chip v-if="issue.status !== 'open'" :tone="st.tone" :text="st.text" />
    </header>
    <p class="issue__text">{{ issue.description }}</p>
    <p class="issue__meta muted">
      <template v-if="showDoc"><b>{{ issue.publication_code }}</b><template v-if="!ui.mobile">, {{ profileShort(issue.profile) }}</template>, </template>
      записи {{ issue.record_ids.join(', ') }}<template v-if="issue.source_page">, стр. {{ issue.source_page }}</template>
    </p>
    <p v-if="issue.review" class="issue__review">{{ issue.review.by }}, {{ fmtDate(issue.review.at) }}: {{ issue.review.reason }}</p>
    <footer v-if="(editable && !compact) || showDoc" class="issue__actions">
      <button v-if="showDoc && !ui.mobile" class="btn btn--sm" type="button" @click="emit('open', issue)"><ArrowUpRight />Открыть в статье</button>
      <template v-if="editable">
        <template v-if="issue.status === 'open'">
          <button class="btn btn--sm" type="button" :disabled="busy" @click="decide('confirmed')"><Check />Подтвердить</button>
          <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('dismissed')"><X />Отклонить</button>
        </template>
        <button v-else class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('open')"><RotateCcw />Вернуть в открытые</button>
      </template>
    </footer>
    <footer v-else-if="editable && compact && issue.status === 'open'" class="issue__actions">
      <button class="btn btn--sm" type="button" :disabled="busy" @click="decide('confirmed')"><Check />Подтвердить</button>
      <button class="btn btn--sm btn--ghost" type="button" :disabled="busy" @click="decide('dismissed')"><X />Отклонить</button>
    </footer>
  </article>
</template>

<style>
.issue { padding: 14px 16px; border: 1px solid var(--line); border-left: 3px solid var(--warn-line); border-radius: var(--r-md); background: var(--surface); }
.issue--error { border-left-color: var(--danger-line); }
.issue--info { border-left-color: var(--line-strong); }
.issue--confirmed, .issue--dismissed { border-left-color: var(--line-strong); }
.issue__head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.issue__rule { flex: 1; min-width: 0; font-size: var(--fs-md); font-weight: 600; }
.issue__text { margin-top: 8px; color: var(--ink-2); }
.issue__meta { margin-top: 6px; font-size: var(--fs-sm); }
.issue__meta b { color: var(--ink); font-weight: 600; }
.issue__review { margin-top: 8px; padding-left: 10px; border-left: 2px solid var(--line-strong); font-size: var(--fs-sm); color: var(--muted); }
.issue__actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
.issue__link { padding: 0; border: 0; background: none; font: inherit; color: inherit; text-align: left; cursor: pointer; text-decoration: underline; text-decoration-color: var(--line-strong); text-underline-offset: 3px; }
.issue--compact { padding: 10px 12px; }
@media (max-width: 719px) {
  .issue__actions { display: grid; grid-template-columns: 1fr 1fr; }
  .issue__actions .btn--ghost { box-shadow: inset 0 0 0 1px var(--line-strong); }
}
.issue--compact .issue__rule { font-size: var(--fs-sm); }
.issue--compact .issue__text { font-size: var(--fs-sm); margin-top: 6px; }
</style>
