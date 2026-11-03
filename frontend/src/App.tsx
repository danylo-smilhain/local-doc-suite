import { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { errorMessage, type ApiErrorBody } from './errorMessage';
import { downloadUrl } from './api';
import { getDownloadName } from './names';
import { toolsConfig, type Tool, type ToolCategory } from './tools';
import { toolTextOf } from './toolText';
import { useUpload } from './hooks/useUpload';
import { useConversion } from './hooks/useConversion';
import type { Status } from './hooks/types';
import { Header } from './components/Header';
import { ToolGrid } from './components/ToolGrid';
import { HistoryTable } from './components/HistoryTable';
import { useLanguage } from './hooks/useLanguage';
import { formatHistoryDate, useHistory } from './hooks/useHistory';
import { ToolPanel } from './components/ToolPanel';
import { FilePanel } from './components/FilePanel';

// Каталог инструментов живет в tools.ts; реэкспорт — для тестов и внешнего кода
export { toolsConfig, TOOL_MENU } from './tools';

export default function App() {
  const { lang, setLang, t, langInfo } = useLanguage();
  const [filter, setFilter] = useState<'all' | ToolCategory>('all');
  const { history, add: addToHistory, clear: clearHistory } = useHistory();

  const [activeTool, setActiveTool] = useState<Tool | null>(null);
  const [status, setStatus] = useState<Status>('idle');
  // Ошибка от сервера ({ code, detail }); переводится при отрисовке
  const [errorInfo, setErrorInfo] = useState<ApiErrorBody | null>(null);

  const toolText = (id: string) => toolTextOf(t, id);
  const isRtl = langInfo.dir === 'rtl';

  const { files, setFiles, onDrop, removeFile, moveFile } = useUpload(activeTool, setStatus, setErrorInfo);
  const { resultId, outMeta, setOutMeta, warnings, process } = useConversion(setStatus, setErrorInfo, (data) => {
    addToHistory({
      id: Date.now(), tool: toolText(activeTool!.id).t,
      source: files.length > 1 ? `${files.length} files` : files[0].name,
      result: data.download_id, date: new Date().toLocaleString()
    });
  });

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
      onDrop,
      multiple: activeTool?.category === 'merge',
      noClick: true,
      noKeyboard: true
  });

  const reset = () => { setActiveTool(null); setFiles([]); setStatus('idle'); setFilter('all'); setOutMeta(null); setErrorInfo(null); };

  const filteredTools = toolsConfig.filter(tool => filter === 'all' || tool.category === filter);

  return (
    <div dir={langInfo.dir} className="min-h-screen bg-[#f4f4f4] font-sans text-[#222222] pb-20">
      <Header t={t} lang={lang} filter={filter} toolTitle={(id) => toolText(id).t}
              onFilter={(f) => { setActiveTool(null); setFilter(f); }}
              onLang={setLang}
              onPickTool={(tool) => { reset(); setActiveTool(tool); }} />

      <main className={`${activeTool ? 'max-w-6xl' : 'max-w-[1800px]'} mx-auto py-12 px-4 sm:px-6 relative z-10`}>
        {!activeTool ? (
          <>
            <div className="text-center mb-12">
              <h1 className="text-4xl font-bold mb-4">{t.mainTitle}</h1>
              <p className="text-gray-600 text-lg">{t.mainSub}</p>
            </div>
            <ToolGrid tools={filteredTools} toolText={toolText} onPick={setActiveTool} />

            {history.length > 0 && (
              <HistoryTable t={t} history={history} formatDate={(h) => formatHistoryDate(h, langInfo.htmlLang)} onClear={clearHistory} />
            )}
          </>
        ) : (
          <div {...getRootProps()} className={`bg-white rounded-xl shadow-sm p-12 text-center max-w-3xl mx-auto relative transition-colors ${isDragActive ? 'ring-4 ring-[#e5322d] bg-red-50' : 'ring-4 ring-transparent'}`}>
          <ToolPanel t={t} tool={activeTool} title={toolText(activeTool.id).t} isRtl={isRtl}
                     isDragActive={isDragActive} hasFiles={files.length > 0}
                     alert={status === 'error' ? errorMessage(t, errorInfo) : ''}
                     inputProps={getInputProps()}
                     onBack={reset} onOpen={open}
                     filePanel={
                       <FilePanel t={t} status={status} tool={activeTool} title={toolText(activeTool.id).t}
                                  files={files} outMeta={outMeta} warnings={warnings}
                                  resultHref={downloadUrl(resultId, getDownloadName(files, activeTool))}
                                  errorText={errorMessage(t, errorInfo)}
                                  onProcess={() => process(files, activeTool)} onReset={reset}
                                  onRemove={removeFile} onMove={moveFile} onAddMore={open} />
                     } />
          </div>
        )}
      </main>
    </div>
  );
}
