// Панель «All tools»: инструменты по колонкам категорий (TOOL_MENU).
import React, { forwardRef } from 'react';
import { TOOL_MENU, toolsConfig, type Tool } from '../tools';
import type { Messages } from '../locales';

type Props = {
  label: string;
  categories: Messages['menuCategories'];
  toolTitle: (id: string) => string;
  onPick: (tool: Tool) => void;
};

export const AllToolsMenu = forwardRef<HTMLElement, Props>(({ label, categories, toolTitle, onPick }, menuRef) => (
  <nav ref={menuRef} id="all-tools-menu" aria-label={label}
       className="absolute inset-x-2 sm:inset-x-4 top-full mt-2 max-h-[80vh] overflow-y-auto bg-white rounded-2xl shadow-[0_8px_30px_rgba(34,34,51,0.12)] p-6 sm:p-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 gap-x-6 gap-y-8 text-start">
    {(Object.entries(TOOL_MENU) as [keyof typeof TOOL_MENU, readonly string[]][]).map(([category, ids]) => (
      <div key={category}>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">{categories[category]}</h2>
        <ul className="space-y-1">
          {ids.map(id => {
            const tool = toolsConfig.find(item => item.id === id)!;
            return (
              <li key={id}>
                <button type="button" onClick={() => onPick(tool)}
                        className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-start text-sm font-medium text-[#33333b] hover:bg-gray-50 hover:text-[#e5322d] transition">
                  <span className="shrink-0">{React.cloneElement(tool.icon, { size: 28 })}</span>
                  <span>{toolTitle(id)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    ))}
  </nav>
));
AllToolsMenu.displayName = 'AllToolsMenu';
