import { en, type Messages } from './locales';

export type ToolText = { t: string; d: string };

// Подписи инструментов, которых еще нет в словарях src/locales. Без этого
// перевод нового инструмента был бы undefined, и страница падала бы целиком.
// Когда ключи появятся в словарях, они автоматически перекроют эти строки.
const TOOL_TEXT_FALLBACK: Record<string, ToolText> = {};

// Название и описание инструмента: словарь языка -> английский -> запасной текст
export const toolTextOf = (t: Messages, id: string): ToolText =>
  (t.tools as Record<string, ToolText>)[id]
  ?? (en.tools as Record<string, ToolText>)[id]
  ?? TOOL_TEXT_FALLBACK[id]
  ?? { t: id, d: '' };
