// Карточка выбранного файла с метаданными исходника.
import { FileText, Info } from 'lucide-react';
import type { UploadedFile } from '../api';
import type { Messages } from '../locales';
import { MetaLine, MetaRows } from './MetaRows';

export function SourceInfo({ t, file }: { t: Messages; file: UploadedFile }) {
  return (
    <div className="p-6 bg-gray-50 border rounded-lg inline-block text-start relative min-w-[300px]">
        <FileText size={48} className="mx-auto mb-4 text-gray-400 block" />
        <p className="font-semibold text-lg text-center">{file.name}</p>

        <div className="mt-4 pt-4 border-t text-sm text-gray-600 space-y-1">
            <p className="font-bold flex items-center mb-2"><Info size={16} className="me-1"/> {t.sourceInfo}:</p>
            <MetaLine label={t.metaSize}>{(file.size/1024/1024).toFixed(2)} MB</MetaLine>
            <MetaRows t={t} meta={file.meta} fields={['pages', 'words', 'images']} />
        </div>
    </div>
  );
}
