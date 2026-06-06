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
  if (await enterButton.isVisible({ timeout: 3000 }).catch(() => false)) {
    await enterButton.click();
    // Wait for main console to render
    await page.waitForTimeout(2000);
  }

  // Wait for the app to fully settle
  await page.waitForLoadState('networkidle').catch(() => {});
}
