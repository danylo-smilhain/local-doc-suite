// Готово: метаданные результата и кнопка скачивания.
import { CheckCircle, Download, Info } from 'lucide-react';
import type { FileMeta } from '../api';
import type { Messages } from '../locales';
import { MetaLine, MetaRows } from './MetaRows';

type Props = { t: Messages; outMeta: FileMeta | null; href: string; onAgain: () => void };

export function ResultPanel({ t, outMeta, href, onAgain }: Props) {
  return (
    <div className="space-y-6">
      <CheckCircle className="mx-auto text-green-500" size={64} />
      <h3 className="text-2xl font-bold">{t.success}</h3>

      {outMeta && (
          <div className="inline-block text-start text-sm text-gray-600 bg-gray-50 p-4 rounded-lg border mb-4 min-w-[250px]">
              <p className="font-bold flex items-center mb-2 text-black"><Info size={16} className="me-1"/> {t.outputInfo}:</p>
              <MetaLine label={t.metaSize}>{(outMeta.size/1024/1024).toFixed(2)} MB</MetaLine>
                <MetaRows t={t} meta={outMeta} fields={['pages', 'words']} />
          </div>
      )}

      <div>
          <a href={href} download className="inline-flex items-center bg-[#222222] text-white font-bold py-4 px-8 rounded-lg text-xl hover:bg-black transition">
            <Download className="me-2" /> {t.downloadBtn}
          </a>
      </div>
      <div><button onClick={(e) => { e.stopPropagation(); onAgain(); }} className="text-[#e5322d] font-semibold mt-4 hover:underline">{t.anotherBtn}</button></div>
    </div>
  );
}
