<!-- Назначение файла: статус словом. Цветом выделяется только то, что ждёт решения; идущая работа с вращением. -->
<script setup>
defineProps({ tone: { type: String, default: '' }, text: String, plain: Boolean })
</script>
<template><span class="chip" :class="[tone && `chip--${tone}`, plain && 'chip--plain']"><slot>{{ text }}</slot></span></template>
