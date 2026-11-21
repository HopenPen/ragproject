<!-- Назначение файла: список корпусов пользователя и создание нового корпуса (POST /corpora). -->
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Archive, Trash2 } from '@lucide/vue'
import Modal from '../components/ui/Modal.vue'
import BrandMark from '../components/app/BrandMark.vue'
import UserMenu from '../components/app/UserMenu.vue'
import { corpora } from '../api/index.js'
import { ws, loadCorpora } from '../stores/workspace.js'
import { session, canManage } from '../stores/session.js'
import { askReason } from '../stores/dialogs.js'
import { notify } from '../stores/toasts.js'
import { fmtDate, countText } from '../lib/format.js'

const router = useRouter()
const loading = ref(true)
const createOpen = ref(false)
const form = ref({ name: '', description: '', split: 'dev' })
const busy = ref(false)
const fieldError = ref('')
const canCreate = computed(() => ['editor', 'admin'].includes(session.user?.role))
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
    <header class="shell__bar">
      <span class="shell__brand"><BrandMark /><span>Science Extract</span></span>
      <span class="grow" />
      <UserMenu />
    </header>
    <main class="page corpora">
      <div class="page__head">
        <h1 class="page__title">Корпуса</h1>
        <span class="grow" />
        <button v-if="canCreate" class="btn btn--accent" type="button" @click="createOpen = true; fieldError = ''"><Plus />Новый корпус</button>
      </div>
      <div v-if="loading" class="panel"><div v-for="i in 3" :key="i" class="skeleton" style="height: 20px; margin: 18px 16px" /></div>
      <div v-else-if="!ws.corpora.length" class="panel empty">
        <h3>Корпусов пока нет</h3>
        <p>Корпус объединяет статьи одной задачи: например, dev-набор для настройки или тестовый набор для сдачи.</p>
        <button v-if="canCreate" class="btn btn--accent" type="button" @click="createOpen = true">Создать корпус</button>
      </div>
      <div v-else class="panel corpora__list">
        <div class="corpora__cols" aria-hidden="true"><span>Корпус</span><span class="t-r">Статьи</span><span class="t-r">Записи</span><span class="t-r">Замечания</span><span>Набор</span><span class="t-r">Изменён</span><span /></div>
        <div v-for="c in ws.corpora" :key="c.id" class="corpora__row">
          <RouterLink :to="`/corpora/${c.id}/documents`" class="corpora__main">
            <span class="corpora__name">{{ c.name }}<span v-if="c.status === 'archived'" class="chip chip--off corpora__arch"><Archive style="width: 12px; height: 12px" />в архиве</span></span>
            <span v-if="c.description" class="corpora__desc">{{ c.description }}</span>
          </RouterLink>
          <span class="corpora__n num" data-label="Статьи">{{ c.stats?.documents ?? 0 }}</span>
          <span class="corpora__n num" data-label="Записи">{{ c.stats?.records ?? 0 }}</span>
          <span class="corpora__n" data-label="Замечания"><span v-if="c.stats?.issues_open" class="count count--warn">{{ c.stats.issues_open }}</span><span v-else class="num">0</span></span>
          <span class="corpora__split"><span class="chip chip--plain">{{ c.split }}</span></span>
          <span class="corpora__age">{{ fmtDate(c.updated_at) }}</span>
          <button v-if="canManage(c)" class="btn btn--ghost btn--icon" type="button" :aria-label="`Удалить корпус ${c.name}`" :disabled="deleting.has(c.id)" @click="remove(c)"><Trash2 /></button>
        </div>
      </div>
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
        <button class="btn btn--accent" type="submit" form="corpus-form" :disabled="busy">Создать корпус</button>
      </template>
    </Modal>
  </div>
</template>

<style>
.corpora { max-width: 1080px; }
.corpora__list { overflow: hidden; }
.corpora__cols, .corpora__row { display: grid; grid-template-columns: minmax(0, 1fr) 72px 72px 88px 72px 120px 32px; align-items: center; gap: 0 16px; padding: 0 16px; }
.corpora__cols { height: 34px; color: var(--u-soft); background: var(--u-fill); box-shadow: inset 0 -1px 0 var(--u-line); }
.corpora__cols .t-r { text-align: right; }
.corpora__row { min-height: 60px; padding-top: 10px; padding-bottom: 10px; color: var(--u-ink); text-decoration: none !important; transition: background-color 160ms var(--u-ease); }
.corpora__row + .corpora__row { box-shadow: inset 0 1px 0 var(--u-line); }
.corpora__row:hover { background: color-mix(in oklab, var(--u-ink) 3%, var(--u-bg)); }
.corpora__main { display: flex; flex-direction: column; min-width: 0; color: inherit; }
.corpora__name { display: flex; align-items: center; gap: 8px; font-weight: 500; }
.corpora__arch { height: 20px; font-size: 12px; }
.corpora__desc { color: var(--u-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.corpora__n { text-align: right; color: var(--u-text-2); }
.corpora__age { text-align: right; color: var(--u-soft); white-space: nowrap; }
@media (max-width: 719px) {
  .corpora__cols { display: none; }
  .corpora__row { grid-template-columns: repeat(3, auto) 1fr; grid-template-rows: auto auto; gap: 8px 16px; padding: 12px 14px; }
  .corpora__main { grid-column: 1 / 4; }
  .corpora__row > button { grid-column: 4; grid-row: 1; justify-self: end; }
  .corpora__desc { white-space: normal; }
  .corpora__n { text-align: left; display: flex; flex-direction: column; font-size: 13px; }
  .corpora__n::before { content: attr(data-label); font-size: 12px; line-height: 16px; color: var(--u-soft); }
  .corpora__split { justify-self: end; align-self: end; }
  .corpora__age { display: none; }
}
</style>
