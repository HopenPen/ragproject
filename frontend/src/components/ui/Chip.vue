<!-- Назначение файла: статус одной строкой с цветовой точкой (готово, идёт, ждёт решения, ошибка, вне тем). -->
<script setup>
defineProps({ tone: { type: String, default: '' }, text: String, plain: Boolean })
</script>
<template><span class="chip" :class="[tone && `chip--${tone}`, plain && 'chip--plain']"><slot>{{ text }}</slot></span></template>
