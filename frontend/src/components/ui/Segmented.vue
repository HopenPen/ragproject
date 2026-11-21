<!-- Назначение файла: переключатель из нескольких вариантов (профиль, вид списка). -->
<script setup>
defineProps({ modelValue: [String, Number, Boolean], options: Array, size: { type: String, default: 'md' }, label: String })
const emit = defineEmits(['update:modelValue'])
</script>
<template>
  <div class="seg" :class="`seg--${size}`" role="radiogroup" :aria-label="label">
    <button v-for="o in options" :key="String(o.value)" type="button" role="radio" class="seg__opt" :class="{ 'is-on': o.value === modelValue }" :aria-checked="o.value === modelValue" @click="emit('update:modelValue', o.value)">
      {{ o.label }}<span v-if="o.count !== undefined" class="seg__count num">{{ o.count }}</span>
    </button>
  </div>
</template>
<style>
.seg { display: inline-flex; padding: 3px; gap: 2px; background: var(--surface-sunk); border-radius: var(--r-md); }
.seg__opt { height: 28px; padding: 0 12px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); font-size: var(--fs-sm); font-weight: 500; cursor: pointer; white-space: nowrap; }
.seg__opt:hover { color: var(--ink); }
.seg__opt.is-on { background: var(--surface-2); color: var(--ink); box-shadow: 0 1px 2px rgba(0, 0, 0, .08); }
.seg__count { margin-left: 6px; color: var(--faint); }
.seg--sm .seg__opt { height: 24px; padding: 0 9px; font-size: var(--fs-xs); }
</style>
