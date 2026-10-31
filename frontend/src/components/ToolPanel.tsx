// Содержимое drop-зоны инструмента: «назад», иконка, название, файлы.
// Сама зона (<div {...getRootProps()}>) остается в App: React переиспользует
// на ее месте DOM-узел главной страницы, и разметка не меняется.
import React, { type InputHTMLAttributes, type ReactNode } from 'react';
import type { Messages } from '../locales';
import type { Tool } from '../tools';
import { DropArea } from './DropArea';

type Props = {
  t: Messages;
  tool: Tool;
  title: string;
  isRtl: boolean;
  isDragActive: boolean;
  hasFiles: boolean;
  alert: string;
  inputProps: InputHTMLAttributes<HTMLInputElement>;
  filePanel: ReactNode;
  onBack: () => void;
  onOpen: () => void;
};

export function ToolPanel({ t, tool, title, isRtl, isDragActive, hasFiles, alert, inputProps,
                            filePanel, onBack, onOpen }: Props) {
  return (
    <>

      <input {...inputProps} />

      <button onClick={(e) => { e.stopPropagation(); onBack(); }} className="absolute top-6 start-6 text-gray-400 hover:text-black z-20">{isRtl ? '→' : '←'} {t.back}</button>
      <div className="flex justify-center mb-3">{React.cloneElement(tool.icon, { size: 64 })}</div>
      <h2 className="text-3xl font-bold mb-8">{title}</h2>

      {!hasFiles ? (
        <DropArea t={t} isDragActive={isDragActive} alert={alert} onOpen={onOpen} />
      ) : (
        filePanel
      )}
    </>
  );
}
