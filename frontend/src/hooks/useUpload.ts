// Files chosen for the active tool: upload on drop, remove, reorder (merge).
import { useCallback, useState } from 'react';
import { arrayMove } from '@dnd-kit/sortable';
import { uploadFile, type UploadedFile } from '../api';
import type { ApiErrorBody } from '../errorMessage';
import type { Tool } from '../tools';
import type { Status } from './types';

// Загружает файлы по одному. Отклоненные сервером в список не попадают
// (остается причина последнего отказа), сетевая ошибка пропускает файл.
export async function uploadAll(acceptedFiles: File[]) {
  const newFiles: UploadedFile[] = [];
  let rejected: ApiErrorBody | null = null;
  for (const f of acceptedFiles) {
    try {
      const reply = await uploadFile(f);
      if (!reply.ok) { rejected = reply.error; continue; }
      newFiles.push(reply.file);
    } catch (e) {
      console.error("Ошибка сети:", e);
    }
  }
  return { newFiles, rejected };
}

export function useUpload(activeTool: Tool | null, setStatus: (s: Status) => void,
                          setErrorInfo: (e: ApiErrorBody | null) => void) {
  const [files, setFiles] = useState<UploadedFile[]>([]);

  const onDrop = useCallback(async (acceptedFiles: File[], fileRejections: any[]) => {
    // 1. Отлавливаем отклоненные файлы и выводим причину в консоль
    if (fileRejections.length > 0) {
      console.error("Браузер забраковал файл:", fileRejections);
      setStatus('error');
      return;
    }

    if (acceptedFiles.length === 0) return;
    setStatus('uploading');
    setErrorInfo(null);

    const { newFiles, rejected } = await uploadAll(acceptedFiles);

    // 2. Защита от белого экрана, если сервер недоступен
    if (newFiles.length === 0) {
      setErrorInfo(rejected);
      setStatus('error');
      return;
    }

    if (activeTool?.category === 'merge') {
      setFiles(prev => [...prev, ...newFiles]);
    } else {
      setFiles([newFiles[0]]);
    }
    setStatus('idle');
  }, [activeTool, setStatus, setErrorInfo]);

  const removeFile = (id: string) => setFiles(prev => prev.filter(f => f.id !== id));

  const moveFile = (activeId: string, overId: string) => {
    if (activeId === overId) return;
    setFiles((items) => {
      const oldIndex = items.findIndex(i => i.id === activeId);
      const newIndex = items.findIndex(i => i.id === overId);
      return arrayMove(items, oldIndex, newIndex);
    });
  };

  return { files, setFiles, onDrop, removeFile, moveFile };
}
