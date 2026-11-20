import { describe, it, expect } from 'vitest';
import { isValidElement } from 'react';
import { toolsConfig, TOOL_MENU } from './App';
import { LANGUAGES, en, loadMessages } from './locales';

const columns = Object.entries(TOOL_MENU) as [string, readonly string[]][];
const menuIds = columns.flatMap(([, ids]) => ids);

describe('All tools menu grouping', () => {
  it('has the 7 expected columns in order, none empty', () => {
    expect(columns.map(([key]) => key)).toEqual(
      ['merge', 'convertFromPdf', 'convertToPdf', 'documents', 'ebooks', 'media', 'ocr']);
    columns.forEach(([, ids]) => expect(ids.length).toBeGreaterThan(0));
  });

  it('shows every tool in toolsConfig exactly once', () => {
    expect(toolsConfig.length).toBeGreaterThan(0);
    for (const { id } of toolsConfig) {
      expect(menuIds.filter((m) => m === id), `"${id}" must appear exactly once`).toHaveLength(1);
    }
  });

  it('has unique tool ids', () => {
    const ids = toolsConfig.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('gives every tool an icon element', () => {
    for (const tool of toolsConfig) {
      expect(isValidElement(tool.icon), `"${tool.id}" icon`).toBe(true);
    }
  });

  it('has an English locale entry (title and description) for every tool, and no orphan entries', () => {
    const texts = en.tools as Record<string, { t: string; d: string }>;
    for (const { id } of toolsConfig) {
      expect(texts[id]?.t, `tools.${id}.t`).toBeTruthy();
      expect(texts[id]?.d, `tools.${id}.d`).toBeTruthy();
    }
    expect(Object.keys(texts).sort()).toEqual(toolsConfig.map((t) => t.id).sort());
  });

  it('contains no id that is missing from toolsConfig', () => {
    const known = new Set(toolsConfig.map((t) => t.id));
    expect(menuIds.filter((id) => !known.has(id))).toEqual([]);
    expect(menuIds).toHaveLength(toolsConfig.length);
  });
});

describe('All tools menu translations', () => {
  const menuKeys = Object.keys(TOOL_MENU);
  const others = LANGUAGES.filter((l) => l.code !== 'en');
  // Real words that are spelled the same as in English in that language
  const sameAsEnglish: Record<string, string[]> = { nl: ['ebooks'], pt: ['ebooks'], id: ['media'] };

  it.each(others.map((l) => l.code))('%s has its own label and all 7 headings (not the English fallback)', async (code) => {
    const m = await loadMessages(code);
    expect(m.navAllTools, 'navAllTools').toBeTruthy();
    expect(m.navAllTools).not.toBe(en.navAllTools);
    expect(Object.keys(m.menuCategories ?? {})).toEqual(menuKeys);
    for (const key of menuKeys.filter((k) => k !== 'ocr' && !sameAsEnglish[code]?.includes(k))) {
      expect(m.menuCategories?.[key as keyof typeof TOOL_MENU], key).not.toBe(en.menuCategories[key as keyof typeof TOOL_MENU]);
    }
  });
});

describe('WebM tool texts are translated, not the English fallback', () => {
  type ToolTexts = Record<string, { t: string; d: string }>;
  it.each(LANGUAGES.filter((l) => l.code !== 'en').map((l) => l.code))('%s', async (code) => {
    const tools = (await loadMessages(code)).tools as ToolTexts;
    const english = en.tools as ToolTexts;
    for (const id of ['webm-to-mp3', 'webm-to-mp4']) {
      expect(tools[id], `${id} missing`).toBeDefined();
      expect(tools[id].t).toContain('WebM');
      expect(tools[id].d, `${id} description is still English`).not.toBe(english[id].d);
    }
  });
});

describe('MOBI, M4A and TS tool texts are translated, not the English fallback', () => {
  type ToolTexts = Record<string, { t: string; d: string }>;
  const expected: Record<string, string[]> = {
    'mobi-to-epub': ['MOBI', 'EPUB'], 'mobi-to-azw3': ['MOBI', 'AZW3'], 'mobi-to-pdf': ['MOBI', 'PDF'],
    'mobi-to-md': ['MOBI', 'Markdown'], 'm4a-to-mp3': ['M4A', 'MP3'],
    'ts-to-webm': ['TS', 'WebM'], 'ts-to-mp4': ['TS', 'MP4'], 'ts-to-mp3': ['TS', 'MP3'],
  };
  it.each(LANGUAGES.filter((l) => l.code !== 'en').map((l) => l.code))('%s', async (code) => {
    const tools = (await loadMessages(code)).tools as ToolTexts;
    const english = en.tools as ToolTexts;
    for (const [id, formats] of Object.entries(expected)) {
      expect(tools[id], `${id} missing`).toBeDefined();
      for (const f of formats) expect(tools[id].t, `${id} title`).toContain(f);
      expect(tools[id].d, `${id} description is still English`).not.toBe(english[id].d);
    }
  });
});

describe('PDF to PPTX comes as two tools, like PDF to Word', () => {
  type ToolTexts = Record<string, { t: string; d: string }>;
  it('has "No OCR" and "with OCR" in toolsConfig and the PDF menu', () => {
    const outs = Object.fromEntries(toolsConfig.map((t) => [t.id, t.out]));
    expect([outs['pdf-to-pptx'], outs['pdf-to-pptx-ocr']]).toEqual(['pptx', 'pptx-ocr']);
    expect(TOOL_MENU.convertFromPdf).toContain('pdf-to-pptx-ocr');
  });
  it.each(LANGUAGES.map((l) => l.code))('%s titles both name PPTX and OCR and differ', async (code) => {
    const tools = (await loadMessages(code)).tools as ToolTexts;
    const english = en.tools as ToolTexts;
    const [plain, ocr] = [tools['pdf-to-pptx'], tools['pdf-to-pptx-ocr']];
    for (const t of [plain, ocr]) {
      expect(t.t).toContain('PPTX');
      expect(t.t).toContain('OCR');
    }
    expect(plain.t).not.toBe(ocr.t);
    if (code !== 'en') expect(ocr.d, 'description is still English').not.toBe(english['pdf-to-pptx-ocr'].d);
  });
});

describe('Spreadsheets merge as XLSX and as XLS', () => {
  type ToolTexts = Record<string, { t: string; d: string }>;
  it('has both tools in toolsConfig and the Merge menu, each keeping its format', () => {
    const outs = Object.fromEntries(toolsConfig.map((t) => [t.id, t.out]));
    expect([outs['merge-xlsx'], outs['merge-xls']]).toEqual(['xlsx', 'xls']);
    expect(TOOL_MENU.merge).toEqual(expect.arrayContaining(['merge-xlsx', 'merge-xls']));
    expect(toolsConfig.find((t) => t.id === 'merge-xls')?.category).toBe('merge');
  });
  it.each(LANGUAGES.map((l) => l.code))('%s names the format in each title and translates the descriptions', async (code) => {
    const tools = (await loadMessages(code)).tools as ToolTexts;
    const english = en.tools as ToolTexts;
    expect(tools['merge-xlsx'].t).toContain('XLSX');
    expect(tools['merge-xls'].t).toMatch(/XLS(?!X)/);
    expect(tools['merge-xls'].t).not.toContain('XLSX');
    if (code !== 'en') {
      for (const id of ['merge-xlsx', 'merge-xls']) expect(tools[id].d, `${id} description is still English`).not.toBe(english[id].d);
    }
  });
});

describe('XLSX to XLS', () => {
  type ToolTexts = Record<string, { t: string; d: string }>;
  it('is a convert tool giving xls, in the Documents menu after DOC to DOCX', () => {
    const tool = toolsConfig.find((t) => t.id === 'xlsx-to-xls');
    expect([tool?.out, tool?.category]).toEqual(['xls', 'convert']);
    const docs = TOOL_MENU.documents;
    expect(docs.indexOf('xlsx-to-xls')).toBe(docs.indexOf('doc-to-docx') + 1);
  });
  it.each(LANGUAGES.map((l) => l.code))('%s names both formats and translates the description', async (code) => {
    const text = ((await loadMessages(code)).tools as ToolTexts)['xlsx-to-xls'];
    expect(text.t).toContain('XLSX');
    expect(text.t.replace('XLSX', '')).toMatch(/XLS(?!X)/);
    if (code !== 'en') expect(text.d).not.toBe((en.tools as ToolTexts)['xlsx-to-xls'].d);
  });
});
