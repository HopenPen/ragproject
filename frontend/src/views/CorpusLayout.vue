<!-- Назначение файла: рабочее место корпуса. Одна строка сверху: знак, корпус, четыре раздела вкладками,
     поиск и пользователь. Бокового меню нет, чтобы таблицы и страница статьи занимали всю ширину.
     На телефоне разделы внизу: документы и проверки (короткий режим). -->
<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown, Monitor } from '@lucide/vue'
import Menu from '../components/ui/Menu.vue'
import BrandMark from '../components/app/BrandMark.vue'
import GlobalSearch from '../components/app/GlobalSearch.vue'
import UserMenu from '../components/app/UserMenu.vue'
import { ws, loadCorpora, openCorpus, loadReference, stopJobsPolling, refreshCorpus } from '../stores/workspace.js'
import { ui } from '../stores/ui.js'
import { notify } from '../stores/toasts.js'

const props = defineProps({ corpusId: String })
const route = useRoute()
const router = useRouter()

async function load (id) {
  try {
    await Promise.all([ws.corpora.length ? null : loadCorpora(), loadReference()])
    await openCorpus(id)
  } catch (e) {
    notify.error(e)
    router.replace('/corpora')
  }
}
watch(() => props.corpusId, id => load(id), { immediate: true })
watch(() => ws.jobsVersion, () => refreshCorpus().catch(() => {}))
onBeforeUnmount(stopJobsPolling)

const issuesOpen = computed(() => ws.corpus?.stats?.issues_open ?? 0)
const desktopOnly = computed(() => ui.mobile && route.meta.desktop)
const base = computed(() => `/corpora/${props.corpusId}`)
</script>

<template>
  <div class="shell">
    <header class="bar">
      <RouterLink to="/corpora" class="bar__brand" aria-label="Все корпуса"><BrandMark /><span v-if="!ui.mobile">Science Extract</span></RouterLink>
      <Menu align="start" width="300px" class="corpus-menu">
        <template #trigger="{ toggle, open }">
          <button class="corpus-btn" type="button" :aria-expanded="open" @click="toggle">
            <span class="ellipsis">{{ ws.corpus?.name || 'Корпус' }}</span><ChevronDown />
          </button>
        </template>
        <RouterLink v-for="c in ws.corpora" :key="c.id" :to="`/corpora/${c.id}/documents`" class="menu__item" :class="{ 'is-active': c.id === corpusId }">
          <span class="ellipsis">{{ c.name }}</span>
        </RouterLink>
        <div class="menu__sep" />
        <RouterLink to="/corpora" class="menu__item">Все корпуса</RouterLink>
      </Menu>
      <nav v-if="!ui.mobile" class="bar__nav" aria-label="Разделы корпуса">
        <RouterLink :to="`${base}/documents`" class="bar__tab">Документы</RouterLink>
        <RouterLink :to="`${base}/results`" class="bar__tab">Результаты</RouterLink>
        <RouterLink :to="`${base}/checks`" class="bar__tab">Проверки<span v-if="issuesOpen" class="count count--warn">{{ issuesOpen }}</span></RouterLink>
        <RouterLink :to="`${base}/export`" class="bar__tab">Выгрузка</RouterLink>
      </nav>
      <div class="bar__end">
        <GlobalSearch :corpus-id="corpusId" :compact="ui.mobile" />
        <UserMenu />
      </div>
    </header>

    <main class="shell__main">
      <div v-if="desktopOnly" class="page empty">
        <Monitor class="empty__icon" />
        <h3>Раздел открывается на компьютере</h3>
        <p>Таблицы, сравнение и выгрузка не помещаются на экран телефона. Здесь доступны документы и проверки.</p>
        <RouterLink class="btn" :to="`${base}/checks`">Открыть проверки</RouterLink>
      </div>
      <RouterView v-else-if="ws.corpus && ws.corpus.id === corpusId" />
    </main>

    <nav v-if="ui.mobile" class="tabbar" aria-label="Разделы">
      <RouterLink :to="`${base}/documents`" class="tabbar__item">Документы</RouterLink>
      <RouterLink :to="`${base}/checks`" class="tabbar__item">Проверки<span v-if="issuesOpen" class="count count--warn">{{ issuesOpen }}</span></RouterLink>
    </nav>
  </div>
</template>

<style>
.corpus-menu { min-width: 0; flex: 0 1 auto; }
.corpus-btn { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: 280px; height: 32px; padding: 0 8px; margin-left: -8px; border: 0; border-radius: 6px; background: none; color: var(--ink); font-weight: 500; }
.corpus-btn:hover { background: var(--hover); }
.corpus-btn svg { width: 14px; height: 14px; color: var(--pencil); }
.empty__icon { width: 24px !important; height: 24px !important; margin-bottom: 14px; color: var(--pencil); }
@media (max-width: 1100px) { .bar__nav { gap: 16px; } .corpus-btn { max-width: 180px; } }
@media (max-width: 719px) {
  .corpus-menu { flex: 1 1 auto; }
  .corpus-btn { max-width: none; width: 100%; margin-left: 0; }
}
</style>
