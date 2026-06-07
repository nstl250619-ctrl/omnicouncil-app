import { Page } from '@playwright/test';

/**
 * Navigate to the app and bypass the AI Platform Manager setup screen
 * to reach the main console where query input and tabs are available.
 */
export async function navigateToConsole(page: Page): Promise<void> {
  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);

  // Check if we're on the AI Platform Manager (setup mode)
  const enterButton = page.locator('button:has-text("进入控制台")');
  const isOnSetup = await enterButton.isVisible({ timeout: 3000 }).catch(() => false);

  if (isOnSetup) {
    // Try clicking — button may be disabled if no platforms connected
    const isDisabled = await enterButton.isDisabled().catch(() => false);
    if (isDisabled) {
      // Bypass setup via exposed Zustand store (DEV mode only)
      await page.evaluate(() => {
        const store = (window as unknown as Record<string, unknown>).__configStore;
        if (store && typeof store === 'object' && 'getState' in store) {
          (store as { getState: () => { completeSetup: (mode: string) => void } }).getState().completeSetup('embedded');
        }
      });
    } else {
      await enterButton.click();
    }
    // Wait for console to render after setup bypass
    await page.waitForTimeout(2000);
  }

  // Wait for the console page to be ready (look for console-specific elements)
  await page.locator('button, [class*="tab"], [class*="query"], input, textarea').first()
    .waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});

  // Wait for the app to fully settle
  await page.waitForLoadState('networkidle').catch(() => {});
}
