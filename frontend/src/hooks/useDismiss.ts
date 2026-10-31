// Закрытие всплывающей панели по Esc (фокус возвращается на кнопку) и по
// клику вне панели; клик по самой кнопке открытия «вне» не считается.
import { useEffect, type RefObject } from 'react';

export function useDismiss(open: boolean, close: () => void,
                           panelRef: RefObject<HTMLElement>, triggerRef: RefObject<HTMLElement>) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      close();
      triggerRef.current?.focus();
    };
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!panelRef.current?.contains(target) && !triggerRef.current?.contains(target)) close();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open, close, panelRef, triggerRef]);
}
