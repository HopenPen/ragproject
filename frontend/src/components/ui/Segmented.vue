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
.seg { display: inline-flex; gap: 20px; flex-wrap: wrap; }
.seg__opt { position: relative; display: inline-flex; align-items: baseline; gap: 6px; height: 32px; padding: 6px 0 0; border: 0; background: none; color: var(--pencil); font-weight: 500; white-space: nowrap; transition: color 140ms var(--ease); }
.seg__opt:hover { color: var(--ink); }
.seg__opt.is-on { color: var(--ink); }
.seg__opt.is-on::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: var(--ink); border-radius: 1px; }
.seg__count { font-weight: 400; color: var(--pencil); font-variant-numeric: tabular-nums; }
.seg--sm { gap: 16px; }
.seg--sm .seg__opt { height: 28px; font-size: 13px; }
</style>
