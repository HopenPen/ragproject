<!-- Назначение файла: меню пользователя: имя и роль, тема оформления, выход на этом или на всех устройствах. -->
<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Sun, Moon, Monitor, LogOut, MonitorSmartphone } from '@lucide/vue'
import Menu from '../ui/Menu.vue'
import { session, logout } from '../../stores/session.js'
import { ui, setTheme } from '../../stores/ui.js'
import { ROLE } from '../../lib/labels.js'
import { notify } from '../../stores/toasts.js'

const router = useRouter()
const initials = computed(() => (session.user?.display_name || '?').split(/\s+/).map(w => w[0]).slice(0, 2).join(''))
async function out (everywhere) {
  try { await logout({ everywhere }) } catch (e) { notify.error(e) }
  router.push('/login')
}
</script>

<template>
  <Menu width="260px">
    <template #trigger="{ toggle, open }">
      <button class="avatar" type="button" :aria-expanded="open" aria-label="Меню пользователя" @click="toggle">{{ initials }}</button>
    </template>
    <div class="menu__label">
      <strong class="user-name">{{ session.user?.display_name }}</strong>
      <span>{{ session.user?.email }}, {{ ROLE[session.user?.role]?.toLowerCase() }}</span>
    </div>
    <div class="menu__sep" />
    <div class="menu__label">Тема</div>
    <button class="menu__item" :class="{ 'is-active': ui.themePref === 'light' }" type="button" @click="setTheme('light')"><Sun />Светлая</button>
    <button class="menu__item" :class="{ 'is-active': ui.themePref === 'dark' }" type="button" @click="setTheme('dark')"><Moon />Тёмная</button>
    <button class="menu__item" :class="{ 'is-active': ui.themePref === 'system' }" type="button" @click="setTheme('system')"><Monitor />Как в системе</button>
    <div class="menu__sep" />
    <button class="menu__item" type="button" @click="out(false)"><LogOut />Выйти</button>
    <button class="menu__item" type="button" @click="out(true)"><MonitorSmartphone />Выйти на всех устройствах</button>
  </Menu>
</template>

<style>
.avatar { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--line-strong); background: var(--surface-2); color: var(--ink-2); font-size: 12px; font-weight: 600; cursor: pointer; }
.avatar:hover { border-color: var(--faint); }
.user-name { display: block; color: var(--ink); font-size: var(--fs-md); font-weight: 500; margin-bottom: 2px; }
</style>
