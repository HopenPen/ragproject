// Назначение файла: собрать @font-face для шрифтов интерфейса из пакетов @fontsource-variable
// (только latin и cyrillic, файлы раздаются вместе с приложением, без Google Fonts).
// Geologica: весь текст интерфейса и числа (есть tabular figures). Geist Mono: хеши, JSON, имена файлов.
import fs from 'node:fs'

const list = [['geologica', 'Geologica'], ['geist-mono', 'Geist Mono']]
let out = '/* Назначение файла: шрифты интерфейса (variable, latin + cyrillic), сгенерировано scripts/make-fonts.mjs */\n'
for (const [pkg, family] of list) {
  const css = fs.readFileSync(`node_modules/@fontsource-variable/${pkg}/wght.css`, 'utf8')
  for (const subset of ['cyrillic', 'latin']) {
    const block = css.split('@font-face').find(b => b.includes(`${pkg}-${subset}-wght-normal.woff2`))
    if (!block) throw new Error(`${pkg}: нет ${subset}`)
    const weight = (block.match(/font-weight:\s*([^;]+);/) || [])[1] || '100 900'
    const range = (block.match(/unicode-range:\s*([^;]+);/) || [])[1]
    out += `@font-face { font-family: "${family}"; font-style: normal; font-display: swap; font-weight: ${weight};\n  src: url("../../node_modules/@fontsource-variable/${pkg}/files/${pkg}-${subset}-wght-normal.woff2") format("woff2-variations");\n  unicode-range: ${range}; }\n`
  }
}
fs.writeFileSync('src/styles/fonts.css', out)
console.log('fonts:', list.map(x => x[1]).join(' + '))
