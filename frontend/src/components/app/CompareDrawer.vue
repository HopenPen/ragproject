<!-- Назначение файла: сравнение выбранных результатов (POST /corpora/{id}/comparisons): группы сопоставимых
     по условиям профиля и исключённые с причиной. В каждой группе точечная шкала значений одной метрики:
     одна серия, поэтому без легенды; значения и подписи в списке под шкалой, наведение показывает запись. -->
<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Drawer from '../ui/Drawer.vue'
import Metric from '../ui/Metric.vue'
import { catalog } from '../../api/index.js'
import { notify } from '../../stores/toasts.js'
import { profileTitle } from '../../lib/labels.js'
import { fmtNum, fmtValue, fmtResult, countText } from '../../lib/format.js'

const props = defineProps({ open: Boolean, corpusId: String, profile: String, refs: { type: Array, default: () => [] } })
const emit = defineEmits(['close'])
const router = useRouter()
const data = ref(null)
const loading = ref(false)

watch(() => props.open, async o => {
  if (!o) return
  loading.value = true
  data.value = null
  try { data.value = await catalog.compare(props.corpusId, { profile: props.profile, result_refs: props.refs }) } catch (e) { notify.error(e); emit('close') } finally { loading.value = false }
})

const W = 440
const PAD = 18
function scaleOf (g) {
  const vals = g.results.map(r => r.metric_value)
  let min = Math.min(...vals)
  let max = Math.max(...vals)
  if (min === max) { min -= 1; max += 1 }
  const span = max - min
  min -= span * 0.12
  max += span * 0.12
  const x = v => PAD + (v - min) / (max - min) * (W - PAD * 2)
  // «круглые» деления: шаг 1, 2 или 5 на степень десяти, не больше пяти делений
  const raw = (max - min) / 4
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map(k => k * pow).find(st => st >= raw) || raw
  const ticks = []
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(Number(t.toFixed(6)))
  return { x, ticks }
}
const groups = computed(() => (data.value?.groups || []).map(g => ({ ...g, s: scaleOf(g) })))
const DEFAULTS = new Set(['без сертификации', 'начальное значение', 'не применяется', 'без k'])
const condText = g => g.conditions.filter(c => c.field !== 'metric' && !DEFAULTS.has(c.value)).map(c => c.value).join(', ')
const metricOf = g => g.results[0]
function openResult (r) {
  router.push({ name: 'article', params: { corpusId: props.corpusId, documentId: r.document_id }, query: { profile: props.profile, record: r.result_id } })
  emit('close')
}
</script>

<template>
  <Drawer :open="open" title="Сравнение результатов" width="620px" @close="emit('close')">
    <template #subtitle><p class="muted cmp__sub">{{ profileTitle(profile) }}, {{ countText(refs.length, ['результат', 'результата', 'результатов']) }}</p></template>
    <div v-if="loading" class="skeleton" style="height: 260px" />
    <template v-else-if="data">
      <p v-if="!groups.length" class="cmp__none">Сопоставимых пар нет: все выбранные результаты различаются условиями. Причины ниже.</p>
      <section v-for="(g, gi) in groups" :key="g.key" class="cmp__group">
        <header class="cmp__head">
          <h3><Metric :name="metricOf(g).metric_name" :k="metricOf(g).metric_k" /><span class="muted">, группа {{ gi + 1 }}: {{ countText(g.results.length, ['результат', 'результата', 'результатов']) }}</span></h3>
          <p class="cmp__cond">{{ condText(g) }}</p>
        </header>
        <svg class="cmp__strip" :viewBox="`0 0 ${W} 46`" role="img" :aria-label="`Значения группы ${gi + 1}`">
          <line :x1="PAD" :x2="W - PAD" y1="22" y2="22" class="cmp__axis" />
          <g v-for="t in g.s.ticks" :key="t">
            <line :x1="g.s.x(t)" :x2="g.s.x(t)" y1="18" y2="26" class="cmp__tick" />
            <text :x="g.s.x(t)" y="42" text-anchor="middle" class="cmp__ticklabel">{{ fmtNum(t, 3) }}</text>
          </g>
          <circle v-for="r in g.results" :key="r.ref.publication_id + r.result_id" :cx="g.s.x(r.metric_value)" cy="22" r="6" class="cmp__dot" @click="openResult(r)">
            <title>{{ r.publication_code }} {{ r.result_id }}: {{ fmtResult(r) }}</title>
          </circle>
        </svg>
        <ul class="cmp__list">
          <li v-for="r in [...g.results].sort((a, b) => b.metric_value - a.metric_value)" :key="r.ref.publication_id + r.result_id">
            <button type="button" class="cmp__row" @click="openResult(r)">
              <b>{{ r.publication_code }}</b><span class="muted">{{ r.result_id }}<template v-if="r.device_id">, прибор {{ r.device_id }}</template><template v-if="r.config_id">, {{ r.config_id }}</template></span>
              <span class="grow" /><span class="num cmp__val">{{ fmtResult(r) }}</span>
            </button>
          </li>
        </ul>
      </section>
      <section v-if="data.excluded.length" class="cmp__excl">
        <h3>Не сравниваются</h3>
        <ul>
          <li v-for="x in data.excluded" :key="x.ref.publication_id + x.result_id" class="cmp__x">
            <button type="button" class="cmp__row" @click="openResult(x)">
              <b>{{ x.publication_code }}</b><span class="muted">{{ x.result_id }}, <Metric :name="x.metric_name" :k="x.metric_k" /></span>
              <span class="grow" /><span class="num cmp__val">{{ fmtResult(x) }}</span>
            </button>
            <p v-for="(why, i) in x.reasons" :key="i" class="cmp__why">{{ why }}</p>
          </li>
        </ul>
      </section>
    </template>
  </Drawer>
</template>

<style>
.cmp__sub { margin-top: 2px; font-size: var(--fs-sm); }
.cmp__none { padding: 12px 14px; border-radius: var(--r-md); background: var(--surface-hover); margin-bottom: 16px; }
.cmp__group { padding: 4px 0 20px; border-bottom: 1px solid var(--line); margin-bottom: 18px; }
.cmp__head h3 { font-size: var(--fs-md); font-weight: 600; }
.cmp__head h3 .muted { font-weight: 400; }
.cmp__cond { margin-top: 4px; font-size: var(--fs-sm); color: var(--ink-2); }
.cmp__strip { width: 100%; height: auto; margin: 10px 0 6px; overflow: visible; }
.cmp__axis { stroke: var(--line-strong); stroke-width: 1; }
.cmp__tick { stroke: var(--line-strong); stroke-width: 1; }
.cmp__ticklabel { font: 11px var(--font); fill: var(--muted); font-variant-numeric: tabular-nums; }
.cmp__dot { fill: var(--accent); stroke: var(--surface); stroke-width: 2; cursor: pointer; }
.cmp__dot:hover { r: 8; }
.cmp__list li + li { border-top: 1px solid var(--line); }
.cmp__row { display: flex; align-items: baseline; gap: 8px; width: 100%; padding: 8px 4px; border: 0; background: none; text-align: left; cursor: pointer; border-radius: var(--r-sm); }
.cmp__row:hover { background: var(--surface-hover); }
.cmp__val { font-weight: 500; }
.cmp__excl h3 { font-size: var(--fs-md); font-weight: 600; margin-bottom: 6px; }
.cmp__x { padding: 4px 0 10px; border-top: 1px solid var(--line); }
.cmp__why { padding-left: 4px; font-size: var(--fs-sm); color: var(--warn); }
</style>
