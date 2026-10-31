#!/usr/bin/env node
// Проверка словарей интерфейса (src/locales). Запуск: node scripts/check-locales.mjs
//
// Ошибки (exit 1):
//   - у локали не хватает ключа, есть лишний ключ или пустая строка;
//   - в названии инструмента (tools.*.t) потеряно имя формата (PDF, TXT, MD...);
//   - реестр LANGUAGES не совпадает с файлами, порядок языков нарушен,
//     htmlLang не является корректным тегом BCP 47.
// Предупреждения (не роняют проверку):
//   - строка совпадает с английской — возможно, ее забыли перевести.
//
// Зависимостей не добавляет: .ts-файлы транспилируются пакетом typescript,
// который уже есть в проекте (им же запускается `tsc`).
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const localesDir = join(root, 'src', 'locales');

let ts;
try {
  ts = createRequire(join(root, 'package.json'))('typescript');
} catch {
  console.error('check-locales: пакет "typescript" не найден в node_modules проекта.');
  process.exit(2);
}

// --- транспиляция src/locales во временную папку --------------------------
const tmp = mkdtempSync(join(tmpdir(), 'check-locales-'));
const files = readdirSync(localesDir).filter((f) => f.endsWith('.ts'));
for (const file of files) {
  const { outputText } = ts.transpileModule(readFileSync(join(localesDir, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
    fileName: file,
  });
  // import('./de') -> import('./de.mjs'), чтобы Node нашел модуль
  const js = outputText.replace(/(['"])\.\/([\w-]+)\1/g, "'./$2.mjs'");
  writeFileSync(join(tmp, file.replace(/\.ts$/, '.mjs')), js);
}
const load = async (name) => (await import(pathToFileURL(join(tmp, `${name}.mjs`)).href));

const errors = [];
const warnings = [];
const err = (code, msg) => errors.push(`${code}: ${msg}`);
const warn = (code, msg) => warnings.push(`${code}: ${msg}`);

try {
  const { LANGUAGES } = await load('index');
  const en = (await load('en')).default;

  // --- реестр и файлы ------------------------------------------------------
  const codes = LANGUAGES.map((l) => l.code);
  const localeFiles = files.filter((f) => f !== 'index.ts').map((f) => f.replace(/\.ts$/, ''));
  for (const c of codes) if (!localeFiles.includes(c)) err(c, 'есть в LANGUAGES, но нет файла src/locales/' + c + '.ts');
  for (const f of localeFiles) if (!codes.includes(f)) err(f, 'файл есть, но языка нет в LANGUAGES');
  if (new Set(codes).size !== codes.length) err('LANGUAGES', 'повторяющиеся коды');
  if (codes.slice(0, 3).join() !== 'en,uk,ru') err('LANGUAGES', 'первыми должны идти en, uk, ru');
  const collator = new Intl.Collator('en');
  const rest = LANGUAGES.slice(3).map((l) => l.nativeName);
  const sorted = [...rest].sort(collator.compare);
  if (rest.join('|') !== sorted.join('|')) err('LANGUAGES', `после en/uk/ru языки не по алфавиту; ожидается: ${sorted.join(', ')}`);
  for (const l of LANGUAGES) {
    try {
      Intl.getCanonicalLocales(l.htmlLang);
    } catch {
      err(l.code, `htmlLang "${l.htmlLang}" — некорректный тег BCP 47`);
    }
    if (!['ltr', 'rtl'].includes(l.dir)) err(l.code, `dir "${l.dir}" должен быть ltr или rtl`);
    if (!l.nativeName?.trim()) err(l.code, 'пустой nativeName');
  }

  // --- ключи и строки ------------------------------------------------------
  const FORMAT = /(?<![A-Za-z0-9])(PDF|TXT|DOCX|EPUB|FB2|AZW3|PPTX|HTML|MP3|MP4|OCR|Markdown|MD|Word)(?![A-Za-z0-9])/g;
  const formats = (s) => [...s.matchAll(FORMAT)].map((m) => (m[1] === 'Markdown' ? 'MD' : m[1]));
  // строки только из имен форматов и знаков («OCR», «PDF → Word») переводить не нужно
  const onlyFormats = (s) => s.replace(FORMAT, '').replace(/[\s()+\-→.,:/]/g, '') === '';

  const compare = (code, ref, loc, path) => {
    for (const key of Object.keys(ref)) {
      const p = path + key;
      if (!(key in loc)) {
        err(code, `нет ключа ${p}`);
      } else if (typeof ref[key] === 'object') {
        if (typeof loc[key] !== 'object' || loc[key] === null) err(code, `${p} должен быть объектом`);
        else compare(code, ref[key], loc[key], `${p}.`);
      } else if (typeof loc[key] !== 'string') {
        err(code, `${p} должен быть строкой`);
      } else if (!loc[key].trim()) {
        err(code, `пустая строка ${p}`);
      } else if (code !== 'en' && loc[key] === ref[key] && !onlyFormats(ref[key])) {
        warn(code, `${p} совпадает с английским: "${ref[key]}"`);
      }
    }
    for (const key of Object.keys(loc)) if (!(key in ref)) err(code, `лишний ключ ${path}${key}`);
  };

  for (const code of codes.filter((c) => localeFiles.includes(c))) {
    const loc = (await load(code)).default;
    compare(code, en, loc, '');
    for (const [id, tool] of Object.entries(en.tools)) {
      const title = loc.tools?.[id]?.t;
      if (typeof title !== 'string') continue;
      const lost = formats(tool.t).filter((f) => !formats(title).includes(f));
      if (lost.length) err(code, `tools.${id}.t: потеряно имя формата ${lost.join(', ')} в "${title}"`);
    }
  }

  const keyCount = (o) => Object.values(o).reduce((n, v) => n + (typeof v === 'object' ? keyCount(v) : 1), 0);
  console.log(`check-locales: ${codes.length} языков, по ${keyCount(en)} строк в каждом.`);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}

if (warnings.length) {
  console.log(`\nПредупреждения (${warnings.length}) — строки, совпадающие с английскими:`);
  for (const w of warnings) console.log(`  ⚠ ${w}`);
}
if (errors.length) {
  console.error(`\nОшибки (${errors.length}):`);
  for (const e of errors) console.error(`  ✗ ${e}`);
  process.exit(1);
}
console.log('\n✓ Все словари полные: нет пропущенных, лишних и пустых ключей.');
