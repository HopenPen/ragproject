<!-- Назначение файла: список корпусов пользователя и создание нового корпуса (POST /corpora). -->
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Archive } from '@lucide/vue'
import Modal from '../components/ui/Modal.vue'
import BrandMark from '../components/app/BrandMark.vue'
import UserMenu from '../components/app/UserMenu.vue'
import { corpora } from '../api/index.js'
import { ws, loadCorpora } from '../stores/workspace.js'
import { session } from '../stores/session.js'
import { notify } from '../stores/toasts.js'
import { fmtDate, countText } from '../lib/format.js'

const router = useRouter()
const loading = ref(true)
const createOpen = ref(false)
const form = ref({ name: '', description: '', split: 'dev' })
const busy = ref(false)
const fieldError = ref('')
const canCreate = computed(() => ['editor', 'admin'].includes(session.user?.role))

onMounted(async () => {
  try { await loadCorpora() } catch (e) { notify.error(e) } finally { loading.value = false }
})
async function create () {
  if (!form.value.name.trim()) { fieldError.value = 'Укажите название.'; return }
  busy.value = true
  try {
    const c = await corpora.create({ ...form.value, name: form.value.name.trim() })
    createOpen.value = false
    notify.ok('Корпус создан')
    await loadCorpora()
    router.push(`/corpora/${c.id}/documents`)
  } catch (e) {
    if (e.details?.field === 'name') fieldError.value = e.message
    else notify.error(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="shell">
    <header class="top">
      <span class="top__brand"><BrandMark /><span>Science Extract</span></span>
      <span class="grow" />
      <UserMenu />
    </header>
    <main class="page corpora">
      <div class="page__head">
        <h1 class="page__title">Корпуса</h1>
        <span class="grow" />
        <button v-if="canCreate" class="btn btn--primary" type="button" @click="createOpen = true; fieldError = ''"><Plus />Новый корпус</button>
      </div>
      <div v-if="loading" class="stack"><div v-for="i in 2" :key="i" class="skeleton" style="height: 88px" /></div>
      <div v-else-if="!ws.corpora.length" class="panel empty">
        <h3>Корпусов пока нет</h3>
        <p>Корпус объединяет статьи одной задачи: например, dev-набор для настройки или тестовый набор для сдачи.</p>
        <button v-if="canCreate" class="btn btn--primary" type="button" @click="createOpen = true">Создать корпус</button>
      </div>
      <ul v-else class="corpora__list">
        <li v-for="c in ws.corpora" :key="c.id">
          <RouterLink :to="`/corpora/${c.id}/documents`" class="corpora__item panel">
            <div class="corpora__main">
              <h2>{{ c.name }}</h2>
              <p v-if="c.description" class="muted">{{ c.description }}</p>
            </div>
            <dl class="corpora__stats">
              <div><dt>Статьи</dt><dd class="num">{{ c.stats?.documents ?? 0 }}</dd></div>
              <div><dt>Записи</dt><dd class="num">{{ c.stats?.records ?? 0 }}</dd></div>
              <div><dt>Замечания</dt><dd class="num" :class="{ 'is-warn': c.stats?.issues_open }">{{ c.stats?.issues_open ?? 0 }}</dd></div>
            </dl>
            <div class="corpora__side">
              <span class="chip chip--plain">{{ c.split }}</span>
              <span v-if="c.status === 'archived'" class="chip chip--off"><Archive style="width: 12px; height: 12px" />в архиве</span>
              <span class="faint">изменён {{ fmtDate(c.updated_at) }}</span>
            </div>
          </RouterLink>
        </li>
      </ul>
      <p v-if="ws.corpora.length" class="faint corpora__note">{{ countText(ws.corpora.length, ['корпус', 'корпуса', 'корпусов']) }} доступно вам.</p>
    </main>

    <Modal :open="createOpen" title="Новый корпус" @close="createOpen = false">
      <form id="corpus-form" class="stack" style="gap: 16px" @submit.prevent="create">
        <label class="field">
          <span class="field__label">Название</span>
          <input v-model="form.name" class="input" autofocus :aria-invalid="!!fieldError" placeholder="Например, Dev-набор ноябрь">
          <span v-if="fieldError" class="field__error">{{ fieldError }}</span>
        </label>
        <label class="field">
          <span class="field__label">Описание<span class="faint">, необязательно</span></span>
          <textarea v-model="form.description" class="textarea" rows="2" />
        </label>
        <label class="field">
          <span class="field__label">Набор</span>
          <select v-model="form.split" class="select">
            <option value="dev">dev: настройка и проверка на размеченных статьях</option>
            <option value="test">test: итоговая обработка</option>
          </select>
          <span class="field__hint">После загрузки статей набор не меняется.</span>
        </label>
      </form>
      <template #footer>
        <button class="btn" type="button" @click="createOpen = false">Отмена</button>
        <button class="btn btn--primary" type="submit" form="corpus-form" :disabled="busy">Создать корпус</button>
      </template>
    </Modal>
  </div>
</template>

<style>
.corpora { max-width: 980px; }
.corpora__list { display: flex; flex-direction: column; gap: var(--s-3); }
.corpora__item { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: var(--s-6); padding: var(--s-5) var(--s-6); color: var(--ink); transition: border-color .15s var(--ease); }
.corpora__item:hover { text-decoration: none; border-color: var(--line-strong); }
.corpora__main h2 { font-size: var(--fs-lg); margin-bottom: 4px; }
.corpora__stats { display: flex; gap: var(--s-6); margin: 0; }
.corpora__stats div { min-width: 64px; }
.corpora__stats dt { font-size: var(--fs-xs); color: var(--muted); }
.corpora__stats dd { margin: 2px 0 0; font-size: var(--fs-xl); font-weight: 500; }
.corpora__stats dd.is-warn { color: var(--warn); }
.corpora__side { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; font-size: var(--fs-sm); }
.corpora__note { margin-top: var(--s-4); font-size: var(--fs-sm); }
@media (max-width: 719px) {
  .corpora__item { grid-template-columns: 1fr; gap: var(--s-3); padding: var(--s-4); }
  .corpora__side { flex-direction: row; align-items: center; }
}
</style>
