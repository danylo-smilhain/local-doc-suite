import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { FileText, Trash2 } from 'lucide-react';
import type { UploadedFile } from '../api';

export const SortableItem = ({ id, file, onRemove }: { id: string; file: UploadedFile; onRemove: (id: string) => void }) => {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  const style = { transform: CSS.Transform.toString(transform), transition };
  return (
    <div ref={setNodeRef} style={style} className="p-4 bg-gray-50 border rounded-lg flex items-center justify-between mb-2 shadow-sm cursor-grab active:cursor-grabbing">
      <div className="flex items-center space-x-4 overflow-hidden" {...attributes} {...listeners}>
        <FileText size={24} className="text-gray-400 shrink-0" />
        <div className="truncate">
          <p className="font-semibold text-sm truncate">{file.name}</p>
          <p className="text-xs text-gray-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
        </div>
      </div>
      <button onClick={(e) => { e.stopPropagation(); onRemove(id); }} className="text-red-500 hover:text-red-700 shrink-0 px-2 bg-white rounded shadow-sm border p-1"><Trash2 size={16}/></button>
    </div>
  );
};
