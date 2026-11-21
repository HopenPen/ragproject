// Назначение файла: скопировать в public/pdfjs ресурсы pdf.js, которые грузятся во время работы:
// cmaps (CJK и нестандартные кодировки), standard_fonts (невстроенные базовые шрифты PDF), wasm (декодеры JBIG2/JPX сканов).
import fs from 'node:fs'

for (const dir of ['cmaps', 'standard_fonts', 'wasm']) {
  fs.cpSync(`node_modules/pdfjs-dist/${dir}`, `public/pdfjs/${dir}`, { recursive: true })
}
console.log('pdfjs assets: cmaps, standard_fonts, wasm')
