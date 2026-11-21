<!-- Назначение файла: название показателя с подстрочными индексами (Voc, Jsc, T80) и k метрики (Recall@5). -->
<script setup>
import { computed } from 'vue'
import { metricParts } from '../../lib/format.js'
const props = defineProps({ name: String, k: [Number, String] })
const parts = computed(() => metricParts(props.name, props.k))
</script>
<template><span class="metric"><template v-for="(p, i) in parts" :key="i"><sub v-if="p.sub">{{ p.text }}</sub><template v-else>{{ p.text }}</template></template></span></template>
<style>.metric { white-space: nowrap; } .metric sub { font-size: .72em; vertical-align: -0.22em; line-height: 0; }</style>
