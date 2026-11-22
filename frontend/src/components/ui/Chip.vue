<!-- Назначение файла: статус словом. Цветом выделяется только то, что ждёт решения; идущая работа с вращением.
     Вариант dot (список документов): точка и слово, как в прошлой версии; рамка и заливка у того, что ждёт человека. -->
<script setup>
defineProps({ tone: { type: String, default: '' }, text: String, plain: Boolean, dot: Boolean })
</script>
<template><span class="chip" :class="[tone && `chip--${tone}`, plain && 'chip--plain', dot && 'chip--dot']"><slot>{{ text }}</slot></span></template>
