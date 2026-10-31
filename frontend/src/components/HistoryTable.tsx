// «Recent Conversions»: последние 10 результатов из localStorage.
import { Clock } from 'lucide-react';
import { downloadUrl } from '../api';
import type { Messages } from '../locales';
import { getHistoryDownloadName } from '../names';
import type { HistoryRecord } from '../hooks/useHistory';


type Props = { t: Messages; history: HistoryRecord[]; formatDate: (h: HistoryRecord) => string; onClear: () => void };

export function HistoryTable({ t, history, formatDate: formatHistoryDate, onClear }: Props) {
  return (
    <div className="bg-white rounded-xl shadow-sm p-6">
        <div className="flex justify-between items-center mb-4">
            <h3 className="text-xl font-bold flex items-center"><Clock className="me-2" /> {t.history}</h3>
            <button onClick={onClear} className="text-sm text-red-500 hover:underline">{t.clearHistory}</button>
        </div>
        <div className="overflow-x-auto">
            <table className="w-full text-start text-sm text-gray-600">
                <thead><tr className="border-b bg-gray-50"><th className="p-3">{t.colTool}</th><th className="p-3">{t.colSource}</th><th className="p-3">{t.colResult}</th><th className="p-3">{t.colDate}</th><th className="p-3"></th></tr></thead>
                <tbody>
                    {history.map(h => (
                        <tr key={h.id} className="border-b hover:bg-gray-50">
                            <td className="p-3 font-semibold text-black">{h.tool}</td>
                            <td className="p-3 truncate max-w-[200px]">{h.source}</td>
                            <td className="p-3 truncate max-w-[200px]">{h.result}</td>
                            <td className="p-3">{formatHistoryDate(h)}</td>
                            <td className="p-3 text-end">
                                <a href={downloadUrl(h.result, getHistoryDownloadName(h.source, h.result))} download className="text-blue-600 hover:underline font-bold">{t.download}</a>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    </div>
  );
}
