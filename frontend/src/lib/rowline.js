// Назначение файла: подпись записи в оглавлении статьи и в заметке на полях: главное слово и короткое
// уточнение через запятую. Для результатов уточнение берётся из связанного прибора, измерения или
// конфигурации в графе, причём только отличия от обычного случая (лучший прибор, обратная развёртка).
// Зависит только от ID_FIELD, valueLabel, fmtNum и fmtUnit, поэтому одинаково работает с демо и с сервером.
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
