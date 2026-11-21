<!-- Назначение файла: полоса прогресса задания; без значения показывает непрерывное движение. -->
<script setup>
defineProps({ value: { type: Number, default: null }, tone: { type: String, default: 'accent' } })
</script>
<template>
  <div class="progress" :class="[`progress--${tone}`, value === null && 'progress--busy']" role="progressbar" :aria-valuenow="value === null ? undefined : Math.round(value * 100)" aria-valuemin="0" aria-valuemax="100">
    <span :style="{ width: value === null ? '35%' : `${Math.max(2, Math.min(100, value * 100))}%` }" />
  </div>
</template>
<style>
.progress { height: 6px; border-radius: 3px; background: var(--surface-sunk); overflow: hidden; }
.progress span { display: block; height: 100%; border-radius: inherit; background: var(--accent); transition: width .35s var(--ease); }
.progress--warn span { background: var(--warn-line); }
.progress--busy span { animation: busy 1.4s var(--ease) infinite; }
@keyframes busy { from { transform: translateX(-100%); } to { transform: translateX(300%); } }
</style>
