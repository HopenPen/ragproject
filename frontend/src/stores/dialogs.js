// Назначение файла: единый диалог подтверждения с необязательным комментарием в истории.
import { reactive } from 'vue'

export const dialog = reactive({
  open: false, title: '', text: '', confirm: 'Подтвердить', tone: 'primary',
  withReason: true, reasonRequired: false, reasonLabel: 'Причина', placeholder: '', value: '', busy: false, resolve: null
})

export function askReason (opts) {
  return new Promise(resolve => {
    Object.assign(dialog, {
      title: opts.title, text: opts.text || '', confirm: opts.confirm || 'Подтвердить', tone: opts.tone || 'primary',
      withReason: opts.withReason !== false, reasonRequired: opts.reasonRequired === true,
      reasonLabel: opts.reasonLabel || 'Причина', placeholder: opts.placeholder || '', value: opts.value || '',
      busy: false, resolve, open: true
    })
  })
}
export function closeDialog (result) {
  dialog.open = false
  dialog.resolve?.(result)
  dialog.resolve = null
}
