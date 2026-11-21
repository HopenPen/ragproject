const status = (text, tone = 'idle') => ({ text, tone })
export const JOB_STATUS = {
  paused: status('Приостановлено', 'wait'), pause_requested: status('Приостанавливается', 'wait'),
  queued: status('В очереди'), running: status('В работе', 'run'), waiting_review: status('Нужна проверка', 'wait'),
  succeeded: status('Готово', 'ok'), partially_succeeded: status('Частично готово', 'warn'), failed: status('Ошибка', 'error'),
  cancelled: status('Отменено', 'off'), cancel_requested: status('Останавливается', 'wait'), blocked_external_configuration: status('Не было доступа к модели', 'error')
}
export const TERMINAL = new Set(['succeeded', 'partially_succeeded', 'failed', 'cancelled', 'blocked_external_configuration'])
export const DOC_STATUS = { paused: JOB_STATUS.paused, uploaded: status('Загружен'), ready: status('Готово', 'ok'), processing: status('Обработка', 'run'), queued: status('В очереди'), needs_review: status('Нужна проверка', 'wait'), outside: status('Вне тем', 'off'), excluded: status('Вне профиля', 'off'), unreadable: status('Не читается', 'error'), failed: JOB_STATUS.failed, blocked: status('Нужен повтор', 'warn') }
export const JOB_KIND = { process: 'Обработка', classify: 'Определение темы', validate: 'Проверка', export: 'Выгрузка' }
export const STAGE = { inspect: 'Проверка файла', text: 'Текст', render: 'Страницы', ocr: 'Распознавание', classify: 'Определение темы', extract: 'Извлечение', validate: 'Проверка', export: 'Выгрузка', done: 'Завершено', links: 'Связи', sources: 'Источники' }
export const ROLE = { viewer: 'Наблюдатель', editor: 'Редактор', admin: 'Администратор' }
export const LABEL_TO_PROFILE = { solar: 'solar-v1', rag: 'rag-v1' }
export const RESULT_ENTITY = { 'solar-v1': 'solar_result', 'rag-v1': 'rag_result' }
export const ID_FIELD = { material: 'material_id', device: 'device_id', layer: 'layer_id', measurement: 'measurement_id', solar_result: 'result_id', configuration: 'config_id', dataset: 'dataset_id', task: 'task_id', experiment: 'experiment_id', rag_result: 'result_id' }
export const ENTITY = Object.fromEntries([
  ['solar_result', 'результат', 'Результаты'], ['rag_result', 'результат', 'Результаты'], ['material', 'материал', 'Материалы'], ['device', 'прибор', 'Приборы'], ['layer', 'слой', 'Слои'], ['measurement', 'измерение', 'Измерения'], ['configuration', 'конфигурация', 'Конфигурации'], ['dataset', 'набор данных', 'Наборы данных'], ['task', 'задача', 'Задачи'], ['experiment', 'эксперимент', 'Эксперименты']
].map(([key, one, many], order) => [key, { one, many, order }]))
export const EVIDENCE_REVIEW = { pending: status('Не проверен', 'wait'), open: status('Не проверен', 'wait'), confirmed: status('Подтверждён', 'ok'), rejected: status('Отклонён', 'error'), needs_review: status('Нужна проверка', 'wait') }
export const ISSUE_STATUS = { open: status('Открыто', 'warn'), confirmed: status('Подтверждено', 'error'), dismissed: status('Отклонено', 'off') }
export const SEVERITY = { error: status('Ошибка', 'error'), warning: status('Предупреждение', 'warn'), info: status('Информация', 'off') }
export const METHOD = { text: 'текст', table: 'таблица', ocr: 'распознавание', vision: 'по изображению', manual: 'вручную' }
export const REVIEW_KIND = { classification: 'Тема статьи', scope: 'Рамки профиля', candidate: 'Новая версия', source: 'Источник', issue: 'Замечание' }
export const profileTitle = id => id === 'solar-v1' ? 'Солнечные элементы' : id === 'rag-v1' ? 'RAG-системы' : id || 'Не указан'
export const profileShort = id => id === 'solar-v1' ? 'Solar' : id === 'rag-v1' ? 'RAG' : id || ''
const FIELDS = { metric_name: 'Показатель', metric_value: 'Значение', metric_unit: 'Единица', metric_k: 'k метрики', aggregation: 'Агрегация', result_origin: 'Происхождение', raw_value: 'Значение в статье', raw_unit: 'Единица в статье', normalized_value: 'Нормализованное значение', normalized_unit: 'Нормализованная единица', source_page: 'Страница', source_fragment: 'Цитата', source_table: 'Таблица', source_figure: 'Рисунок', note: 'Примечание', device_id: 'Прибор', measurement_id: 'Измерение', material_id: 'Материал', config_id: 'Конфигурация', dataset_id: 'Набор данных', task_id: 'Задача', experiment_id: 'Эксперимент', result_id: 'Код результата', layer_id: 'Код слоя', name: 'Название', material_class: 'Класс материала', device_type: 'Тип прибора', architecture: 'Архитектура', scan_direction: 'Развёртка', spectrum: 'Спектр', intensity: 'Интенсивность', area: 'Площадь', certified: 'Сертификация', dataset_name: 'Набор данных', dataset_version: 'Версия набора', data_split: 'Выборка', generator_model: 'Генератор', retrieval_method: 'Метод поиска', top_k: 'Количество найденных фрагментов', time_point: 'Время', time_unit: 'Единица времени', n_devices: 'Число приборов', spread_value: 'Разброс', sample_size: 'Размер выборки', duplicate_of: 'Повтор записи', extraction_status: 'Статус извлечения' }
export const fieldLabel = name => FIELDS[name] || name?.replaceAll('_', ' ') || ''
export function valueLabel(field, value) {
  if (value == null || value === '') return 'не указано'
  if (Array.isArray(value)) return value.map(v => valueLabel(field, v)).join('; ')
  if (typeof value === 'object') return JSON.stringify(value)
  return ({ true: 'да', false: 'нет', primary: 'результат статьи', cited: 'из другой работы', champion: 'лучший', mean: 'среднее', median: 'медиана', forward: 'прямая', reverse: 'обратная' })[String(value)] || String(value)
}
export const ruleLabel = rule => ({ jv_consistency: 'Сходимость PCE', eqe_consistency: 'Сходимость Jsc по EQE', voc_limit: 'Предел Voc', source: 'Источник значения', metric_scale: 'Шкала метрики', contradiction: 'Противоречие', normalization: 'Нормализация', links: 'Связи записей', metric_k: 'Параметр k', comparability: 'Сопоставимость', schema: 'Структура данных' })[rule] || rule
