// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { en } from '../locales';
import { ResultPanel } from './ResultPanel';

afterEach(cleanup);

describe('ResultPanel', () => {
  it('shows the server warnings next to the download', () => {
    render(<ResultPanel t={en} outMeta={null} href="#" onAgain={() => {}}
                        warnings={['Use PDF to PPTX (with OCR) to make their text editable.']} />);
    expect(screen.getByRole('note').textContent).toContain('Use PDF to PPTX (with OCR)');
  });

  it('shows no warning box when there is nothing to say', () => {
    render(<ResultPanel t={en} outMeta={null} href="#" onAgain={() => {}} warnings={[]} />);
    expect(screen.queryByRole('note')).toBeNull();
  });
});
