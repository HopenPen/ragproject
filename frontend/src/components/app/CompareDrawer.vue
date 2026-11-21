<!-- Назначение файла: сравнение выбранных результатов (POST /corpora/{id}/comparisons): группы сопоставимых
     по условиям профиля и исключённые с причиной. В каждой группе полосы одной метрики от нуля, как доска
     сравнения на лендинге: одна серия, подписи и значения в строке, наибольшее значение выделено акцентом. -->
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
  return sorted.map((r, i) => ({ r, top: i === 0 && sorted.length > 1, w: `${Math.max(2, Math.abs(Number(r.metric_value)) / max * 100)}%` }))
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
  <Drawer :open="open" title="Сравнение результатов" width="600px" @close="emit('close')">
    <template #subtitle><p class="cmp__sub">{{ profileTitle(profile) }}, {{ countText(refs.length, ['результат', 'результата', 'результатов']) }}</p></template>
    <div v-if="loading" class="skeleton" style="height: 260px; border-radius: 12px" />
    <template v-else-if="data">
      <p v-if="!groups.length" class="cmp__none">Сопоставимых пар нет: все выбранные результаты различаются условиями. Причины ниже.</p>
      <section v-for="(g, gi) in groups" :key="g.key" class="cmp__group">
        <header class="cmp__head">
          <h3><Metric :name="metricOf(g).metric_name" :k="metricOf(g).metric_k" /></h3>
          <span class="cmp__n">{{ groups.length > 1 ? `группа ${gi + 1}, ` : '' }}{{ countText(g.results.length, ['результат', 'результата', 'результатов']) }}</span>
        </header>
        <p v-if="condText(g)" class="cmp__cond">{{ condText(g) }}</p>
        <ul class="cmp__bars">
          <li v-for="b in g.bars" :key="b.r.ref.publication_id + b.r.result_id">
            <button type="button" class="cmp__row" :class="{ 'is-top': b.top }" @click="openResult(b.r)">
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
            <p v-for="(why, i) in x.reasons" :key="i" class="cmp__why">{{ why }}</p>
          </li>
        </ul>
      </section>
    </template>
  </Drawer>
</template>

<style>
.cmp__sub { margin-top: 2px; font-size: 12px; line-height: 16px; color: var(--u-muted); }
.cmp__none { padding: 10px 12px; margin-bottom: 16px; border-radius: 8px; background: var(--u-fill); box-shadow: inset 0 0 0 1px var(--u-line); color: var(--u-text-2); }
.cmp__group + .cmp__group, .cmp__group + .cmp__excl { margin-top: 16px; padding-top: 16px; box-shadow: inset 0 1px 0 var(--u-line); }
.cmp__head { display: flex; align-items: baseline; gap: 10px; }
.cmp__head h3 { font-size: 15px; line-height: 20px; font-weight: 500; }
.cmp__n { color: var(--u-soft); }
.cmp__cond { margin-top: 2px; font-size: 12px; line-height: 16px; color: var(--u-muted); }
.cmp__bars { margin-top: 10px; }
.cmp__row { display: grid; grid-template-columns: 150px minmax(0, 1fr) 84px; align-items: center; gap: 12px; width: 100%; height: 32px; padding: 0 6px; border: 0; border-radius: 6px; background: none; text-align: left; transition: background-color 160ms var(--u-ease); }
.cmp__row:hover { background: var(--u-fill); }
.cmp__code { color: var(--u-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cmp__code b { color: var(--u-ink); font-weight: 500; }
.cmp__track { height: 8px; border-radius: 4px; background: var(--u-fill-2); overflow: hidden; }
.cmp__track i { display: block; height: 100%; border-radius: 4px; background: var(--u-ink); opacity: .45; }
.cmp__row.is-top .cmp__track i { background: var(--u-accent); opacity: 1; }
.cmp__val { text-align: right; font-weight: 500; white-space: nowrap; }
.cmp__excl h3 { font-size: 13px; line-height: 20px; font-weight: 500; margin-bottom: 4px; }
.cmp__x + .cmp__x { box-shadow: inset 0 1px 0 var(--u-line); }
.cmp__x { padding: 6px 0 8px; }
.cmp__xrow { display: flex; align-items: baseline; gap: 8px; width: 100%; padding: 4px 6px; border: 0; border-radius: 6px; background: none; text-align: left; }
.cmp__xrow:hover { background: var(--u-fill); }
.cmp__xrow b { font-weight: 500; }
.cmp__xid { color: var(--u-muted); }
.cmp__why { display: flex; gap: 8px; padding: 0 6px; font-size: 12px; line-height: 16px; color: var(--u-text-2); }
.cmp__why::before { content: ""; width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--ochre); flex: none; }
</style>
