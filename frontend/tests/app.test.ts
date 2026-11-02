// @vitest-environment jsdom
//
// Behavior of the whole page, the way a user sees it: pick a tool, drop a
// file, convert, download. fetch is replaced by a fake backend.
// The DOM snapshots pin the markup, so refactoring App.tsx into smaller
// modules must leave them byte-for-byte identical ("no visual changes").
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createElement } from 'react';
import App from '../src/App';

const API = 'http://127.0.0.1:8000/api';

type Reply = { status?: number; body: unknown };

function fakeBackend(convertReply: Reply) {
  const calls: { url: string; form: Record<string, string> }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const form: Record<string, string> = {};
    (init?.body as FormData | undefined)?.forEach((v, k) => { form[k] = typeof v === 'string' ? v : (v as File).name; });
    calls.push({ url, form });
    if (url.endsWith('/upload')) {
      const name = form.file;
      const ext = name.split('.').pop()!.toLowerCase();
      return new Response(JSON.stringify({
        id: `id-${calls.length}`, ext, original_name: name,
        meta: { size: 2048, pages: 3, words: 120, chars: 600, images: 'N/A' },
      }));
    }
    return new Response(JSON.stringify(convertReply.body), { status: convertReply.status ?? 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

const fileInput = (c: HTMLElement) => c.querySelector('input[type="file"]') as HTMLInputElement;

async function dropFiles(container: HTMLElement, ...names: string[]) {
  const list = names.map((n) => new File(['x'.repeat(10)], n));
  await act(async () => { fireEvent.change(fileInput(container), { target: { files: list } }); });
}

function openTool(title: string) {
  fireEvent.click(screen.getByRole('heading', { level: 3, name: title }));
}

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-01-02T03:04:05Z'));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('home page', () => {
  it('lists every tool as a card', () => {
    render(createElement(App));
    const cards = screen.getAllByRole('heading', { level: 3 });
    expect(cards.map((h) => h.textContent)).toContain('PDF to TXT');
    expect(cards.map((h) => h.textContent)).toContain('DOC to DOCX');
    for (const title of ['MOBI to EPUB', 'MOBI to AZW3', 'MOBI to PDF', 'MOBI to Markdown', 'M4A to MP3']) {
      expect(cards.map((h) => h.textContent)).toContain(title);
    }
    expect(cards).toHaveLength(52);
  });

  it('filters tools by the MERGE / CONVERT / OCR buttons', () => {
    render(createElement(App));
    fireEvent.click(screen.getByRole('button', { name: 'MERGE' }));
    const merge = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(merge.every((t) => /Merge|\(Merge\)/.test(t ?? ''))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'OCR' }));
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent))
      .toEqual(['Image to TXT', 'Image to Markdown']);
  });

  it('opens the All tools menu and starts a tool from it', () => {
    const { container } = render(createElement(App));
    fireEvent.click(screen.getByRole('button', { name: /All tools/ }));
    const menu = screen.getByRole('navigation', { name: 'All tools' });
    expect(within(menu).getAllByRole('button')).toHaveLength(52);
    fireEvent.click(within(menu).getByRole('button', { name: 'WebM to MP4' }));
    expect(screen.getByRole('heading', { level: 2, name: 'WebM to MP4' })).toBeTruthy();
    expect(container.querySelector('#all-tools-menu')).toBeNull();
  });

  it('matches the markup snapshot', () => {
    const { container } = render(createElement(App));
    expect(container.innerHTML).toMatchSnapshot();
  });

  it('matches the markup snapshot with the menu open', () => {
    const { container } = render(createElement(App));
    fireEvent.click(screen.getByRole('button', { name: /All tools/ }));
    expect(container.innerHTML).toMatchSnapshot();
  });
});

describe('All tools menu closing', () => {
  it('closes on Escape and gives focus back to the button', () => {
    render(createElement(App));
    const button = screen.getByRole('button', { name: /All tools/ });
    fireEvent.click(button);
    expect(screen.getByRole('navigation', { name: 'All tools' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(screen.queryByRole('navigation', { name: 'All tools' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('navigation', { name: 'All tools' })).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it('closes on a click outside, but not on a click inside the panel', () => {
    render(createElement(App));
    fireEvent.click(screen.getByRole('button', { name: /All tools/ }));
    const menu = screen.getByRole('navigation', { name: 'All tools' });
    fireEvent.pointerDown(within(menu).getAllByRole('heading')[0]);
    expect(screen.queryByRole('navigation', { name: 'All tools' })).toBeTruthy();
    fireEvent.pointerDown(screen.getByRole('heading', { level: 1 }));
    expect(screen.queryByRole('navigation', { name: 'All tools' })).toBeNull();
  });

  it('toggles with its own button', () => {
    render(createElement(App));
    const button = screen.getByRole('button', { name: /All tools/ });
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    fireEvent.pointerDown(button);
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('false');
  });
});

describe('history', () => {
  it('lists saved results with download links named after the source', () => {
    localStorage.setItem('docHistory', JSON.stringify([
      { id: Date.UTC(2026, 0, 2, 3, 4, 5), tool: 'EPUB to Markdown', source: 'Book.epub', result: 'converted_1.md', date: 'x' },
      { id: 'legacy', tool: 'Merge PDF', source: '2 files', result: 'merged_2.pdf', date: 'old date' },
    ]));
    render(createElement(App));
    expect(screen.getByText('Recent Conversions')).toBeTruthy();
    const links = screen.getAllByRole('link', { name: 'Download' }) as HTMLAnchorElement[];
    expect(links.map((a) => a.href)).toEqual([
      `${API}/download/converted_1.md?name=Book.md`,
      `${API}/download/merged_2.pdf?name=Merged_Document.pdf`,
    ]);
    expect(screen.getByText('old date')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Clear History' }));
    expect(screen.queryByText('Recent Conversions')).toBeNull();
    expect(localStorage.getItem('docHistory')).toBe('[]');
  });
});

describe('single-file conversion', () => {
  it('uploads, converts and offers the result under the original name', async () => {
    const calls = fakeBackend({ body: { status: 'success', download_id: 'converted_abc.txt', meta: { size: 1048576, pages: 'N/A', words: 42 } } });
    const { container } = render(createElement(App));
    openTool('PDF to TXT');
    await dropFiles(container, 'Report.final.pdf');
    await waitFor(() => screen.getByText('Report.final.pdf'));
    expect(container.innerHTML).toMatchSnapshot('file selected');

    fireEvent.click(screen.getByRole('button', { name: 'PDF to TXT' }));
    await waitFor(() => screen.getByText('Task completed successfully!'));

    expect(calls[0].url).toBe(`${API}/upload`);
    expect(calls[1]).toEqual({ url: `${API}/convert`, form: { file_id: 'id-1', target_format: 'txt', source_ext: 'pdf' } });
    const link = screen.getByRole('link', { name: /Download Result/ }) as HTMLAnchorElement;
    expect(link.href).toBe(`${API}/download/converted_abc.txt?name=Report.final.txt`);
    expect(container.innerHTML).toMatchSnapshot('success');

    const history = JSON.parse(localStorage.getItem('docHistory')!);
    expect(history[0]).toMatchObject({ tool: 'PDF to TXT', source: 'Report.final.pdf', result: 'converted_abc.txt' });
  });

  it('sends docx-ocr for "PDF to Word (with OCR)" and names the result .docx', async () => {
    const calls = fakeBackend({ body: { status: 'success', download_id: 'converted_x.docx', meta: { size: 10, pages: 1, words: 1 } } });
    const { container } = render(createElement(App));
    openTool('PDF to Word (with OCR)');
    await dropFiles(container, 'scan.pdf');
    await waitFor(() => screen.getByText('scan.pdf'));
    fireEvent.click(screen.getByRole('button', { name: 'PDF to Word (with OCR)' }));
    await waitFor(() => screen.getByText('Task completed successfully!'));
    expect(calls[1].form.target_format).toBe('docx-ocr');
    expect((screen.getByRole('link', { name: /Download Result/ }) as HTMLAnchorElement).href).toContain('name=scan.docx');
  });

  it('shows the server reason when conversion fails', async () => {
    fakeBackend({ status: 422, body: { detail: 'The book is DRM protected' } });
    const { container } = render(createElement(App));
    openTool('AZW3 to EPUB');
    await dropFiles(container, 'book.azw3');
    await waitFor(() => screen.getByText('book.azw3'));
    fireEvent.click(screen.getByRole('button', { name: 'AZW3 to EPUB' }));
    await waitFor(() => screen.getByText('An error occurred during processing.'));
    expect(screen.getByText('The book is DRM protected')).toBeTruthy();
    expect(container.innerHTML).toMatchSnapshot('error');
  });

  it('stays on the drop zone when the upload cannot reach the server (current behavior, see NOTES.md)', async () => {
    const fetchMock = vi.fn(async () => { throw new TypeError('Failed to fetch'); });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { container } = render(createElement(App));
    openTool('PDF to TXT');
    await dropFiles(container, 'a.pdf');
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    // status becomes "error", but the error block only renders once a file is listed
    expect(screen.getByText('Select file(s)')).toBeTruthy();
    expect(screen.queryByText('An error occurred during processing.')).toBeNull();
  });
});

describe('error codes from the server', () => {
  it('translates the code, also after switching language', async () => {
    fakeBackend({ status: 422, body: { code: 'EBOOK_DRM_PROTECTED', detail: 'The file is DRM-protected (KFX/Kindle)' } });
    const { container } = render(createElement(App));
    openTool('AZW3 to EPUB');
    await dropFiles(container, 'book.azw3');
    await waitFor(() => screen.getByText('book.azw3'));
    fireEvent.click(screen.getByRole('button', { name: 'AZW3 to EPUB' }));
    await waitFor(() => screen.getByText('The book is DRM-protected. Only DRM-free books can be converted.'));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'uk' } });
    await waitFor(() => screen.getByText('Книгу захищено DRM. Конвертувати можна лише книги без DRM.'));
  });

  it('falls back to the detail text for an unknown code', async () => {
    fakeBackend({ status: 500, body: { code: 'SOMETHING_NEW', detail: 'engine exploded' } });
    const { container } = render(createElement(App));
    openTool('PDF to TXT');
    await dropFiles(container, 'a.pdf');
    await waitFor(() => screen.getByText('a.pdf'));
    fireEvent.click(screen.getByRole('button', { name: 'PDF to TXT' }));
    await waitFor(() => screen.getByText('engine exploded'));
  });

  it('does not list a file the server rejected and says why', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ code: 'UNSUPPORTED_FORMAT', detail: "Unsupported file type: 'exe'" }), { status: 400 }));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = render(createElement(App));
    openTool('PDF to TXT');
    await dropFiles(container, 'virus.exe');
    await waitFor(() => screen.getByRole('alert'));
    expect(screen.getByRole('alert').textContent).toBe('This file type is not supported.');
    expect(screen.queryByText('virus.exe')).toBeNull();
    expect(screen.getByText('Select file(s)')).toBeTruthy();
  });
});

describe('merge', () => {
  it('collects several files and sends their ids in order', async () => {
    const calls = fakeBackend({ body: { status: 'success', download_id: 'merged_1.pdf', meta: { size: 10, pages: 2, words: 5 } } });
    const { container } = render(createElement(App));
    openTool('Merge PDF');
    await dropFiles(container, 'one.pdf', 'two.pdf');
    await waitFor(() => screen.getByText('two.pdf'));
    fireEvent.click(screen.getByRole('button', { name: 'Merge PDF' }));
    await waitFor(() => screen.getByText('Task completed successfully!'));
    expect(calls[calls.length - 1].form.file_id).toBe('id-1,id-2');
    expect((screen.getByRole('link', { name: /Download Result/ }) as HTMLAnchorElement).href)
      .toContain('name=Merged_one.pdf');
  });
});

describe('drop zone limits', () => {
  it('a single-file tool rejects several files at once and lists none (current behavior)', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { container } = render(createElement(App));
    openTool('PDF to TXT');
    await dropFiles(container, 'a.pdf', 'b.pdf');
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText('Select file(s)')).toBeTruthy();
  });

  it('removes a file from the merge list', async () => {
    fakeBackend({ body: { status: 'success', download_id: 'merged_1.pdf', meta: { size: 1, pages: 1, words: 1 } } });
    const { container } = render(createElement(App));
    openTool('Merge PDF');
    await dropFiles(container, 'one.pdf', 'two.pdf');
    await waitFor(() => screen.getByText('two.pdf'));
    const row = screen.getByText('one.pdf').closest('div.p-4') as HTMLElement;
    fireEvent.click(row.querySelector('button')!);
    expect(screen.queryByText('one.pdf')).toBeNull();
    expect(screen.getByText('two.pdf')).toBeTruthy();
  });

  it('shows the duration of a media file and of the result', async () => {
    const calls = fakeBackend({ body: { status: 'success', download_id: 'converted_v.mp3', meta: { size: 5, pages: 'N/A', words: 'N/A', duration: 3725 } } });
    const { container } = render(createElement(App));
    openTool('MP4 to MP3');
    await dropFiles(container, 'clip.mp4');
    await waitFor(() => screen.getByText('clip.mp4'));
    fireEvent.click(screen.getByRole('button', { name: 'MP4 to MP3' }));
    await waitFor(() => screen.getByText('Task completed successfully!'));
    expect(screen.getByText('1:02:05')).toBeTruthy();
    expect(calls[1].form.target_format).toBe('mp3');
  });
});

describe('language', () => {
  it('switches the interface language and remembers it', async () => {
    render(createElement(App));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'uk' } });
    await waitFor(() => expect(document.documentElement.lang).toBe('uk'));
    expect(localStorage.getItem('docLang')).toBe('uk');
    expect(screen.queryByText('Every tool you need to work with documents locally')).toBeNull();
  });
});
