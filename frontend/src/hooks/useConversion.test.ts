// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useConversion } from './useConversion';
import type { Tool } from '../tools';

afterEach(() => { vi.unstubAllGlobals(); });

const file = { id: 'a', name: 'deck.pdf', size: 1, ext: 'pdf', meta: {} };
const tool = { id: 'pdf-to-pptx', out: 'pptx' } as Tool;
const answer = (body: object) => vi.fn(async () => new Response(JSON.stringify(body)));

describe('useConversion.warnings', () => {
  it('keeps what the server warned about, and forgets it on the next conversion', async () => {
    const hint = '32 page(s) have no usable text layer; use PDF to PPTX (with OCR).';
    vi.stubGlobal('fetch', answer({ status: 'success', download_id: 'x', meta: {}, warnings: [hint] }));
    const { result } = renderHook(() => useConversion(() => {}, () => {}, () => {}));
    await act(() => result.current.process([file], tool));
    expect(result.current.warnings).toEqual([hint]);

    vi.stubGlobal('fetch', answer({ status: 'success', download_id: 'y', meta: {} }));
    await act(() => result.current.process([file], tool));
    expect(result.current.warnings).toEqual([]);
  });
});
