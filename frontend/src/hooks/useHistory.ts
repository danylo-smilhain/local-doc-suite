// «Recent Conversions»: последние 10 результатов, хранятся в localStorage.
import { useEffect, useState } from 'react';

export type HistoryRecord = { id: number; tool: string; source: string; result: string; date: string };

const KEY = 'docHistory';
const LIMIT = 10;

export function useHistory() {
  const [history, setHistory] = useState<HistoryRecord[]>(() => JSON.parse(localStorage.getItem(KEY) || '[]'));
  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(history)); }, [history]);
  const add = (record: HistoryRecord) => setHistory(prev => [record, ...prev].slice(0, LIMIT));
  const clear = () => setHistory([]);
  return { history, add, clear };
}

// Дата в истории — из метки времени записи (id), в формате языка интерфейса
export const formatHistoryDate = (h: HistoryRecord, htmlLang: string) =>
  typeof h.id === 'number' ? new Date(h.id).toLocaleString(htmlLang) : h.date;
