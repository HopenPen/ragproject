import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router.js'
import { restoreSession, onSessionLost } from './stores/session.js'
import './stores/ui.js'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/kit/ui-base.css'
import './styles/kit/ui-window.css'
import './styles/kit/ui-doc.css'
import './styles/kit/ui-files.css'
import './styles/kit/ui-checklist.css'
import './styles/app.css'

restoreSession().finally(() => {
  onSessionLost(() => router.replace({ name: 'login', query: { next: router.currentRoute.value.fullPath } }))
  createApp(App).use(router).mount('#app')
})
