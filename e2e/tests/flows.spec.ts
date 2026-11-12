import { expect, Page, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { HANDBOOK, resetWorkspace, UNRELATED_Q, uploadViaApi, VACATION_Q } from './api';

// E2E-1..6, E2E-9 on the demo stack (S1-S4, S6, S7, S12, S13). Answers come from the stub.
const FIXTURES = path.join(__dirname, '..', 'fixtures');

test.beforeEach(async ({ request }) => {
  await resetWorkspace(request);
});

function file(name: string, text: string) {
  return { name, mimeType: 'text/plain', buffer: Buffer.from(text, 'utf-8') };
}

async function ask(page: Page, question: string) {
  const box = page.getByRole('textbox', { name: 'Your question' });
  await expect(box).toBeEnabled();
  await box.fill(question);
  await box.press('Enter');
}

function docRow(page: Page, name: string) {
  return page.getByRole('row').filter({ hasText: name });
}

test('E2E-1 upload TXT, MD and PDF; each turns Ready without reload, with size and passages (S1, AC4)', async ({ page }) => {
  await page.goto('/library');
  await page.locator('#file-input').setInputFiles([
    file('handbook.txt', HANDBOOK),
    { name: 'garden.md', mimeType: 'text/markdown', buffer: Buffer.from('# Tomatoes\n\nTomatoes need full sun.') },
    { name: 'invoices.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(path.join(FIXTURES, 'invoices.pdf')) },
  ]);
  for (const name of ['handbook.txt', 'garden.md', 'invoices.pdf']) {
    const row = docRow(page, name);
    await expect(row).toContainText('Ready', { timeout: 30_000 });
    await expect(row).toContainText(/\d+(\.\d)? (B|KB)/);
    await expect(row.getByRole('cell').nth(3)).toHaveText(/^\d+$/);
  }
});

test('E2E-1b rejected upload shows its specific message and stores nothing (S10)', async ({ page, request }) => {
  await page.goto('/library');
  await page.locator('#file-input').setInputFiles([
    { name: 'report.docx', mimeType: 'application/octet-stream', buffer: Buffer.from('PK') },
    { name: 'empty.txt', mimeType: 'text/plain', buffer: Buffer.alloc(0) },
  ]);
  const uploads = page.getByRole('list', { name: 'Uploads' });
  await expect(uploads).toContainText(/report\.docx[\s\S]*Not uploaded/);
  await expect(uploads).toContainText(/empty\.txt[\s\S]*Not uploaded/);
  expect((await (await request.get('/api/v1/documents')).json()).total).toBe(0);
});

test('E2E-2/3/4 cited answer, follow-up with history, not-grounded answer (S2, S3, S4)', async ({ page, request }) => {
  await uploadViaApi(request, 'handbook.txt', HANDBOOK);
  await page.goto('/');
  await ask(page, VACATION_Q);
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);

  const thread = page.getByRole('region', { name: 'Questions and answers' }).or(page.getByLabel('Questions and answers'));
  await expect(thread.getByText(/\[Simulated answer\] Based on handbook\.txt/)).toBeVisible({ timeout: 30_000 });
  await expect(thread.getByRole('heading', { name: /Sources \(\d\)/ })).toBeVisible();
  const firstCite = thread.getByRole('button', { name: /Source 1: handbook\.txt/ });
  await expect(firstCite).toHaveAttribute('aria-expanded', 'true');
  await expect(thread.getByText(/twenty days of paid vacation/).first()).toBeVisible();
  await expect(firstCite).toContainText(/\d+% match/);

  await ask(page, 'Do unused vacation days carry over?');
  await expect(thread.getByText(/\(follow-up, 2 earlier messages\)/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('textbox', { name: 'Your question' })).toBeFocused();

  await ask(page, UNRELATED_Q);
  await expect(thread.getByText('Not found in your documents')).toBeVisible({ timeout: 30_000 });
  await expect(thread.getByRole('heading', { name: /Sources/ })).toHaveCount(2);
});

test('E2E-5 delete a document: confirmation, gone, old citation kept and marked removed (S6, AC9)', async ({ page, request }) => {
  await uploadViaApi(request, 'handbook.txt', HANDBOOK);
  await page.goto('/');
  await ask(page, VACATION_Q);
  await expect(page).toHaveURL(/\/c\//);
  const convUrl = page.url();
  await expect(page.getByText(/Sources \(\d\)/)).toBeVisible({ timeout: 30_000 });

  await page.goto('/library');
  await page.getByRole('button', { name: 'Delete handbook.txt' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('handbook.txt');
  await expect(dialog).toContainText(/passage|quote/i); // says old answers keep their quotes
  await dialog.getByRole('button', { name: 'Delete document' }).click();
  await expect(docRow(page, 'handbook.txt')).toHaveCount(0);
  await expect(page.getByText('No documents yet')).toBeVisible();

  await page.goto(convUrl);
  await expect(page.getByText('Removed from library').first()).toBeVisible();
  await expect(page.getByText(/twenty days of paid vacation/).first()).toBeVisible();
});

test('E2E-6 reopen after reload, rename and delete a conversation (S7, S12)', async ({ page, request }) => {
  await uploadViaApi(request, 'handbook.txt', HANDBOOK);
  await page.goto('/');
  await ask(page, VACATION_Q);
  await expect(page.getByText(/Sources \(\d\)/)).toBeVisible({ timeout: 30_000 });
  await page.reload();
  await expect(page.getByText(VACATION_Q).first()).toBeVisible();
  await expect(page.getByText(/Sources \(\d\)/)).toBeVisible();

  await page.getByRole('button', { name: 'Rename conversation' }).click();
  const title = page.getByRole('textbox').filter({ hasNot: page.locator('#question') }).first();
  await title.fill('Vacation questions');
  await title.press('Enter');
  await expect(page.getByRole('heading', { name: 'Vacation questions' })).toBeVisible();
  await expect
    .poll(async () => (await (await request.get('/api/v1/conversations')).json()).items[0].title)
    .toBe('Vacation questions');

  await page.getByRole('button', { name: 'Delete conversation' }).first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Vacation questions');
  await page.keyboard.press('Escape'); // Escape cancels
  await expect(dialog).toBeHidden();
  await page.getByRole('button', { name: 'Delete conversation' }).first().click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete conversation' }).click();
  await expect
    .poll(async () => (await (await request.get('/api/v1/conversations')).json()).total)
    .toBe(0);
});

test('E2E-9 keyboard only: upload -> ask -> open citation -> delete (AC20)', async ({ page }) => {
  test.skip(test.info().project.name !== 'desktop', 'keyboard run once, on desktop');
  await page.goto('/library');

  // Upload: Tab to "Choose files", press Enter, answer the native file chooser.
  const chooseFiles = page.getByRole('button', { name: 'Choose files' });
  await tabUntilFocused(page, chooseFiles);
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.keyboard.press('Enter')]);
  await chooser.setFiles([file('handbook.txt', HANDBOOK)]);
  await expect(docRow(page, 'handbook.txt')).toContainText('Ready', { timeout: 30_000 });

  // Ask: move to the workspace by keyboard through the navigation link.
  const workspaceLink = page.getByRole('link', { name: /ask|workspace|new conversation/i }).first();
  await tabUntilFocused(page, workspaceLink);
  await page.keyboard.press('Enter');
  const box = page.getByRole('textbox', { name: 'Your question' });
  await tabUntilFocused(page, box);
  await page.keyboard.type(VACATION_Q);
  await page.keyboard.press('Enter');
  await expect(page.getByText(/Sources \(\d\)/)).toBeVisible({ timeout: 30_000 });

  // Open citation: first one is open, collapse and reopen it with the keyboard.
  const cite = page.getByRole('button', { name: /Source 1: handbook\.txt/ });
  await tabUntilFocused(page, cite);
  await page.keyboard.press('Enter');
  await expect(cite).toHaveAttribute('aria-expanded', 'false');
  await page.keyboard.press('Space');
  await expect(cite).toHaveAttribute('aria-expanded', 'true');

  // Delete the conversation with the keyboard; the dialog traps focus and Enter confirms.
  const del = page.getByRole('button', { name: 'Delete conversation' }).first();
  await tabUntilFocused(page, del);
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const confirm = dialog.getByRole('button', { name: 'Delete conversation' });
  await tabUntilFocused(page, confirm, 4);
  await page.keyboard.press('Enter');
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/$/);
});

async function tabUntilFocused(page: Page, target: ReturnType<Page['getByRole']>, max = 60) {
  for (let i = 0; i < max; i++) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) {
      // Visible focus indicator (AC20): the element or a close ancestor (focus-within) looks different
      // focused vs not focused (outline, box-shadow, border or background).
      const snap = (el: Element) => {
        const chain: Element[] = [];
        for (let e: Element | null = el; e && chain.length < 4; e = e.parentElement) chain.push(e);
        return chain.map((e) => {
          const s = getComputedStyle(e);
          return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderColor, s.backgroundColor].join('|');
        });
      };
      await page.waitForTimeout(400); // let focus transitions finish
      const focused = await target.evaluate(snap);
      const own = await target.evaluate((el) => {
        const s = getComputedStyle(el);
        return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none';
      });
      await target.evaluate((el) => (el as HTMLElement).blur());
      await page.waitForTimeout(400);
      const blurred = await target.evaluate(snap);
      await target.focus(); // back where the keyboard user was
      const visible = own || focused.some((v, i) => v !== blurred[i]);
      expect(visible, 'focused element has a visible focus style').toBe(true);
      return;
    }
    await page.keyboard.press('Tab');
  }
  throw new Error(`could not reach ${target} with Tab in ${max} presses`);
}
