<!-- Назначение файла: окно подтверждения действия с полем причины (stores/dialogs.js). -->
<script setup>
import { computed } from 'vue'
import Modal from './Modal.vue'
import { dialog, closeDialog } from '../../stores/dialogs.js'
const valid = computed(() => !dialog.withReason || !dialog.reasonRequired || dialog.value.trim().length > 2)
function submit () {
  if (!valid.value) return
  closeDialog(dialog.withReason ? dialog.value.trim() : true)
}
</script>
<template>
  <Modal :open="dialog.open" :title="dialog.title" width="480px" @close="closeDialog(null)">
    <form id="reason-form" class="stack" @submit.prevent="submit">
      <p v-if="dialog.text" class="muted">{{ dialog.text }}</p>
      <label v-if="dialog.withReason" class="field">
        <span class="field__label">{{ dialog.reasonLabel }}<span v-if="!dialog.reasonRequired" class="faint">, необязательно</span></span>
        <textarea v-model="dialog.value" class="textarea" rows="3" :placeholder="dialog.placeholder" autofocus @keydown.enter.ctrl.prevent="submit" @keydown.enter.meta.prevent="submit" />
        <span class="field__hint">Попадёт в историю версий вместе с вашим именем.</span>
      </label>
    </form>
    <template #footer>
      <button class="btn" type="button" @click="closeDialog(null)">Отмена</button>
      <button class="btn" :class="dialog.tone === 'danger' ? 'btn--danger' : 'btn--primary'" type="submit" form="reason-form" :disabled="!valid">{{ dialog.confirm }}</button>
    </template>
  </Modal>
</template>
