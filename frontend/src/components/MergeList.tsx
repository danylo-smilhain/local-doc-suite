// Список файлов для слияния: порядок перетаскиванием, удаление, «добавить еще».
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable';
import type { UploadedFile } from '../api';
import type { Messages } from '../locales';
import { SortableItem } from './SortableItem';

type Props = {
  t: Messages;
  files: UploadedFile[];
  onRemove: (id: string) => void;
  onMove: (activeId: string, overId: string) => void;
  onAddMore: () => void;
};

export function MergeList({ t, files, onRemove, onMove, onAddMore }: Props) {
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  return (
    <div className="text-left mb-6 max-h-64 overflow-y-auto pr-2">
       <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={(e: DragEndEvent) => e.over && onMove(String(e.active.id), String(e.over.id))}>
         <SortableContext items={files.map(f => f.id)} strategy={verticalListSortingStrategy}>
           {files.map(f => <SortableItem key={f.id} id={f.id} file={f} onRemove={onRemove} />)}
         </SortableContext>
       </DndContext>

       <button onClick={onAddMore} type="button" className="mt-2 text-sm text-[#e5322d] font-bold border border-[#e5322d] bg-white px-4 py-2 rounded hover:bg-red-50 w-full transition">
          {t.addMore}
       </button>
    </div>
  );
}
