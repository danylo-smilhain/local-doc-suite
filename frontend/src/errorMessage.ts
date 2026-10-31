import type { Messages } from './locales';

// Error body of the backend: { code, detail }. `code` is translated through
// t.errors; an unknown or missing code falls back to the server's text.
export type ApiErrorBody = { code?: string; detail?: unknown };

export const errorMessage = (t: Messages, body: ApiErrorBody | null): string => {
  if (!body) return '';
  const known = body.code ? (t.errors as Record<string, string>)[body.code] : undefined;
  if (known) return known;
  return typeof body.detail === 'string' ? body.detail : '';
};
