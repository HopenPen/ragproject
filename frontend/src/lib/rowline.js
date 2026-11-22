// Назначение файла: подпись записи в оглавлении статьи и в заметке на полях: главное слово и короткое
// уточнение через запятую. Для результатов уточнение берётся из связанного прибора, измерения или
// конфигурации в графе, причём только отличия от обычного случая (лучший прибор, обратная развёртка).
// Зависит только от ID_FIELD, valueLabel, fmtNum и fmtUnit, поэтому одинаково работает с демо и с сервером.
// Здесь же подписи строки таблицы результатов: демо отдаёт готовый context (device, intensity, area),
// сервер отдаёт плоские поля строки (device_label, light_intensity, active_area). Раньше таблица читала только
// ключи демо, поэтому на сервере ячейки «Прибор и условия» оставались пустыми.
import { ID_FIELD, valueLabel } from './labels.js'
import { fmtNum, fmtUnit } from './format.js'

const has = v => v !== null && v !== undefined && v !== ''
const join = parts => parts.filter(has).join(', ')
const find = (graph, type, id) => has(id) ? graph?.entities?.[type]?.find(e => e[ID_FIELD[type]] === id) || null : null
const num = (v, unit) => has(v) ? `${fmtNum(v)} ${fmtUnit(unit)}`.trim() : null

export function rowLine (type, it, graph) {
  if (!it) return { title: '', sub: '' }
  switch (type) {
    case 'solar_result': {
      const dev = find(graph, 'device', it.device_id)
      const meas = find(graph, 'measurement', it.measurement_id)
      return {
        title: it.metric_name,
        sub: join([
          dev?.device_label || it.device_id,
          has(it.aggregation) && it.aggregation !== 'champion' ? valueLabel('aggregation', it.aggregation) : null,
          meas?.scan_direction === 'forward' ? 'прямая развёртка' : null,
          meas?.certified === true ? 'сертифицировано' : null,
          has(it.time_point) ? `через ${num(it.time_point, it.time_unit)}` : null
        ])
      }
    }
    case 'rag_result': {
      const cfg = find(graph, 'configuration', it.config_id)
      const ds = find(graph, 'dataset', it.dataset_id)
      return {
        title: it.metric_name,
        sub: join([
          has(it.config_id) ? join([it.config_id, cfg?.retrieval_method]) : (it.result_origin === 'cited' ? 'цитата' : null),
          ds?.dataset_name,
          has(ds?.data_split) && ds.data_split !== 'test' ? `разбиение ${ds.data_split}` : null,
          has(it.duplicate_of) ? `повтор ${it.duplicate_of}` : null
        ])
      }
    }
    case 'device': return { title: it.device_label || it.device_id, sub: join([has(it.device_role) ? valueLabel('device_role', it.device_role) : null, it.architecture, num(it.active_area, it.area_unit)]) }
    case 'measurement': return { title: join([it.measurement_id, it.measurement_type]), sub: join([it.spectrum, num(it.light_intensity, 'mW/cm2'), has(it.scan_direction) ? `развёртка ${valueLabel('scan_direction', it.scan_direction)}` : null, it.certified === true ? 'сертифицировано' : null]) }
    case 'material': return { title: it.material_name_raw || it.name || it.material_id, sub: join([it.material_class, has(it.bandgap_value) ? `Eg ${num(it.bandgap_value, 'эВ')}` : null]) }
    case 'layer': return { title: join([it.device_id, has(it.layer_order) ? `слой ${it.layer_order}` : null]), sub: join([it.layer_material || it.material_id, it.layer_function || it.role, num(it.layer_thickness, it.thickness_unit), it.deposition_method]) }
    case 'configuration': return { title: join([it.config_id, it.retrieval_method || it.rag_variant]), sub: join([has(it.chunk_size) ? `фрагмент ${it.chunk_size}` : null, has(it.top_k) ? `top_k ${it.top_k}` : null, it.reranker_model, it.generator_model]) }
    case 'dataset': return { title: `${it.dataset_name || it.dataset_id}${has(it.dataset_version) ? ' ' + it.dataset_version : ''}`, sub: join([it.data_split, it.language]) }
    case 'task': return { title: it.task_type || it.task_id, sub: it.note || '' }
    case 'experiment': return { title: it.experiment_id, sub: join([it.evaluation_protocol, has(it.baseline_name) ? `база ${it.baseline_name}` : null, it.hardware]) }
    default: return { title: it[ID_FIELD[type]] || '', sub: '' }
  }
}

const pick = (...vals) => vals.find(has)
const SCAN = { reverse: 'обратная развёртка', forward: 'прямая развёртка', average: 'среднее по развёрткам' }
const MEASURE = { EQE: 'EQE', 'MPP tracking': 'отслеживание MPP', stability: 'стабильность' }
const ctxOf = r => ({ ...r, ...(r.context && r.context !== r ? r.context : {}) })

// прибор строки результата: подпись из статьи, иначе код прибора
export function resultDevice (r) {
  const c = ctxOf(r)
  return pick(c.device, c.device_label, c.device_id) || ''
}

// условия измерения солнечного результата, каждое значение с названием: «AM1.5G, 100 мВт/см², площадь 0,09 см², обратная развёртка»
export function resultConditions (r) {
  const c = ctxOf(r)
  const type = c.measurement_type
  const intensity = pick(c.intensity, c.light_intensity)
  const area = pick(c.area, c.active_area)
  return join([
    has(type) && type !== 'J-V' ? (MEASURE[type] || type) : null,
    c.spectrum,
    has(intensity) ? `${fmtNum(intensity)} ${fmtUnit(c.intensity_unit || 'mW/cm2')}` : null,
    has(area) ? `площадь ${fmtNum(area)} ${fmtUnit(c.area_unit || 'cm2')}` : null,
    has(c.scan_direction) ? (SCAN[c.scan_direction] || `развёртка ${c.scan_direction}`) : (type === 'J-V' ? 'развёртка не указана' : null),
    c.certified === true ? 'сертифицировано' : null,
    has(c.temperature) ? `${fmtNum(c.temperature)} °C` : null
  ])
}

// конфигурация и данные RAG-результата: код конфигурации отдельно, остальное через запятую
export function resultSetup (r) {
  const c = ctxOf(r)
  const dataset = pick(c.dataset, has(c.dataset_name) ? `${c.dataset_name}${has(c.dataset_version) ? ' ' + c.dataset_version : ''}` : null)
  return {
    head: pick(c.config, c.config_id) || '',
    rest: join([
      pick(c.retrieval, c.retrieval_method),
      has(c.chunk_size) ? `фрагмент ${c.chunk_size}` : null,
      has(c.top_k) ? `top_k ${c.top_k}` : null,
      pick(c.reranker, c.reranker_model),
      dataset,
      pick(c.split, c.data_split)
    ])
  }
}
