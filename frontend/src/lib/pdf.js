import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { documents } from '../api/index.js'
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
const cache = new Map()
export function loadPdf(id) {
  if (!cache.has(id)) {
    const request = documents.file(id).then(data => pdfjs.getDocument({ data, cMapUrl: '/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/pdfjs/standard_fonts/', wasmUrl: '/pdfjs/wasm/' }).promise)
    cache.set(id, request)
    request.catch(() => cache.delete(id))
    if (cache.size > 3) cache.delete(cache.keys().next().value)
  }
  return cache.get(id)
}
export const pdfErrorText = error => error?.message || 'Не удалось открыть PDF. Повторите загрузку.'
