<!-- Назначение файла: корень приложения: текущий экран, уведомления и общий диалог подтверждения. -->
<script setup>
import Toaster from './components/ui/Toaster.vue'
import DialogHost from './components/ui/DialogHost.vue'
import { session } from './stores/session.js'
</script>
<template>
  <RouterView v-if="session.ready" />
  <div v-else class="boot" aria-busy="true"><span class="boot__mark" /></div>
  <Toaster />
  <DialogHost />
</template>
<style>
.boot { min-height: 100vh; display: grid; place-items: center; }
.boot__mark { width: 28px; height: 34px; border: 2px solid var(--ink); border-radius: 4px; position: relative; opacity: .5; }
.boot__mark::after { content: ""; position: absolute; right: -7px; bottom: 5px; width: 14px; height: 10px; border: 2.4px solid var(--accent); border-radius: 2px; background: var(--bg); }
</style>
