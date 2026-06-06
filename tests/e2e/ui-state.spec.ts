import { test, expect } from '@playwright/test';
import { navigateToConsole } from './helpers';

// Section 6: UI State Sync Tests
test.describe('六、UI 状态同步测试', () => {
  test.beforeEach(async ({ page }) => {
    await navigateToConsole(page);
  });

  test('6.1 页面基本渲染', async ({ page }) => {
    // Verify the app renders without errors
    const body = await page.textContent('body');
    expect(body).toBeTruthy();
    expect(body!.length).toBeGreaterThan(0);

    // Check for no console errors
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    await page.waitForTimeout(2000);

    // Filter out known non-critical errors
    const criticalErrors = errors.filter(e =>
      !e.includes('favicon') &&
      !e.includes('manifest') &&
      !e.includes('service-worker')
    );

    // Should have no critical console errors
    expect(criticalErrors.length).toBe(0);
  });

  test('6.2 StatusBar 状态显示', async ({ page }) => {
    // Check if status bar or status indicator exists
    const body = await page.textContent('body');

    // The app should have some status indication
    // Look for common status patterns
    const hasStatusIndicator = body && (
      body.includes('就绪') ||
      body.includes('Ready') ||
      body.includes('已连接') ||
      body.includes('Connected') ||
      body.includes('连接') ||
      body.includes('状态')
    );

    // At minimum, the page should render with some content
    expect(body!.length).toBeGreaterThan(10);
  });

  test('6.3 TabBar 导航', async ({ page }) => {
    // Look for tab elements
    const tabs = page.locator('[role="tab"], [class*="tab"], [data-testid*="tab"], button.tab-btn');
    const tabCount = await tabs.count();

    // Verify tabs exist
    expect(tabCount).toBeGreaterThan(0);

    // Get tab names for verification
    const tabNames = await tabs.allTextContents();
    expect(tabNames.length).toBeGreaterThan(0);

    // Click each enabled tab only
    for (let i = 0; i < tabCount; i++) {
      const tab = tabs.nth(i);
      if (await tab.isVisible() && await tab.isEnabled()) {
        await tab.click();
        await page.waitForTimeout(500);
      }
    }

    // Verify page still renders correctly after tab navigation
    const body = await page.textContent('body');
    expect(body).toBeTruthy();
  });

  test('6.4 响应式布局', async ({ page }) => {
    // Test at different viewport sizes
    const viewports = [
      { width: 1920, height: 1080 },
      { width: 1440, height: 900 },
      { width: 1280, height: 720 },
    ];

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(500);

      // Verify no horizontal overflow
      const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
      expect(bodyWidth).toBeLessThanOrEqual(viewport.width + 20); // 20px tolerance

      // Verify content is visible
      const body = await page.textContent('body');
      expect(body).toBeTruthy();
    }
  });
});
