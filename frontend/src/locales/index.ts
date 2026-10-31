import en from './en';
import type { Messages } from './en';

export type { Messages };
export { en };

export type TextDir = 'ltr' | 'rtl';

// Реестр языков интерфейса. EN, UK, RU идут первыми, остальные —
// по алфавиту самоназвания (порядок корневой сортировки Unicode,
// Intl.Collator('en'); scripts/check-locales.mjs проверяет его).
// htmlLang уходит в <html lang>, в toLocaleString() и в :lang() в CSS.
export const LANGUAGES = [
  { code: 'en', nativeName: 'English', dir: 'ltr', htmlLang: 'en' },
  { code: 'uk', nativeName: 'Українська', dir: 'ltr', htmlLang: 'uk' },
  { code: 'ru', nativeName: 'Русский', dir: 'ltr', htmlLang: 'ru' },
  { code: 'af', nativeName: 'Afrikaans', dir: 'ltr', htmlLang: 'af' },
  { code: 'az', nativeName: 'Azərbaycanca', dir: 'ltr', htmlLang: 'az-Latn' },
  { code: 'id', nativeName: 'Bahasa Indonesia', dir: 'ltr', htmlLang: 'id' },
  { code: 'ca', nativeName: 'Català', dir: 'ltr', htmlLang: 'ca' },
  { code: 'cs', nativeName: 'Čeština', dir: 'ltr', htmlLang: 'cs' },
  { code: 'da', nativeName: 'Dansk', dir: 'ltr', htmlLang: 'da' },
  { code: 'de', nativeName: 'Deutsch', dir: 'ltr', htmlLang: 'de' },
  { code: 'et', nativeName: 'Eesti', dir: 'ltr', htmlLang: 'et' },
  { code: 'es', nativeName: 'Español', dir: 'ltr', htmlLang: 'es' },
  { code: 'es-419', nativeName: 'Español (Latinoamérica)', dir: 'ltr', htmlLang: 'es-419' },
  { code: 'eu', nativeName: 'Euskara', dir: 'ltr', htmlLang: 'eu' },
  { code: 'fil', nativeName: 'Filipino', dir: 'ltr', htmlLang: 'fil' },
  { code: 'fr', nativeName: 'Français', dir: 'ltr', htmlLang: 'fr' },
  { code: 'ga', nativeName: 'Gaeilge', dir: 'ltr', htmlLang: 'ga' },
  { code: 'gl', nativeName: 'Galego', dir: 'ltr', htmlLang: 'gl' },
  { code: 'ha', nativeName: 'Hausa', dir: 'ltr', htmlLang: 'ha' },
  { code: 'hr', nativeName: 'Hrvatski', dir: 'ltr', htmlLang: 'hr' },
  { code: 'is', nativeName: 'Íslenska', dir: 'ltr', htmlLang: 'is' },
  { code: 'it', nativeName: 'Italiano', dir: 'ltr', htmlLang: 'it' },
  { code: 'sw', nativeName: 'Kiswahili', dir: 'ltr', htmlLang: 'sw' },
  { code: 'ltg', nativeName: 'Latgalīšu', dir: 'ltr', htmlLang: 'ltg' },
  { code: 'la', nativeName: 'Latina', dir: 'ltr', htmlLang: 'la' },
  { code: 'lv', nativeName: 'Latviešu', dir: 'ltr', htmlLang: 'lv' },
  { code: 'lb', nativeName: 'Lëtzebuergesch', dir: 'ltr', htmlLang: 'lb' },
  { code: 'lt', nativeName: 'Lietuvių', dir: 'ltr', htmlLang: 'lt' },
  { code: 'hu', nativeName: 'Magyar', dir: 'ltr', htmlLang: 'hu' },
  { code: 'mt', nativeName: 'Malti', dir: 'ltr', htmlLang: 'mt' },
  { code: 'nl', nativeName: 'Nederlands', dir: 'ltr', htmlLang: 'nl' },
  { code: 'nb', nativeName: 'Norsk bokmål', dir: 'ltr', htmlLang: 'nb' },
  { code: 'uz', nativeName: 'Oʻzbekcha', dir: 'ltr', htmlLang: 'uz-Latn' },
  { code: 'pl', nativeName: 'Polski', dir: 'ltr', htmlLang: 'pl' },
  { code: 'pt', nativeName: 'Português', dir: 'ltr', htmlLang: 'pt-BR' },
  { code: 'ro', nativeName: 'Română', dir: 'ltr', htmlLang: 'ro' },
  { code: 'sq', nativeName: 'Shqip', dir: 'ltr', htmlLang: 'sq' },
  { code: 'sk', nativeName: 'Slovenčina', dir: 'ltr', htmlLang: 'sk' },
  { code: 'sl', nativeName: 'Slovenščina', dir: 'ltr', htmlLang: 'sl' },
  { code: 'fi', nativeName: 'Suomi', dir: 'ltr', htmlLang: 'fi' },
  { code: 'sv', nativeName: 'Svenska', dir: 'ltr', htmlLang: 'sv' },
  { code: 'vi', nativeName: 'Tiếng Việt', dir: 'ltr', htmlLang: 'vi' },
  { code: 'tr', nativeName: 'Türkçe', dir: 'ltr', htmlLang: 'tr' },
  { code: 'yo', nativeName: 'Yorùbá', dir: 'ltr', htmlLang: 'yo' },
  { code: 'el', nativeName: 'Ελληνικά', dir: 'ltr', htmlLang: 'el' },
  { code: 'ba', nativeName: 'Башҡортса', dir: 'ltr', htmlLang: 'ba' },
  { code: 'be', nativeName: 'Беларуская', dir: 'ltr', htmlLang: 'be' },
  { code: 'bg', nativeName: 'Български', dir: 'ltr', htmlLang: 'bg' },
  { code: 'ky', nativeName: 'Кыргызча', dir: 'ltr', htmlLang: 'ky' },
  { code: 'kk', nativeName: 'Қазақша', dir: 'ltr', htmlLang: 'kk' },
  { code: 'mk', nativeName: 'Македонски', dir: 'ltr', htmlLang: 'mk' },
  { code: 'mn', nativeName: 'Монгол', dir: 'ltr', htmlLang: 'mn' },
  { code: 'ce', nativeName: 'Нохчийн', dir: 'ltr', htmlLang: 'ce' },
  { code: 'sr', nativeName: 'Српски', dir: 'ltr', htmlLang: 'sr-Cyrl' },
  { code: 'tg', nativeName: 'Тоҷикӣ', dir: 'ltr', htmlLang: 'tg' },
  { code: 'ka', nativeName: 'ქართული', dir: 'ltr', htmlLang: 'ka' },
  { code: 'hy', nativeName: 'Հայերեն', dir: 'ltr', htmlLang: 'hy' },
  { code: 'ur', nativeName: 'اردو', dir: 'rtl', htmlLang: 'ur' },
  { code: 'ar', nativeName: 'العربية', dir: 'rtl', htmlLang: 'ar' },
  { code: 'fa', nativeName: 'فارسی', dir: 'rtl', htmlLang: 'fa' },
  { code: 'am', nativeName: 'አማርኛ', dir: 'ltr', htmlLang: 'am' },
  { code: 'mr', nativeName: 'मराठी', dir: 'ltr', htmlLang: 'mr' },
  { code: 'hi', nativeName: 'हिन्दी', dir: 'ltr', htmlLang: 'hi' },
  { code: 'bn', nativeName: 'বাংলা', dir: 'ltr', htmlLang: 'bn' },
  { code: 'pa', nativeName: 'ਪੰਜਾਬੀ', dir: 'ltr', htmlLang: 'pa-Guru' },
  { code: 'ta', nativeName: 'தமிழ்', dir: 'ltr', htmlLang: 'ta' },
  { code: 'te', nativeName: 'తెలుగు', dir: 'ltr', htmlLang: 'te' },
  { code: 'th', nativeName: 'ไทย', dir: 'ltr', htmlLang: 'th' },
  { code: 'my', nativeName: 'မြန်မာ', dir: 'ltr', htmlLang: 'my' },
  { code: 'km', nativeName: 'ខ្មែរ', dir: 'ltr', htmlLang: 'km' },
  { code: 'ko', nativeName: '한국어', dir: 'ltr', htmlLang: 'ko' },
  { code: 'ja', nativeName: '日本語', dir: 'ltr', htmlLang: 'ja' },
  { code: 'zh-CN', nativeName: '简体中文', dir: 'ltr', htmlLang: 'zh-CN' },
  { code: 'zh-TW', nativeName: '繁體中文', dir: 'ltr', htmlLang: 'zh-TW' },
] as const satisfies readonly { code: string; nativeName: string; dir: TextDir; htmlLang: string }[];

export type LangCode = (typeof LANGUAGES)[number]['code'];
export type LanguageInfo = (typeof LANGUAGES)[number];

export const DEFAULT_LANG: LangCode = 'en';
export const LANG_STORAGE_KEY = 'docLang';

export const isLangCode = (value: string): value is LangCode =>
  LANGUAGES.some((l) => l.code === value);

export const getLanguage = (code: LangCode): LanguageInfo =>
  LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];

// Сохраненный язык; неизвестный код или недоступный localStorage — английский
export const readSavedLang = (): LangCode => {
  try {
    const saved = localStorage.getItem(LANG_STORAGE_KEY);
    if (saved && isLangCode(saved)) return saved;
  } catch {
    /* localStorage недоступен (приватный режим и т.п.) */
  }
  return DEFAULT_LANG;
};

export const saveLang = (code: LangCode) => {
  try {
    localStorage.setItem(LANG_STORAGE_KEY, code);
  } catch {
    /* не критично: язык просто не запомнится */
  }
};

// EN входит в основной бандл, остальные словари — отдельные чанки,
// которые подгружаются только при выборе языка. Record требует загрузчик
// для каждого кода из реестра: пропущенный язык — ошибка компиляции.
const loaders: Record<Exclude<LangCode, 'en'>, () => Promise<{ default: Messages }>> = {
  uk: () => import('./uk'),
  ru: () => import('./ru'),
  af: () => import('./af'),
  az: () => import('./az'),
  id: () => import('./id'),
  ca: () => import('./ca'),
  cs: () => import('./cs'),
  da: () => import('./da'),
  de: () => import('./de'),
  et: () => import('./et'),
  es: () => import('./es'),
  'es-419': () => import('./es-419'),
  eu: () => import('./eu'),
  fil: () => import('./fil'),
  fr: () => import('./fr'),
  ga: () => import('./ga'),
  gl: () => import('./gl'),
  ha: () => import('./ha'),
  hr: () => import('./hr'),
  is: () => import('./is'),
  it: () => import('./it'),
  sw: () => import('./sw'),
  ltg: () => import('./ltg'),
  la: () => import('./la'),
  lv: () => import('./lv'),
  lb: () => import('./lb'),
  lt: () => import('./lt'),
  hu: () => import('./hu'),
  mt: () => import('./mt'),
  nl: () => import('./nl'),
  nb: () => import('./nb'),
  uz: () => import('./uz'),
  pl: () => import('./pl'),
  pt: () => import('./pt'),
  ro: () => import('./ro'),
  sq: () => import('./sq'),
  sk: () => import('./sk'),
  sl: () => import('./sl'),
  fi: () => import('./fi'),
  sv: () => import('./sv'),
  vi: () => import('./vi'),
  tr: () => import('./tr'),
  yo: () => import('./yo'),
  el: () => import('./el'),
  ba: () => import('./ba'),
  be: () => import('./be'),
  bg: () => import('./bg'),
  ky: () => import('./ky'),
  kk: () => import('./kk'),
  mk: () => import('./mk'),
  mn: () => import('./mn'),
  ce: () => import('./ce'),
  sr: () => import('./sr'),
  tg: () => import('./tg'),
  ka: () => import('./ka'),
  hy: () => import('./hy'),
  ur: () => import('./ur'),
  ar: () => import('./ar'),
  fa: () => import('./fa'),
  am: () => import('./am'),
  mr: () => import('./mr'),
  hi: () => import('./hi'),
  bn: () => import('./bn'),
  pa: () => import('./pa'),
  ta: () => import('./ta'),
  te: () => import('./te'),
  th: () => import('./th'),
  my: () => import('./my'),
  km: () => import('./km'),
  ko: () => import('./ko'),
  ja: () => import('./ja'),
  'zh-CN': () => import('./zh-CN'),
  'zh-TW': () => import('./zh-TW'),
};

export const loadMessages = async (code: LangCode): Promise<Messages> => {
  if (code === 'en') return en;
  return (await loaders[code]()).default;
};
