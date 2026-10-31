import { describe, expect, it } from 'vitest';
import { en, type Messages } from './locales';
import { toolTextOf } from './toolText';

describe('toolTextOf', () => {
  it('uses the current language', () => {
    expect(toolTextOf(en, 'pdf-to-txt')).toEqual(en.tools['pdf-to-txt']);
  });
  it('falls back to English when a language lacks the tool', () => {
    const partial = { ...en, tools: {} } as unknown as Messages;
    expect(toolTextOf(partial, 'pdf-to-txt')).toEqual(en.tools['pdf-to-txt']);
  });
  it('shows the id for an unknown tool instead of crashing', () => {
    expect(toolTextOf(en, 'brand-new-tool')).toEqual({ t: 'brand-new-tool', d: '' });
  });
});
