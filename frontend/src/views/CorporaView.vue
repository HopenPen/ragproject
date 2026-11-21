<!-- Назначение файла: список корпусов пользователя и создание нового корпуса (POST /corpora). -->
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Trash2 } from '@lucide/vue'
import Modal from '../components/ui/Modal.vue'
import BrandMark from '../components/app/BrandMark.vue'
import UserMenu from '../components/app/UserMenu.vue'
import { corpora } from '../api/index.js'
import { ws, loadCorpora } from '../stores/workspace.js'
import { session, canManage } from '../stores/session.js'
import { askReason } from '../stores/dialogs.js'
import { ui } from '../stores/ui.js'
import { notify } from '../stores/toasts.js'
import { fmtDate } from '../lib/format.js'

const router = useRouter()
const loading = ref(true)
const createOpen = ref(false)
const form = ref({ name: '', description: '', split: 'dev' })
const busy = ref(false)
const fieldError = ref('')
const canCreate = computed(() => ['editor', 'admin'].includes(session.user?.role))
const manageable = computed(() => ws.corpora.some(c => canManage(c)))
const deleting = ref(new Set())
async function remove (corpus) {
  const accepted = await askReason({ title: `Удалить корпус «${corpus.name}»?`, text: 'Будут удалены все PDF, извлечённые данные, история изменений и выгрузки корпуса. Восстановить их через сайт будет невозможно.', confirm: 'Удалить корпус', tone: 'danger', withReason: false })
  if (!accepted) return
  deleting.value.add(corpus.id)
  try { await corpora.remove(corpus.id); await loadCorpora(); notify.ok('Корпус удалён') } catch (e) { notify.error(e) } finally { deleting.value.delete(corpus.id) }
}

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
    <header class="bar">
      <span class="bar__brand"><BrandMark /><span>Science Extract</span></span>
      <div class="bar__end"><UserMenu /></div>
    </header>
    <main class="page corpora">
      <div class="page__head">
        <h1 class="page__title">Корпуса</h1>
        <span class="grow" />
        <button v-if="canCreate" class="btn btn--accent" type="button" @click="createOpen = true; fieldError = ''"><Plus />Новый корпус</button>
      </div>
      <div v-if="loading" class="corpora__ghost"><span v-for="i in 3" :key="i" class="skeleton" style="height: 18px" /></div>
      <div v-else-if="!ws.corpora.length" class="empty">
        <h3>Корпусов пока нет</h3>
        <p>Корпус объединяет статьи одной задачи: например, dev-набор для настройки или тестовый набор для сдачи.</p>
        <button v-if="canCreate" class="btn btn--accent" type="button" @click="createOpen = true">Создать корпус</button>
      </div>
      <table v-else-if="!ui.mobile" class="table corpora__table">
        <thead><tr><th>Корпус</th><th>Набор</th><th class="t-num">Статьи</th><th class="t-num">Записи</th><th class="t-num">Замечания</th><th class="t-num">Изменён</th><th v-if="manageable" class="t-act"><span class="visually-hidden">Удаление</span></th></tr></thead>
        <tbody>
          <tr v-for="c in ws.corpora" :key="c.id" class="is-link" @click="router.push(`/corpora/${c.id}/documents`)">
            <td class="corpora__main">
              <RouterLink :to="`/corpora/${c.id}/documents`" class="corpora__name" @click.stop>{{ c.name }}</RouterLink><span v-if="c.status === 'archived'" class="corpora__arch">, в архиве</span>
              <span v-if="c.description" class="corpora__desc">{{ c.description }}</span>
            </td>
            <td class="muted">{{ c.split }}</td>
            <td class="t-num">{{ c.stats?.documents ?? 0 }}</td>
            <td class="t-num">{{ c.stats?.records ?? 0 }}</td>
            <td class="t-num"><span v-if="c.stats?.issues_open" class="count count--warn">{{ c.stats.issues_open }}</span></td>
            <td class="t-num muted">{{ fmtDate(c.updated_at) }}</td>
            <td v-if="manageable" class="t-act" @click.stop><button v-if="canManage(c)" class="btn btn--ghost btn--icon btn--sm row-del" type="button" :aria-label="`Удалить корпус ${c.name}`" :title="`Удалить корпус ${c.name}`" :disabled="deleting.has(c.id)" @click="remove(c)"><Trash2 /></button></td>
          </tr>
        </tbody>
      </table>
      <ul v-else class="mcorp">
        <li v-for="c in ws.corpora" :key="c.id">
          <RouterLink :to="`/corpora/${c.id}/documents`" class="mcorp__row">
            <span class="mcorp__name">{{ c.name }}</span>
            <span class="mcorp__meta">{{ c.split }}, статей {{ c.stats?.documents ?? 0 }}<template v-if="c.stats?.issues_open">, <span class="count count--warn">замечаний {{ c.stats.issues_open }}</span></template></span>
          </RouterLink>
        </li>
      </ul>
    </main>

    <Modal :open="createOpen" title="Новый корпус" @close="createOpen = false">
      <form id="corpus-form" class="stack" style="gap: 16px" @submit.prevent="create">
        <label class="field">
          <span class="field__label">Название</span>
          <input v-model="form.name" class="input" autofocus :aria-invalid="!!fieldError" placeholder="Например, Dev-набор ноябрь">
          <span v-if="fieldError" class="field__error">{{ fieldError }}</span>
        </label>
        <label class="field">
          <span class="field__label">Описание<span class="muted">, необязательно</span></span>
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
        <button class="btn btn--ghost" type="button" @click="createOpen = false">Отмена</button>
        <button class="btn btn--accent" type="submit" form="corpus-form" :disabled="busy">Создать корпус</button>
      </template>
    </Modal>
  </div>
</template>

<style>
.corpora { max-width: 1120px; }
.corpora__ghost { display: flex; flex-direction: column; gap: 26px; padding: 20px 0; }
.corpora__table td { height: 64px; }
.corpora__main { min-width: 0; max-width: 560px; }
.corpora__name { font-weight: 600; color: var(--ink); text-decoration: none; }
.corpora__name:hover { text-decoration: underline; text-underline-offset: 4px; text-decoration-thickness: 1px; }
.corpora__arch { color: var(--pencil); }
.corpora__desc { display: block; color: var(--pencil); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcorp { box-shadow: inset 0 1.5px 0 var(--rule-strong); }
.mcorp li + li { box-shadow: inset 0 1px 0 var(--rule); }
.mcorp__row { display: flex; flex-direction: column; gap: 2px; padding: 14px 0; color: var(--ink); text-decoration: none; }
.mcorp__name { font-weight: 600; }
.mcorp__meta { color: var(--pencil); }
</style>
