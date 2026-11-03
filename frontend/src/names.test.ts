import { describe, expect, it } from 'vitest';
import { formatDuration, getDownloadName, getHistoryDownloadName } from './names';
import { toolsConfig } from './tools';

const tool = (id: string) => toolsConfig.find((t) => t.id === id)!;
const file = (name: string) => ({ id: name, name, size: 1, ext: name.split('.').pop()!, meta: {} });

describe('formatDuration', () => {
  it.each([[0, '0:00'], [5.4, '0:05'], [65, '1:05'], [3599.6, '1:00:00'], [3725, '1:02:05'], [-3, '0:00']])(
    '%s s -> %s', (s, out) => expect(formatDuration(s)).toBe(out));
});

describe('getDownloadName', () => {
  it('keeps the base name and uses the tool output extension', () => {
    expect(getDownloadName([file('My.Report.pdf')], tool('pdf-to-md'))).toBe('My.Report.md');
  });
  it('maps pptx-ocr to .pptx', () => {
    expect(getDownloadName([file('Lesson 1.pdf')], tool('pdf-to-pptx-ocr'))).toBe('Lesson 1.pptx');
  });

  it('maps docx-ocr to .docx', () => {
    expect(getDownloadName([file('scan.pdf')], tool('pdf-to-word-ocr'))).toBe('scan.docx');
  });
  it('prefixes merged results only when several files are merged', () => {
    expect(getDownloadName([file('a.pdf'), file('b.pdf')], tool('merge-pdf'))).toBe('Merged_a.pdf');
    expect(getDownloadName([file('a.pdf')], tool('merge-pdf'))).toBe('a.pdf');
  });
  it('falls back to "document"', () => {
    expect(getDownloadName([], tool('pdf-to-md'))).toBe('document');
    expect(getDownloadName([file('a.pdf')], null)).toBe('document');
  });
});

describe('getHistoryDownloadName', () => {
  it('names merged results generically', () => {
    expect(getHistoryDownloadName('3 files', 'merged_x.pdf')).toBe('Merged_Document.pdf');
  });
  it('reuses the source name with the result extension', () => {
    expect(getHistoryDownloadName('Book.epub', 'converted_x.md')).toBe('Book.md');
  });
});
