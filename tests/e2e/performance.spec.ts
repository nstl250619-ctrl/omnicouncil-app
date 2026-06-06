import { test, expect } from '@playwright/test';

// Section 8: Performance Tests
test.describe('八、性能测试', () => {
  test('8.1 页面加载性能', async ({ page }) => {
    const startTime = Date.now();

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const loadTime = Date.now() - startTime;

    // Page should load within 5 seconds
    expect(loadTime).toBeLessThan(5000);
  });

  test('8.2 首次内容绘制 (FCP)', async ({ page }) => {
    await page.goto('/');

    // Get performance metrics
    const fcp = await page.evaluate(() => {
      const entries = performance.getEntriesByName('first-contentful-paint');
      return entries.length > 0 ? entries[0].startTime : null;
    });

    if (fcp !== null) {
      // FCP should be under 2 seconds
      expect(fcp).toBeLessThan(2000);
    }
  });

  test('8.3 无内存泄漏警告', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    // Check for memory-related console warnings
    const warnings: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'warning' && msg.text().includes('memory')) {
        warnings.push(msg.text());
      }
    });

    await page.waitForTimeout(5000);

    // Should have no memory warnings
    expect(warnings.length).toBe(0);
  });

  test('8.4 DOM 节点数量合理', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);

    const nodeCount = await page.evaluate(() => document.querySelectorAll('*').length);

    // DOM should not be excessively large
    expect(nodeCount).toBeLessThan(5000);
  });

  test('8.5 无布局偏移 (CLS)', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    // Check for layout shift
    const cls = await page.evaluate(() => {
      let clsValue = 0;
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!(entry as any).hadRecentInput) {
            clsValue += (entry as any).value;
          }
        }
      });
      observer.observe({ type: 'layout-shift', buffered: true });
      return clsValue;
    });

    // CLS should be minimal
    expect(cls).toBeLessThan(0.1);
  });
});
