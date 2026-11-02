// Иконка инструмента (верстка без изменений, перенесена из App.tsx).
// --- ИКОНКИ ИНСТРУМЕНТОВ ---
// Документ в цвете формата результата с подписью формата, внизу слева —
// значок в цвете исходного формата: стрелка (конвертация), «+» (слияние)
// или «T» (распознавание текста). Цвета — привычные цвета форматов.
export type Fmt = 'pdf' | 'doc' | 'docx' | 'pptx' | 'txt' | 'md' | 'epub' | 'fb2' | 'azw3' | 'mobi' | 'html' | 'mp3' | 'mp4' | 'webm' | 'm4a' | 'img';

const FORMATS: Record<Fmt, { color: string; label: string }> = {
  pdf:  { color: '#e5322d', label: 'PDF' },
  doc:  { color: '#41a5ee', label: 'DOC' },
  docx: { color: '#2b579a', label: 'DOC' },
  pptx: { color: '#d04423', label: 'PPT' },
  txt:  { color: '#64748b', label: 'TXT' },
  md:   { color: '#1f2937', label: 'MD' },
  epub: { color: '#4d9a2a', label: 'EPUB' },
  fb2:  { color: '#7c3aed', label: 'FB2' },
  azw3: { color: '#e89a0c', label: 'AZW3' },
  mobi: { color: '#c2410c', label: 'MOBI' },
  html: { color: '#0e8fb0', label: 'HTML' },
  mp3:  { color: '#db2777', label: 'MP3' },
  mp4:  { color: '#6d28d9', label: 'MP4' },
  webm: { color: '#15803d', label: 'WEBM' },
  m4a:  { color: '#0f766e', label: 'M4A' },
  img:  { color: '#c58a06', label: 'IMG' },
};

export const FormatIcon = ({ from, to, kind = 'convert', size = 48 }: {
  from: Fmt; to: Fmt; kind?: 'convert' | 'merge' | 'ocr'; size?: number;
}) => {
  const target = FORMATS[to];
  const source = FORMATS[from];
  const fontSize = target.label.length <= 2 ? 11 : target.label.length === 3 ? 9.5 : 7.5;
  // Контур документа с загнутым углом (правый верхний)
  const page = 'M16 4h16l10 10v26a4 4 0 0 1-4 4H16a4 4 0 0 1-4-4V8a4 4 0 0 1 4-4z';
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      {kind === 'merge' && (
        // Второй лист позади — несколько файлов в один
        <path d={page} transform="translate(-5 -3)" fill={target.color} opacity={0.35} />
      )}
      <path d={page} fill={target.color} />
      <path d="M32 4v6a4 4 0 0 0 4 4h6z" fill="#ffffff" opacity={0.4} />
      <text x="27.5" y="27" textAnchor="middle" fontSize={fontSize} fontWeight={800}
            fontFamily="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
            fill="#ffffff" letterSpacing="0.2">{target.label}</text>
      {/* Значок источника: белое кольцо отделяет его от документа */}
      <circle cx="11" cy="38.5" r="9" fill="#ffffff" />
      <circle cx="11" cy="38.5" r="7" fill={source.color} />
      <g stroke="#ffffff" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" fill="none">
        {kind === 'merge' && <path d="M11 35.3v6.4M7.8 38.5h6.4" />}
        {kind === 'ocr' && <path d="M8 35.5h6M11 35.5v6.2" />}
        {kind === 'convert' && <path d="M7.6 38.5h6.6M11.6 35.9l2.6 2.6-2.6 2.6" />}
      </g>
    </svg>
  );
};
