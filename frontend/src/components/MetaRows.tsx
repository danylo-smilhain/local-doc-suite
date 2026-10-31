// Строки метаданных «Подпись: значение»; поля со значением 'N/A' скрыты,
// длительность показывается, только если она есть.
import type { ReactNode } from 'react';
import type { FileMeta } from '../api';
import type { Messages } from '../locales';
import { formatDuration } from '../names';

export const MetaLine = ({ label, children }: { label: string; children: ReactNode }) => (
  <p><span className="text-gray-400">{label}:</span> {children}</p>
);

const LABELS = { pages: 'metaPages', words: 'metaWords', images: 'metaImages' } as const;
type Field = keyof typeof LABELS;

export function MetaRows({ t, meta, fields }: { t: Messages; meta: FileMeta | undefined; fields: Field[] }) {
  const m = meta || {};
  return (
    <>
      {fields.map((f) => m[f] !== 'N/A' && <MetaLine key={f} label={t[LABELS[f]]}>{m[f]}</MetaLine>)}
      {typeof m.duration === 'number' && <MetaLine label={t.metaDuration}>{formatDuration(m.duration)}</MetaLine>}
    </>
  );
}
