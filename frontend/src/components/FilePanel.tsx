// Панель с выбранными файлами: загрузка, запуск, ход работы, результат, ошибка.
import { Loader2 } from 'lucide-react';
import type { FileMeta, UploadedFile } from '../api';
import type { Status } from '../hooks/types';
import type { Messages } from '../locales';
import type { Tool } from '../tools';
import { ErrorPanel } from './ErrorPanel';
import { MergeList } from './MergeList';
import { ResultPanel } from './ResultPanel';
import { SourceInfo } from './SourceInfo';

type Props = {
  t: Messages;
  status: Status;
  tool: Tool;
  title: string;
  files: UploadedFile[];
  outMeta: FileMeta | null;
  resultHref: string;
  errorText: string;
  onProcess: () => void;
  onReset: () => void;
  onRemove: (id: string) => void;
  onMove: (activeId: string, overId: string) => void;
  onAddMore: () => void;
};

export function FilePanel({ t, status, tool, title, files, outMeta, resultHref, errorText,
                            onProcess, onReset, onRemove, onMove, onAddMore }: Props) {
  return (
    <div className="space-y-6 relative z-20">
      {status === 'uploading' && <Loader2 className="animate-spin mx-auto text-[#e5322d]" size={48} />}

      {status === 'idle' && (
         <>
           {tool.category === 'merge' ? (
              <MergeList t={t} files={files} onRemove={onRemove} onMove={onMove} onAddMore={onAddMore} />
           ) : (
              <SourceInfo t={t} file={files[0]} />
           )}

           <div>
             <button onClick={onProcess} className="bg-[#e5322d] text-white font-bold py-3 px-8 rounded-lg text-lg shadow-md hover:bg-red-700 uppercase">
               {title}
             </button>
           </div>
         </>
      )}
      {status === 'converting' && (
        <div className="space-y-4 py-8">
          <Loader2 className="animate-spin mx-auto text-[#e5322d]" size={48} />
          <p className="text-xl font-semibold animate-pulse">{t.processing}</p>
        </div>
      )}
      {status === 'success' && (
        <ResultPanel t={t} outMeta={outMeta} href={resultHref} onAgain={onReset} />
      )}
      {status === 'error' && (
        <ErrorPanel t={t} message={errorText} onRetry={onReset} />
      )}
    </div>
  );
}
