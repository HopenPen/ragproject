// Назначение файла: маршруты интерфейса и защита экранов: без входа доступен только /login.
import { createRouter, createWebHistory } from 'vue-router'
import { session } from './stores/session.js'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
  { path: '/', redirect: '/corpora' },
  { path: '/corpora', name: 'corpora', component: () => import('./views/CorporaView.vue') },
  {
    path: '/corpora/:corpusId',
    component: () => import('./views/CorpusLayout.vue'),
    props: true,
    children: [
      { path: '', redirect: to => `/corpora/${to.params.corpusId}/documents` },
      { path: 'documents', name: 'documents', component: () => import('./views/DocumentsView.vue') },
      { path: 'documents/:documentId', name: 'article', component: () => import('./views/ArticleView.vue'), props: true, meta: { wide: true } },
      { path: 'results', name: 'results', component: () => import('./views/ResultsView.vue'), meta: { desktop: true } },
      { path: 'checks', name: 'checks', component: () => import('./views/ChecksView.vue') },
      { path: 'export', name: 'export', component: () => import('./views/ExportView.vue'), meta: { desktop: true } }
    ]
  },
  { path: '/:pathMatch(.*)*', name: 'missing', component: () => import('./views/MissingView.vue') }
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: (to, from, saved) => saved || (to.path !== from.path ? { top: 0 } : undefined)
})

router.beforeEach(to => {
  if (!to.meta.public && !session.user) return { name: 'login', query: to.fullPath !== '/corpora' ? { next: to.fullPath } : {} }
  if (to.name === 'login' && session.user) return '/corpora'
})
