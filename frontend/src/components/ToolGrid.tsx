// Карточки инструментов на главной странице.
import type { Tool } from '../tools';
import type { ToolText } from '../toolText';

type Props = { tools: Tool[]; toolText: (id: string) => ToolText; onPick: (tool: Tool) => void };

export function ToolGrid({ tools: filteredTools, toolText, onPick }: Props) {
  return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6 gap-4 mb-16">
        {filteredTools.map(tool => (
          <div key={tool.id} onClick={() => onPick(tool)}
               className="group bg-white px-6 pt-6 pb-7 rounded-2xl border border-[#e6e6ef] cursor-pointer transition flex flex-col items-start text-start min-h-[230px] hover:shadow-[0_8px_24px_rgba(34,34,51,0.08)] hover:border-[#d6d6e2]">
            <div className="mb-4 shrink-0">{tool.icon}</div>
            <h3 className="font-semibold text-xl text-[#33333b] mb-3 leading-snug group-hover:text-[#e5322d] transition-colors">{toolText(tool.id).t}</h3>
            <p className="text-[#707078] text-sm leading-relaxed tracking-[0.01em]">{toolText(tool.id).d}</p>
          </div>
        ))}
      </div>
  );
}
