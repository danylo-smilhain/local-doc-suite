import { describe, expect, it } from 'vitest';
import { errorMessage } from './errorMessage';
import { LANGUAGES, en, loadMessages } from './locales';

describe('errorMessage', () => {
  it('translates a known code', () => {
    expect(errorMessage(en, { code: 'FILE_NOT_FOUND', detail: 'x' })).toBe(en.errors.FILE_NOT_FOUND);
  });
  it('falls back to a string detail', () => {
    expect(errorMessage(en, { code: 'NOPE', detail: 'raw reason' })).toBe('raw reason');
    expect(errorMessage(en, { detail: 'raw reason' })).toBe('raw reason');
  });
  it('ignores a non-string detail (FastAPI validation list) and nothing at all', () => {
    expect(errorMessage(en, { detail: [{ loc: ['body'] }] })).toBe('');
    expect(errorMessage(en, null)).toBe('');
  });
  it.each(LANGUAGES.map((l) => l.code))('%s has a non-empty text for every error code', async (code) => {
    const m = await loadMessages(code);
    for (const key of Object.keys(en.errors)) {
      expect((m.errors as Record<string, string>)[key], key).toBeTruthy();
    }
  });
});
