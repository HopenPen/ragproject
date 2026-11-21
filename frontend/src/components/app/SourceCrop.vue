<!-- Назначение файла: вырезка страницы PDF вокруг значения (телефонный режим): pdf.js рисует только нужную
     область через смещение viewport, поверх рамка источника. -->
<script setup>
import { onMounted, ref, watch } from 'vue'
import { loadPdf, pdfErrorText } from '../../lib/pdf.js'

const props = defineProps({ documentId: String, page: Number, bbox: Array, label: String, tone: { type: String, default: 'ok' } })
const wrap = ref(null)
const canvas = ref(null)
const crop = ref(null)
const error = ref('')

async function draw () {
  error.value = ''
  if (!props.page || !props.bbox) return
  try {
    const pdf = await loadPdf(props.documentId)
    const page = await pdf.getPage(props.page)
    const vp1 = page.getViewport({ scale: 1 })
    const [x0, y0, x1, y1] = props.bbox
    const w = Math.min(vp1.width, Math.max(x1 - x0 + 220, 320))
    const h = Math.max(y1 - y0 + 70, 90)
    const cx = Math.min(Math.max(0, (x0 + x1) / 2 - w / 2), vp1.width - w)
    const cy = Math.min(Math.max(0, (y0 + y1) / 2 - h / 2), vp1.height - h)
    crop.value = { x: cx, y: cy, w, h }
    const cssW = wrap.value.clientWidth
    const scale = cssW / w
    const dpr = Math.min(window.devicePixelRatio || 1, 3)
    const vp = page.getViewport({ scale: scale * dpr, offsetX: -cx * scale * dpr, offsetY: -cy * scale * dpr })
    canvas.value.width = Math.floor(w * scale * dpr)
    canvas.value.height = Math.floor(h * scale * dpr)
    canvas.value.style.height = `${h * scale}px`
    await page.render({ canvas: canvas.value, viewport: vp }).promise
  } catch (e) {
    error.value = pdfErrorText(e)
  }
}
onMounted(draw)
watch(() => [props.documentId, props.page, props.bbox], draw)
</script>

<template>
  <div ref="wrap" class="crop">
    <p v-if="error" class="crop__error">{{ error }}</p>
    <div v-else class="crop__sheet">
      <canvas ref="canvas" />
      <span class="crop__paper" />
      <span v-if="crop" class="pin is-active" :class="`pin--${tone}`" :style="{ left: `${(bbox[0] - crop.x) / crop.w * 100}%`, top: `${(bbox[1] - crop.y) / crop.h * 100}%`, width: `${(bbox[2] - bbox[0]) / crop.w * 100}%`, height: `${(bbox[3] - bbox[1]) / crop.h * 100}%` }" />
    </div>
  </div>
</template>

<style>
.crop { width: 100%; }
.crop__sheet { position: relative; overflow: hidden; background: #fff; border-radius: 2px; box-shadow: 0 1px 2px var(--shade); }
.crop__sheet canvas { display: block; width: 100%; }
.crop__paper { position: absolute; inset: 0; background: var(--paper); mix-blend-mode: multiply; pointer-events: none; }
.crop .pin { pointer-events: none; animation: none; }
.crop__error { color: var(--pencil); font-size: 13px; line-height: 18px; }
</style>
