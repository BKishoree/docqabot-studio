import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { hasHorizontalScroll, resetWorkspace } from './api';

// E2E-7 (S11 first run), E2E-8 (S13 demo notice), axe per screen (AC20), viewports (AC20),
// no third-party requests (AC21). Selector-agnostic: these hold for any design.
const SCREENS = ['/', '/library', '/status', '/does-not-exist'];

test.beforeEach(async ({ request }) => {
  await resetWorkspace(request);
});

for (const path of SCREENS) {
  test(`screen ${path}: loads, demo notice, no serious axe violations, same-origin only`, async ({ page, baseURL }) => {
    const foreign: string[] = [];
    page.on('request', (req) => {
      const u = new URL(req.url());
      if (!['data:', 'blob:'].includes(u.protocol) && u.origin !== new URL(baseURL!).origin) foreign.push(req.url());
    });
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));

    const resp = await page.goto(path);
    expect(resp?.status()).toBe(200);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByText(/simulated/i).first()).toBeVisible(); // demo stack: notice on every screen

    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    const bad = axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(bad.map((v) => `${v.id}: ${v.nodes.length} node(s)`)).toEqual([]);

    expect(foreign).toEqual([]);
    expect(errors).toEqual([]);
  });
}

for (const width of [360, 390, 1920]) {
  test(`no horizontal scroll at ${width}px on every screen`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of SCREENS) {
      await page.goto(path);
      await expect(page.getByRole('main')).toBeVisible();
      expect(await hasHorizontalScroll(page), `${path} at ${width}px`).toBe(false);
    }
  });
}

test('first run: empty states and asking disabled until a document is ready (S11)', async ({ page }) => {
  await page.goto('/');
  const question = page.getByRole('textbox', { name: /question|ask/i });
  await expect(question.or(page.getByRole('button', { name: /send|ask/i })).first()).toBeVisible();
  const send = page.getByRole('button', { name: /send|ask/i });
  // Either the textbox or the send button is disabled, with a visible reason mentioning documents.
  const textboxDisabled = await question.isDisabled().catch(() => false);
  const sendDisabled = await send.first().isDisabled().catch(() => false);
  expect(textboxDisabled || sendDisabled).toBe(true);
  await expect(page.getByText(/upload|document/i).first()).toBeVisible();
  await page.goto('/library');
  await expect(page.getByText(/no documents|upload/i).first()).toBeVisible();
});
