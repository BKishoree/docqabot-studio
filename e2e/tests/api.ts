import { APIRequestContext, expect, Page } from '@playwright/test';

/** Public API helpers used to set up and clean state between e2e tests. */
export async function resetWorkspace(request: APIRequestContext): Promise<void> {
  const convs = await (await request.get('/api/v1/conversations?limit=200')).json();
  for (const c of convs.items) await request.delete(`/api/v1/conversations/${c.id}`);
  const docs = await (await request.get('/api/v1/documents')).json();
  for (const d of docs.items) await request.delete(`/api/v1/documents/${d.id}`);
}

export async function uploadViaApi(request: APIRequestContext, name: string, text: string): Promise<number> {
  const r = await request.post('/api/v1/documents', {
    multipart: { file: { name, mimeType: 'text/plain', buffer: Buffer.from(text, 'utf-8') } },
  });
  expect(r.status()).toBe(202);
  const id = (await r.json()).id as number;
  await expect
    .poll(async () => (await (await request.get(`/api/v1/documents/${id}`)).json()).status, { timeout: 30_000 })
    .toBe('ready');
  return id;
}

/** True when the page scrolls horizontally (layout wider than the viewport). */
export async function hasHorizontalScroll(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

export const HANDBOOK = [
  'Vacation policy',
  'Full-time employees accrue twenty days of paid vacation per calendar year. Unused vacation days carry over until the end of March.',
  'Remote work',
  'Staff may work remotely on Tuesdays and Thursdays after approval by their manager.',
].join('\n\n');

export const VACATION_Q = 'How many paid vacation days do full-time employees accrue per calendar year?';
export const UNRELATED_Q = 'zebra quantum saxophone';
