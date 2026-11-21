<!-- Назначение файла: сравнение выбранных результатов (POST /corpora/{id}/comparisons): группы сопоставимых
     по условиям профиля и исключённые с причиной. В каждой группе полосы одной метрики от нуля, как доска
     сравнения: одна серия, подписи и значения в строке, цвет полосы одинаковый (цвет не зависит от места). -->
<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Drawer from '../ui/Drawer.vue'
import Metric from '../ui/Metric.vue'
import { catalog } from '../../api/index.js'
import { notify } from '../../stores/toasts.js'
import { profileTitle } from '../../lib/labels.js'
import { fmtResult, countText } from '../../lib/format.js'

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

// длина полосы от нуля: значения одной метрики при одинаковых условиях, отрицательных в профилях нет
function barsOf (g) {
  const sorted = [...g.results].sort((a, b) => b.metric_value - a.metric_value)
  const max = Math.max(...sorted.map(r => Math.abs(Number(r.metric_value)) || 0)) || 1
  return sorted.map(r => ({ r, w: `${Math.max(1.5, Math.abs(Number(r.metric_value)) / max * 100)}%` }))
}
const groups = computed(() => (data.value?.groups || []).map(g => ({ ...g, bars: barsOf(g) })))
const DEFAULTS = new Set(['без сертификации', 'начальное значение', 'не применяется', 'без k'])
const condText = g => g.conditions.filter(c => c.field !== 'metric' && !DEFAULTS.has(c.value)).map(c => c.value).join(', ')
const metricOf = g => g.results[0]
function openResult (r) {
  router.push({ name: 'article', params: { corpusId: props.corpusId, documentId: r.document_id }, query: { profile: props.profile, record: r.result_id } })
  emit('close')
}
</script>

<template>
  <Drawer :open="open" title="Сравнение" width="600px" @close="emit('close')">
    <template #subtitle><p class="cmp__sub">{{ profileTitle(profile) }}, {{ countText(refs.length, ['значение', 'значения', 'значений']) }}</p></template>
    <div v-if="loading" class="cmp__ghost"><span v-for="i in 4" :key="i" class="skeleton" :style="{ width: `${90 - i * 14}%`, height: '10px' }" /></div>
    <template v-else-if="data">
      <p v-if="!groups.length" class="cmp__none">Сопоставимых пар нет: выбранные значения получены в разных условиях. Причины ниже.</p>
      <section v-for="(g, gi) in groups" :key="g.key" class="cmp__group">
        <header class="cmp__head">
          <h3><Metric :name="metricOf(g).metric_name" :k="metricOf(g).metric_k" /></h3>
          <span class="cmp__n">{{ groups.length > 1 ? `группа ${gi + 1}, ` : '' }}{{ countText(g.results.length, ['значение', 'значения', 'значений']) }}</span>
        </header>
        <p v-if="condText(g)" class="cmp__cond">{{ condText(g) }}</p>
        <ul class="cmp__bars">
          <li v-for="b in g.bars" :key="b.r.ref.publication_id + b.r.result_id">
            <button type="button" class="cmp__row" :title="`Открыть ${b.r.publication_code} на этом значении`" @click="openResult(b.r)">
              <span class="cmp__code"><b>{{ b.r.publication_code }}</b> {{ b.r.result_id }}<template v-if="b.r.device_id">, {{ b.r.device_id }}</template><template v-if="b.r.config_id">, {{ b.r.config_id }}</template></span>
              <span class="cmp__track"><i :style="{ width: b.w }" /></span>
              <span class="cmp__val num">{{ fmtResult(b.r) }}</span>
            </button>
          </li>
        </ul>
      </section>
      <section v-if="data.excluded.length" class="cmp__excl">
        <h3>Не сравниваются</h3>
        <ul>
          <li v-for="x in data.excluded" :key="x.ref.publication_id + x.result_id" class="cmp__x">
            <button type="button" class="cmp__xrow" @click="openResult(x)">
              <b>{{ x.publication_code }}</b><span class="cmp__xid">{{ x.result_id }}, <Metric :name="x.metric_name" :k="x.metric_k" /></span>
              <span class="grow" /><span class="num cmp__val">{{ fmtResult(x) }}</span>
            </button>
            <p class="cmp__why">{{ x.reasons.join('. ') }}</p>
          </li>
        </ul>
      </section>
    </template>
  </Drawer>
</template>

<style>
.cmp__sub { margin-top: 2px; color: var(--pencil); }
.cmp__ghost { display: flex; flex-direction: column; gap: 18px; padding: 12px 0 0 150px; }
.cmp__none { margin-bottom: 20px; color: var(--pencil); max-width: 60ch; }
.cmp__group + .cmp__group, .cmp__group + .cmp__excl { margin-top: 24px; padding-top: 20px; box-shadow: inset 0 1px 0 var(--rule); }
.cmp__head { display: flex; align-items: baseline; gap: 12px; }
.cmp__head h3 { font-size: var(--t-17); line-height: 24px; font-weight: 600; letter-spacing: -0.01em; }
.cmp__n { color: var(--pencil); }
.cmp__cond { margin-top: 2px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.cmp__bars { margin-top: 12px; }
/* полосы от общего нуля: тонкая отметка, скруглён только конец данных, нулевая линия слева */
.cmp__row { display: grid; grid-template-columns: 150px minmax(0, 1fr) 88px; align-items: center; gap: 14px; width: calc(100% + 16px); height: 34px; margin: 0 -8px; padding: 0 8px; border: 0; border-radius: 6px; background: none; text-align: left; transition: background-color 120ms var(--ease); }
.cmp__row:hover { background: var(--hover); }
.cmp__code { color: var(--pencil); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cmp__code b { color: var(--ink); font-weight: 600; }
.cmp__track { position: relative; height: 34px; display: flex; align-items: center; box-shadow: inset 1px 0 0 var(--rule-mid); }
.cmp__track i { display: block; height: 10px; border-radius: 0 4px 4px 0; background: color-mix(in oklab, var(--ink) 72%, var(--desk)); }
.cmp__val { text-align: right; font-weight: 600; white-space: nowrap; }
.cmp__excl h3 { font-size: var(--t-14); line-height: 20px; font-weight: 600; margin-bottom: 6px; }
.cmp__x { padding: 6px 0 10px; }
.cmp__x + .cmp__x { box-shadow: inset 0 1px 0 var(--rule); }
.cmp__xrow { display: flex; align-items: baseline; gap: 8px; width: calc(100% + 16px); margin: 0 -8px; padding: 4px 8px; border: 0; border-radius: 6px; background: none; text-align: left; }
.cmp__xrow:hover { background: var(--hover); }
.cmp__xrow b { font-weight: 600; }
.cmp__xid { color: var(--pencil); }
.cmp__why { font-size: 13px; line-height: 18px; color: var(--pencil); max-width: 62ch; }
</style>
