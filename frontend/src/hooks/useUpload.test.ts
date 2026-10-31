// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { uploadAll, useUpload } from './useUpload';

afterEach(() => { vi.unstubAllGlobals(); });

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe('uploadAll', () => {
  it('keeps accepted files in order, remembers the last rejection, skips network errors', async () => {
    const answers = [
      () => reply(200, { id: 'a', ext: 'pdf', meta: {} }),
      () => reply(400, { code: 'UNSUPPORTED_FORMAT' }),
      () => { throw new TypeError('offline'); },
      () => reply(200, { id: 'd', ext: 'pdf', meta: {} }),
    ];
    let n = 0;
    vi.stubGlobal('fetch', vi.fn(async () => answers[n++]()));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const files = ['a.pdf', 'b.exe', 'c.pdf', 'd.pdf'].map((name) => new File(['x'], name));
    const { newFiles, rejected } = await uploadAll(files);
    expect(newFiles.map((f) => f.id)).toEqual(['a', 'd']);
    expect(newFiles[0]).toMatchObject({ name: 'a.pdf', size: 1, ext: 'pdf' });
    expect(rejected).toEqual({ code: 'UNSUPPORTED_FORMAT' });
  });
});

describe('useUpload.moveFile', () => {
  it('moves a file to the position of another, and ignores a drop on itself', () => {
    const { result } = renderHook(() => useUpload(null, () => {}, () => {}));
    const f = (id: string) => ({ id, name: id, size: 1, ext: 'pdf', meta: {} });
    act(() => result.current.setFiles([f('a'), f('b'), f('c')]));
    act(() => result.current.moveFile('a', 'c'));
    expect(result.current.files.map((x) => x.id)).toEqual(['b', 'c', 'a']);
    act(() => result.current.moveFile('b', 'b'));
    expect(result.current.files.map((x) => x.id)).toEqual(['b', 'c', 'a']);
  });
});
