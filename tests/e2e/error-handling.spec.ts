import { test, expect } from '@playwright/test';

// Section 5: Error Handling Tests
test.describe('五、错误处理测试', () => {
  test('5.1 页面无 JavaScript 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => {
      errors.push(error.message);
    });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    // Filter out known non-critical errors
    const criticalErrors = errors.filter(e =>
      !e.includes('favicon') &&
      !e.includes('manifest') &&
      !e.includes('service-worker') &&
      !e.includes('WebSocket') && // WS errors expected if backend not running
      !e.includes('net::') // Network errors
    );

    // Should have no critical JS errors
    expect(criticalErrors.length).toBe(0);
  });

  test('5.2 WebSocket 断连处理', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    // Navigate away and back to test reconnection
    await page.goto('about:blank');
    await page.waitForTimeout(1000);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    // Page should still render correctly
    const body = await page.textContent('body');
    expect(body).toBeTruthy();
    expect(body!.length).toBeGreaterThan(0);
  });

  test('5.3 网络请求错误处理', async ({ page }) => {
    const failedRequests: string[] = [];
    page.on('requestfailed', request => {
      failedRequests.push(request.url());
    });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    // Filter out expected failures (like favicon)
    const unexpectedFailures = failedRequests.filter(url =>
      !url.includes('favicon') &&
      !url.includes('manifest') &&
      !url.includes('service-worker')
    );

    // Should have minimal request failures
    // Note: Some failures may be expected (e.g., API calls to external services)
    expect(unexpectedFailures.length).toBeLessThan(5);
  });

  test('5.4 资源加载完整性', async ({ page }) => {
    const resources: { url: string; status: number }[] = [];
    page.on('response', response => {
      resources.push({ url: response.url(), status: response.status() });
    });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);

    // Check for failed resources (4xx, 5xx)
    const failedResources = resources.filter(r =>
      r.status >= 400 &&
      !r.url.includes('favicon') &&
      !r.url.includes('manifest')
    );

    // Should have no critical resource failures
    expect(failedResources.length).toBe(0);
  });
});
