// Pure helpers for what the page displays and how results are named.
import type { UploadedFile } from './api';
import type { Tool } from './tools';

// Длительность в секундах -> «m:ss» или «h:mm:ss» (для MP4/MP3)
export const formatDuration = (seconds: number) => {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const ss = String(total % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
};

export const getDownloadName = (files: UploadedFile[], tool: Tool | null) => {
  if (!files || files.length === 0 || !tool) return `document`;
  const baseName = files[0].name.replace(/\.[^/.]+$/, '');
  // 'docx-ocr', 'pptx-ocr': the same file type made with OCR (as TargetFormat.out_ext)
  const ext = tool.out.replace(/-ocr$/, '');
  if (tool.category === 'merge' && files.length > 1) {
    return `Merged_${baseName}.${ext}`;
  }
  return `${baseName}.${ext}`;
};

export const getHistoryDownloadName = (source: string, result: string) => {
  const ext = result.split('.').pop();
  if (source.includes('files')) return `Merged_Document.${ext}`;
  return `${source.replace(/\.[^/.]+$/, '')}.${ext}`;
};
