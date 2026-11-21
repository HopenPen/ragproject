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
.seg { display: inline-flex; gap: 4px; flex-wrap: wrap; }
.seg__opt { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 10px; border: 0; border-radius: 99px; background: transparent; color: var(--u-muted); font-size: 13px; font-weight: 400; white-space: nowrap; transition: background-color 160ms var(--u-ease), color 160ms var(--u-ease); }
.seg__opt:hover { color: var(--u-ink); background: var(--u-fill); }
.seg__opt.is-on { background: var(--u-fill-2); color: var(--u-ink); font-weight: 500; }
.seg__count { color: var(--u-soft); font-variant-numeric: tabular-nums; }
.seg__opt.is-on .seg__count { color: var(--u-muted); }
.seg--sm .seg__opt { height: 24px; padding: 0 9px; }
</style>
