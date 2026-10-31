// Sends the chosen files to /convert and keeps the result.
import { useState } from 'react';
import { convertFiles, type ConvertSuccess, type FileMeta, type UploadedFile } from '../api';
import type { ApiErrorBody } from '../errorMessage';
import type { Tool } from '../tools';
import type { Status } from './types';

export function useConversion(setStatus: (s: Status) => void, setErrorInfo: (e: ApiErrorBody | null) => void,
                              onSuccess: (data: ConvertSuccess) => void) {
  const [resultId, setResultId] = useState<string>('');
  const [outMeta, setOutMeta] = useState<FileMeta | null>(null);

  const process = async (files: UploadedFile[], tool: Tool) => {
    setStatus('converting');
    setErrorInfo(null);
    try {
      const data = await convertFiles(files, tool.out);
      if (data.status === 'success') {
        setResultId(data.download_id);
        setOutMeta(data.meta);
        setStatus('success');
        onSuccess(data);
      } else {
        setErrorInfo(data);
        setStatus('error');
      }
    } catch (err) { setStatus('error'); }
  };

  return { resultId, outMeta, setOutMeta, process };
}
