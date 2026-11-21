import { ID_FIELD, fieldLabel, valueLabel } from './labels.js'
import { fmtResult } from './format.js'

export const natural = (a, b) => String(a).localeCompare(String(b), 'ru', { numeric: true })
export const MAIN_FIELDS = { solar_result: ['device_id', 'measurement_id', 'metric_name', 'metric_value', 'metric_unit', 'aggregation'], rag_result: ['config_id', 'dataset_id', 'task_id', 'experiment_id', 'metric_name', 'metric_value', 'metric_unit', 'metric_k'], material: ['material_class', 'name'], device: ['device_type', 'absorber_material_id', 'architecture'], measurement: ['device_id', 'measurement_type'], configuration: ['rag_variant', 'retrieval_method', 'generator_model'], dataset: ['dataset_name', 'dataset_version', 'data_split'], task: ['task_type'], experiment: ['config_id', 'dataset_id', 'task_id'], layer: ['device_id', 'material_id', 'layer_order', 'role'] }
export const sortItems = (type, rows = []) => [...rows].sort((a, b) => natural(a[ID_FIELD[type]], b[ID_FIELD[type]]))
export const evidenceOf = (graph, id) => graph?.evidence?.find(e => e.entity_id === id)
export const pinLabel = (type, item) => type?.endsWith('_result') ? `${item?.metric_name} ${fmtResult(item)}` : item?.[ID_FIELD[type]] || ''
export function rowText(type, item) {
  const fields = (MAIN_FIELDS[type] || []).filter(k => item[k] != null)
  return { title: item.name || item.dataset_name || item.metric_name || item[ID_FIELD[type]], sub: fields.map(k => `${fieldLabel(k)}: ${valueLabel(k, item[k])}`).join(' · ') }
}
export function quoteParts(fragment, raw) {
  const text = fragment || ''
  const at = raw ? text.indexOf(String(raw)) : -1
  return at < 0 ? [{ text }] : [{ text: text.slice(0, at) }, { text: String(raw), hit: true }, { text: text.slice(at + String(raw).length) }]
}
export function resultContext(type, item, graph) {
  const rows = []
  for (const entity of ['device', 'measurement', 'material', 'configuration', 'dataset', 'task', 'experiment']) {
    const id = item[ID_FIELD[entity]]
    const linked = graph?.entities?.[entity]?.find(e => e[ID_FIELD[entity]] === id)
    if (linked) for (const [key, value] of Object.entries(linked)) if (value != null && !key.startsWith('source_')) rows.push([fieldLabel(key), valueLabel(key, value)])
  }
  return { rows }
}
