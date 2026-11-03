// The three backend calls. Network failures throw; server-side errors are
// returned as data so the caller can show the translated reason.
import type { ApiErrorBody } from './errorMessage';

export const API_URL = 'http://127.0.0.1:8000/api';

export type FileMeta = Record<string, any>;
export type UploadedFile = { id: string; name: string; size: number; ext: string; meta: FileMeta };
export type UploadReply = { ok: true; file: UploadedFile } | { ok: false; error: ApiErrorBody };
// warnings: what the server wants the user to know about the result (in English)
export type ConvertSuccess = { status: 'success'; download_id: string; meta: FileMeta; warnings?: string[] };
export type ConvertReply = ConvertSuccess | (ApiErrorBody & { status?: undefined });

export async function uploadFile(f: File): Promise<UploadReply> {
  const formData = new FormData();
  formData.append('file', f);
  const res = await fetch(`${API_URL}/upload`, { method: 'POST', body: formData });
  const data = await res.json();
  if (!res.ok) return { ok: false, error: data };
  return { ok: true, file: { id: data.id, name: f.name, size: f.size, ext: data.ext, meta: data.meta } };
}

export async function convertFiles(files: UploadedFile[], targetFormat: string): Promise<ConvertReply> {
  const formData = new FormData();
  formData.append('file_id', files.map((f) => f.id).join(','));
  formData.append('target_format', targetFormat);
  formData.append('source_ext', files[0].ext);
  const res = await fetch(`${API_URL}/convert`, { method: 'POST', body: formData });
  return res.json();
}

export const downloadUrl = (downloadId: string, name: string) =>
  `${API_URL}/download/${downloadId}?name=${encodeURIComponent(name)}`;
