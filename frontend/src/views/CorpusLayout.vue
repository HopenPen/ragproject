<!-- Назначение файла: рабочее место корпуса в языке окна из UI-кита (как макет продукта на лендинге): строка окна
     с корпусом, поиском и пользователем, слева навигация по разделам, профилям и корпусам, справа экран раздела.
     На экране статьи навигация сжимается до значков, на телефоне уходит в нижнюю панель (короткий режим). -->
<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown, FileText, ListChecks, Monitor, Sun, Moon, Table2, PackageCheck, Folder } from '@lucide/vue'
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

const stats = computed(() => ws.corpus?.stats || {})
const issuesOpen = computed(() => stats.value.issues_open ?? 0)
const desktopOnly = computed(() => ui.mobile && route.meta.desktop)
const base = computed(() => `/corpora/${props.corpusId}`)
const others = computed(() => ws.corpora.filter(c => c.id !== props.corpusId))
const profileOn = p => route.name === 'results' && (route.query.profile || 'solar-v1') === p
</script>

<template>
  <div class="shell" :class="{ 'shell--rail': route.meta.wide && !ui.mobile }">
    <header class="shell__bar">
      <RouterLink to="/corpora" class="shell__brand" aria-label="Все корпуса"><BrandMark /><span v-if="!ui.mobile">Science Extract</span></RouterLink>
      <span v-if="!ui.mobile" class="ui-sep" />
      <Menu align="start" width="300px" class="crumb-menu">
        <template #trigger="{ toggle, open }">
          <button class="crumb" type="button" :aria-expanded="open" @click="toggle">
            <span v-if="!ui.mobile" class="crumb__dim">Корпус</span><i v-if="!ui.mobile">/</i><b class="ellipsis">{{ ws.corpus?.name || 'Корпус' }}</b><ChevronDown />
          </button>
        </template>
        <div class="menu__label">Корпуса</div>
        <RouterLink v-for="c in ws.corpora" :key="c.id" :to="`/corpora/${c.id}/documents`" class="menu__item" :class="{ 'is-active': c.id === corpusId }">
          <Folder /><span class="ellipsis">{{ c.name }}</span>
        </RouterLink>
        <div class="menu__sep" />
        <RouterLink to="/corpora" class="menu__item">Все корпуса</RouterLink>
      </Menu>
      <span class="grow" />
      <GlobalSearch :corpus-id="corpusId" :compact="ui.mobile" />
      <span v-if="demo && !ui.mobile" class="ui-chip ui-chip--plain" title="Синтетические статьи, модель не вызывается">Демо-данные</span>
      <button v-if="!ui.mobile" class="btn btn--ghost btn--icon" type="button" :aria-label="ui.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'" :title="ui.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'" @click="toggleTheme"><Sun v-if="ui.theme === 'dark'" /><Moon v-else /></button>
      <UserMenu />
    </header>

    <div class="shell__body">
      <nav v-if="!ui.mobile" class="shell__side" aria-label="Разделы корпуса">
        <RouterLink :to="`${base}/documents`" class="side__nav" title="Документы"><FileText /><span class="side__text">Документы</span><em>{{ stats.documents ?? '' }}</em></RouterLink>
        <RouterLink :to="`${base}/results`" class="side__nav" active-class="" exact-active-class="" :class="{ 'is-on': route.name === 'results' }" title="Результаты"><Table2 /><span class="side__text">Результаты</span><em>{{ stats.records ?? '' }}</em></RouterLink>
        <RouterLink :to="`${base}/checks`" class="side__nav" title="Проверки"><ListChecks /><span class="side__text">Проверки</span><span v-if="issuesOpen" class="count count--warn">{{ issuesOpen }}</span></RouterLink>
        <RouterLink :to="`${base}/export`" class="side__nav" title="Выгрузка"><PackageCheck /><span class="side__text">Выгрузка</span></RouterLink>
        <span class="side__label">Профили</span>
        <RouterLink :to="{ path: `${base}/results`, query: { profile: 'solar-v1' } }" class="side__nav side__extra" active-class="" exact-active-class="" :class="{ 'is-on': profileOn('solar-v1') }" title="solar-v1"><span class="side__hash">#</span><span class="side__text">solar-v1</span></RouterLink>
        <RouterLink :to="{ path: `${base}/results`, query: { profile: 'rag-v1' } }" class="side__nav side__extra" active-class="" exact-active-class="" :class="{ 'is-on': profileOn('rag-v1') }" title="rag-v1"><span class="side__hash">#</span><span class="side__text">rag-v1</span></RouterLink>
        <template v-if="others.length">
          <span class="side__label">Другие корпуса</span>
          <RouterLink v-for="c in others" :key="c.id" :to="`/corpora/${c.id}/documents`" class="side__nav side__extra" :title="c.name"><Folder /><span class="side__text ellipsis">{{ c.name }}</span></RouterLink>
        </template>
        <p v-if="ws.processing" class="side__foot">Модель {{ ws.processing.model_id }}<template v-if="demo"><br>в демо не вызывается</template><template v-else-if="ws.processing.configured === false"><br>ключ модели не настроен</template></p>
      </nav>

      <main class="shell__main">
        <div v-if="desktopOnly" class="page empty">
          <Monitor class="empty__icon" />
          <h3>Раздел открывается на компьютере</h3>
          <p>Таблицы результатов, сравнение и выгрузка не помещаются на экран телефона. Здесь доступны документы и проверки.</p>
          <RouterLink class="btn" :to="`${base}/checks`">Открыть проверки</RouterLink>
        </div>
        <RouterView v-else-if="ws.corpus && ws.corpus.id === corpusId" />
      </main>
    </div>

    <nav v-if="ui.mobile" class="tabbar" aria-label="Разделы">
      <RouterLink :to="`${base}/documents`" class="tabbar__item"><FileText /><span>Документы</span></RouterLink>
      <RouterLink :to="`${base}/checks`" class="tabbar__item"><ListChecks /><span>Проверки</span><span v-if="issuesOpen" class="count count--warn tabbar__count">{{ issuesOpen }}</span></RouterLink>
    </nav>
  </div>
</template>

<style>
.crumb-menu { min-width: 0; flex: 0 1 auto; }
.crumb { display: inline-flex; align-items: center; gap: 8px; min-width: 0; max-width: 100%; height: 30px; padding: 0 8px; border: 0; border-radius: 6px; background: none; color: var(--u-muted); font-size: 13px; line-height: 16px; white-space: nowrap; }
.crumb:hover { background: var(--u-fill-2); }
.crumb i { font-style: normal; color: var(--u-soft); }
.crumb b { min-width: 0; max-width: 320px; font-weight: 500; color: var(--u-ink); }
.crumb svg { width: 14px; height: 14px; flex: none; }
.empty__icon { width: 24px; height: 24px; margin: 0 auto 12px; color: var(--u-muted); }
.shell--rail .shell__body { grid-template-columns: 56px minmax(0, 1fr); }
.shell--rail .shell__side :is(.side__text, .side__label, .side__foot, em) { display: none; }
.shell--rail .side__nav { justify-content: center; padding: 0; }
.shell--rail .side__nav { position: relative; }
.shell--rail .side__nav .count { position: absolute; top: 2px; right: 2px; min-width: 16px; height: 16px; padding: 0 4px; font-size: 11px; }
.shell--rail .side__extra { display: none; }
@media (max-width: 719px) {
  .shell__bar { gap: 8px; padding: 0 8px 0 10px; }
  .crumb-menu { flex: 1 1 auto; }
  .crumb { width: 100%; }
  .crumb b { max-width: none; }
}
</style>
