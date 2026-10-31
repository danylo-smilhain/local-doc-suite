// Пустая панель инструмента: зона выбора/перетаскивания и причина отказа сервера.
import type { Messages } from '../locales';

export function DropArea({ t, isDragActive, alert, onOpen }: { t: Messages; isDragActive: boolean; alert: string; onOpen: () => void }) {
  return (
    <>
      {alert && (
        <p role="alert" className="text-red-600 font-semibold mb-4">{alert}</p>
      )}
      <div onClick={onOpen} className={`border-4 border-dashed rounded-xl p-16 cursor-pointer transition ${isDragActive ? 'border-[#e5322d] bg-white' : 'border-gray-200 bg-gray-50 hover:bg-gray-100'}`}>
        <button className="bg-[#e5322d] hover:bg-red-700 text-white font-bold py-4 px-8 rounded-lg text-xl shadow-lg transition pointer-events-none">{t.selectBtn}</button>
        <p className="mt-4 text-gray-500">{t.dropText}</p>
      </div>
    </>
  );
}
