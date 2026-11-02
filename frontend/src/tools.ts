// Каталог инструментов: id, иконка, формат результата и категория.
// Порядок здесь — порядок карточек на главной странице.
import { createElement, type ReactElement } from 'react';
import { FormatIcon, type Fmt } from './FormatIcon';

export type ToolCategory = 'convert' | 'merge' | 'ocr';
export type Tool = { id: string; icon: ReactElement; out: string; category: ToolCategory };

const icon = (props: { from: Fmt; to: Fmt; kind?: 'convert' | 'merge' | 'ocr' }) => createElement(FormatIcon, props);

export const toolsConfig: Tool[] = [
  { id: 'pdf-to-txt', icon: icon({ from: 'pdf', to: 'txt' }), out: 'txt', category: 'convert' },
  { id: 'pdf-to-md', icon: icon({ from: 'pdf', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'pdf-to-word', icon: icon({ from: 'pdf', to: 'docx' }), out: 'docx', category: 'convert' },
  { id: 'pdf-to-word-ocr', icon: icon({ from: 'pdf', to: 'docx', kind: 'ocr' }), out: 'docx-ocr', category: 'convert' },
  { id: 'pdf-to-epub', icon: icon({ from: 'pdf', to: 'epub' }), out: 'epub', category: 'convert' },
  { id: 'pdf-to-fb2', icon: icon({ from: 'pdf', to: 'fb2' }), out: 'fb2', category: 'convert' },
  { id: 'pdf-to-pptx', icon: icon({ from: 'pdf', to: 'pptx' }), out: 'pptx', category: 'convert' },
  { id: 'word-to-txt', icon: icon({ from: 'docx', to: 'txt' }), out: 'txt', category: 'convert' },
  { id: 'word-to-md', icon: icon({ from: 'docx', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'word-to-epub', icon: icon({ from: 'docx', to: 'epub' }), out: 'epub', category: 'convert' },
  { id: 'word-to-fb2', icon: icon({ from: 'docx', to: 'fb2' }), out: 'fb2', category: 'convert' },
  { id: 'word-to-pdf', icon: icon({ from: 'docx', to: 'pdf' }), out: 'pdf', category: 'convert' },
  { id: 'doc-to-docx', icon: icon({ from: 'doc', to: 'docx' }), out: 'docx', category: 'convert' },
  { id: 'epub-to-pdf', icon: icon({ from: 'epub', to: 'pdf' }), out: 'pdf', category: 'convert' },
  { id: 'epub-to-md', icon: icon({ from: 'epub', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'fb2-to-pdf', icon: icon({ from: 'fb2', to: 'pdf' }), out: 'pdf', category: 'convert' },
  { id: 'fb2-to-md', icon: icon({ from: 'fb2', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'azw3-to-epub', icon: icon({ from: 'azw3', to: 'epub' }), out: 'epub', category: 'convert' },
  { id: 'azw3-to-pdf', icon: icon({ from: 'azw3', to: 'pdf' }), out: 'pdf', category: 'convert' },
  { id: 'azw3-to-md', icon: icon({ from: 'azw3', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'mobi-to-epub', icon: icon({ from: 'mobi', to: 'epub' }), out: 'epub', category: 'convert' },
  { id: 'mobi-to-azw3', icon: icon({ from: 'mobi', to: 'azw3' }), out: 'azw3', category: 'convert' },
  { id: 'mobi-to-pdf', icon: icon({ from: 'mobi', to: 'pdf' }), out: 'pdf', category: 'convert' },
  { id: 'mobi-to-md', icon: icon({ from: 'mobi', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'html-to-md', icon: icon({ from: 'html', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'html-to-pdf', icon: icon({ from: 'html', to: 'pdf' }), out: 'pdf', category: 'convert' },
  { id: 'html-to-docx', icon: icon({ from: 'html', to: 'docx' }), out: 'docx', category: 'convert' },
  { id: 'html-to-txt', icon: icon({ from: 'html', to: 'txt' }), out: 'txt', category: 'convert' },
  { id: 'md-to-txt', icon: icon({ from: 'md', to: 'txt' }), out: 'txt', category: 'convert' },
  { id: 'txt-to-md', icon: icon({ from: 'txt', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'pptx-to-pdf', icon: icon({ from: 'pptx', to: 'pdf' }), out: 'pdf', category: 'convert' },
  { id: 'pptx-to-docx', icon: icon({ from: 'pptx', to: 'docx' }), out: 'docx', category: 'convert' },
  { id: 'pptx-to-md', icon: icon({ from: 'pptx', to: 'md' }), out: 'md', category: 'convert' },
  { id: 'mp4-to-mp3', icon: icon({ from: 'mp4', to: 'mp3' }), out: 'mp3', category: 'convert' },
  { id: 'webm-to-mp3', icon: icon({ from: 'webm', to: 'mp3' }), out: 'mp3', category: 'convert' },
  { id: 'webm-to-mp4', icon: icon({ from: 'webm', to: 'mp4' }), out: 'mp4', category: 'convert' },
  { id: 'm4a-to-mp3', icon: icon({ from: 'm4a', to: 'mp3' }), out: 'mp3', category: 'convert' },
  { id: 'ts-to-webm', icon: icon({ from: 'ts', to: 'webm' }), out: 'webm', category: 'convert' },
  { id: 'ts-to-mp4', icon: icon({ from: 'ts', to: 'mp4' }), out: 'mp4', category: 'convert' },
  { id: 'ts-to-mp3', icon: icon({ from: 'ts', to: 'mp3' }), out: 'mp3', category: 'convert' },
  { id: 'merge-docx', icon: icon({ from: 'docx', to: 'docx', kind: 'merge' }), out: 'docx', category: 'merge' },
  { id: 'merge-pdf', icon: icon({ from: 'pdf', to: 'pdf', kind: 'merge' }), out: 'pdf', category: 'merge' },
  { id: 'merge-txt', icon: icon({ from: 'txt', to: 'txt', kind: 'merge' }), out: 'txt', category: 'merge' },
  { id: 'merge-md', icon: icon({ from: 'md', to: 'md', kind: 'merge' }), out: 'md', category: 'merge' },
  { id: 'merge-pptx', icon: icon({ from: 'pptx', to: 'pptx', kind: 'merge' }), out: 'pptx', category: 'merge' },
  { id: 'merge-html', icon: icon({ from: 'html', to: 'html', kind: 'merge' }), out: 'html', category: 'merge' },
  { id: 'merge-epub', icon: icon({ from: 'epub', to: 'epub', kind: 'merge' }), out: 'epub', category: 'merge' },
  { id: 'merge-fb2', icon: icon({ from: 'fb2', to: 'fb2', kind: 'merge' }), out: 'fb2', category: 'merge' },
  { id: 'merge-txt-md', icon: icon({ from: 'txt', to: 'md', kind: 'merge' }), out: 'md', category: 'merge' },
  { id: 'merge-docx-md', icon: icon({ from: 'docx', to: 'md', kind: 'merge' }), out: 'md', category: 'merge' },
  { id: 'merge-pdf-md', icon: icon({ from: 'pdf', to: 'md', kind: 'merge' }), out: 'md', category: 'merge' },
  { id: 'merge-html-md', icon: icon({ from: 'html', to: 'md', kind: 'merge' }), out: 'md', category: 'merge' },
  { id: 'merge-html-pdf', icon: icon({ from: 'html', to: 'pdf', kind: 'merge' }), out: 'pdf', category: 'merge' },
  { id: 'ocr-to-txt', icon: icon({ from: 'img', to: 'txt', kind: 'ocr' }), out: 'txt', category: 'ocr' },
  { id: 'ocr-to-md', icon: icon({ from: 'img', to: 'md', kind: 'ocr' }), out: 'md', category: 'ocr' }
];

// Меню «All tools»: единственное место, где инструменты сгруппированы по колонкам.
// Ключ — категория (подпись в t.menuCategories), значение — упорядоченные id из toolsConfig.
export const TOOL_MENU = {
  merge: ['merge-docx', 'merge-pdf', 'merge-txt', 'merge-md', 'merge-pptx', 'merge-html', 'merge-epub',
    'merge-fb2', 'merge-txt-md', 'merge-docx-md', 'merge-pdf-md', 'merge-html-md', 'merge-html-pdf'],
  convertFromPdf: ['pdf-to-txt', 'pdf-to-md', 'pdf-to-word', 'pdf-to-word-ocr', 'pdf-to-epub', 'pdf-to-fb2', 'pdf-to-pptx'],
  convertToPdf: ['word-to-pdf', 'epub-to-pdf', 'fb2-to-pdf', 'azw3-to-pdf', 'mobi-to-pdf', 'html-to-pdf', 'pptx-to-pdf'],
  documents: ['doc-to-docx', 'word-to-txt', 'word-to-md', 'html-to-md', 'html-to-docx', 'html-to-txt', 'md-to-txt', 'txt-to-md',
    'pptx-to-docx', 'pptx-to-md'],
  ebooks: ['word-to-epub', 'word-to-fb2', 'epub-to-md', 'fb2-to-md', 'azw3-to-epub', 'azw3-to-md',
    'mobi-to-epub', 'mobi-to-azw3', 'mobi-to-md'],
  media: ['mp4-to-mp3', 'webm-to-mp3', 'webm-to-mp4', 'm4a-to-mp3', 'ts-to-webm', 'ts-to-mp4', 'ts-to-mp3'],
  ocr: ['ocr-to-txt', 'ocr-to-md'],
} as const;
