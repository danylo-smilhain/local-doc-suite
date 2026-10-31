// Ошибка обработки: общий текст, причина от сервера, «попробовать снова».
import { AlertCircle } from 'lucide-react';
import type { Messages } from '../locales';

export function ErrorPanel({ t, message, onRetry }: { t: Messages; message: string; onRetry: () => void }) {
  return (
    <div>
      <AlertCircle className="mx-auto text-[#e5322d] mb-4" size={48} />
      <p className="text-red-600 font-semibold text-lg">{t.errorMsg}</p>
      {message && <p className="text-gray-600 text-sm mt-2">{message}</p>}
      <button onClick={(e) => { e.stopPropagation(); onRetry(); }} className="mt-4 text-gray-600 underline">{t.tryAgain}</button>
    </div>
  );
}
