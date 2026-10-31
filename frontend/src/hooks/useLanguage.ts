// Язык интерфейса: выбор, сохранение, ленивая загрузка словаря, <html lang/dir>.
import { useEffect, useState } from 'react';
import { en, getLanguage, loadMessages, readSavedLang, saveLang, type LangCode, type Messages } from '../locales';

export function useLanguage() {
  const [lang, setLang] = useState<LangCode>(readSavedLang);
  // Загруженные словари: EN есть сразу, остальные подгружаются при выборе языка
  const [loaded, setLoaded] = useState<Partial<Record<LangCode, Messages>>>({ en });

  // Пока словарь выбранного языка грузится, интерфейс остается на английском
  const t: Messages = loaded[lang] ?? en;
  const langInfo = getLanguage(loaded[lang] ? lang : 'en');

  useEffect(() => { saveLang(lang); }, [lang]);
  useEffect(() => {
    if (loaded[lang]) return;
    loadMessages(lang)
      .then((messages) => setLoaded((prev) => ({ ...prev, [lang]: messages })))
      .catch((err) => console.error('Не удалось загрузить язык', lang, err));
  }, [lang, loaded]);
  useEffect(() => {
    document.documentElement.lang = langInfo.htmlLang;
    document.documentElement.dir = langInfo.dir;
  }, [langInfo]);

  return { lang, setLang, t, langInfo };
}
