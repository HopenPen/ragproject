<!-- Назначение файла: рабочее место корпуса: шапка с корпусом, разделами, поиском, темой и пользователем;
     на телефоне нижняя навигация только по документам и проверкам (короткий режим). -->
<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown, FileText, ListChecks, Archive, Monitor, Sun, Moon } from '@lucide/vue'
import Menu from '../components/ui/Menu.vue'
import BrandMark from '../components/app/BrandMark.vue'
import GlobalSearch from '../components/app/GlobalSearch.vue'
import UserMenu from '../components/app/UserMenu.vue'
import { ws, loadCorpora, openCorpus, loadReference, stopJobsPolling, refreshCorpus } from '../stores/workspace.js'
import { ui, toggleTheme } from '../stores/ui.js'
import { notify } from '../stores/toasts.js'
import { API_MODE } from '../api/http.js'

const props = defineProps({ corpusId: String })
const route = useRoute()
const router = useRouter()
const demo = API_MODE === 'mock'

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
const tabs = computed(() => [
  { to: `/corpora/${props.corpusId}/documents`, label: 'Документы' },
  { to: `/corpora/${props.corpusId}/results`, label: 'Результаты' },
  { to: `/corpora/${props.corpusId}/checks`, label: 'Проверки', count: issuesOpen.value },
  { to: `/corpora/${props.corpusId}/export`, label: 'Выгрузка' }
])
</script>

<template>
  <div class="shell" :class="{ 'shell--wide': route.meta.wide }">
    <header class="top">
      <RouterLink to="/corpora" class="top__brand" aria-label="Все корпуса"><BrandMark /><span v-if="!ui.mobile">Science Extract</span></RouterLink>
      <Menu align="start" width="320px" class="top__corpusmenu">
        <template #trigger="{ toggle, open }">
          <button class="top__corpus" type="button" :aria-expanded="open" @click="toggle">
            <span class="ellipsis">{{ ws.corpus?.name || 'Корпус' }}</span><ChevronDown />
          </button>
        </template>
        <div class="menu__label">Корпуса</div>
        <RouterLink v-for="c in ws.corpora" :key="c.id" :to="`/corpora/${c.id}/documents`" class="menu__item" :class="{ 'is-active': c.id === corpusId }">
          <Archive v-if="c.status === 'archived'" /><FileText v-else />
          <span class="ellipsis">{{ c.name }}</span>
        </RouterLink>
        <div class="menu__sep" />
        <RouterLink to="/corpora" class="menu__item">Все корпуса и новый корпус</RouterLink>
      </Menu>
      <nav v-if="!ui.mobile" class="top__tabs" aria-label="Разделы корпуса">
        <RouterLink v-for="t in tabs" :key="t.to" :to="t.to" class="top__tab">
          {{ t.label }}<span v-if="t.count" class="count count--warn">{{ t.count }}</span>
        </RouterLink>
      </nav>
      <span class="grow" />
      <GlobalSearch :corpus-id="corpusId" :compact="ui.mobile" />
      <span v-if="demo && !ui.mobile" class="chip chip--plain top__demo" title="Синтетические статьи, модель не вызывается">Демо-данные</span>
      <button v-if="!ui.mobile" class="btn btn--ghost btn--icon" type="button" :aria-label="ui.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'" :title="ui.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'" @click="toggleTheme"><Sun v-if="ui.theme === 'dark'" /><Moon v-else /></button>
      <UserMenu />
    </header>

    <main class="shell__main">
      <div v-if="desktopOnly" class="page empty">
        <Monitor class="empty__icon" />
        <h3>Раздел открывается на компьютере</h3>
        <p>Таблицы результатов, сравнение и выгрузка не помещаются на экран телефона. Здесь доступны документы и проверки.</p>
        <RouterLink class="btn" :to="`/corpora/${corpusId}/checks`">Открыть проверки</RouterLink>
      </div>
      <RouterView v-else-if="ws.corpus && ws.corpus.id === corpusId" />
    </main>

    <nav v-if="ui.mobile" class="tabbar" aria-label="Разделы">
      <RouterLink :to="`/corpora/${corpusId}/documents`" class="tabbar__item"><FileText /><span>Документы</span></RouterLink>
      <RouterLink :to="`/corpora/${corpusId}/checks`" class="tabbar__item"><ListChecks /><span>Проверки</span><span v-if="issuesOpen" class="count count--warn tabbar__count">{{ issuesOpen }}</span></RouterLink>
    </nav>
  </div>
</template>


