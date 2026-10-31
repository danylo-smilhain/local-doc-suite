// Шапка: фильтры, меню «All tools», выбор языка.
import { useCallback, useRef, useState, type ReactNode } from 'react';
import { ChevronDown, Globe } from 'lucide-react';
import { LANGUAGES, type LangCode, type Messages } from '../locales';
import type { Tool, ToolCategory } from '../tools';
import { AllToolsMenu } from './AllToolsMenu';
import { useDismiss } from '../hooks/useDismiss';

type Props = {
  t: Messages;
  lang: LangCode;
  filter: 'all' | ToolCategory;
  toolTitle: (id: string) => string;
  onFilter: (f: ToolCategory) => void;
  onLang: (code: LangCode) => void;
  onPickTool: (tool: Tool) => void;
};

const FilterButton = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) => (
  <button onClick={onClick} className={`hover:text-[#e5322d] transition ${active ? 'text-[#e5322d]' : ''}`}>{children}</button>
);

export function Header({ t, lang, filter, toolTitle, onFilter, onLang, onPickTool }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLElement>(null);
  const menuBtnRef = useRef<HTMLButtonElement>(null);

  const closeMenu = useCallback(() => setMenuOpen(false), []);
  useDismiss(menuOpen, closeMenu, menuRef, menuBtnRef);

  return (
    <header className="bg-white shadow-sm flex flex-wrap items-center justify-end gap-y-3 px-6 py-4 relative z-20">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm font-semibold">
        <FilterButton active={filter === 'merge'} onClick={() => onFilter('merge')}>{t.navMerge}</FilterButton>
        <FilterButton active={filter === 'convert'} onClick={() => onFilter('convert')}>{t.navConvert}</FilterButton>
        <FilterButton active={filter === 'ocr'} onClick={() => onFilter('ocr')}>{t.navOcr}</FilterButton>
        <button ref={menuBtnRef} type="button" aria-expanded={menuOpen} aria-controls="all-tools-menu"
                onClick={() => setMenuOpen(open => !open)}
                className={`flex items-center gap-1 hover:text-[#e5322d] transition ${menuOpen ? 'text-[#e5322d]' : ''}`}>
          {t.navAllTools}
          <ChevronDown size={16} aria-hidden="true" className={`transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
        </button>
        <div className="flex items-center gap-2 border-s ps-6">
           <Globe size={18}/>
           <select value={lang} onChange={(e) => onLang(e.target.value as LangCode)} className="bg-transparent outline-none cursor-pointer font-bold">
              {LANGUAGES.map((l) => <option key={l.code} value={l.code} lang={l.htmlLang} dir={l.dir}>{l.nativeName}</option>)}
           </select>
        </div>
      </div>

      {menuOpen && (
        <AllToolsMenu ref={menuRef} label={t.navAllTools} categories={t.menuCategories} toolTitle={toolTitle}
                      onPick={(tool) => { onPickTool(tool); setMenuOpen(false); }} />
      )}
    </header>
  );
}
