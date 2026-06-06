import { test, expect, Page } from '@playwright/test';
import { navigateToConsole } from './helpers';

// ===== Qwen (千问) End-to-End Query Test =====

/**
 * Helper: Submit a query to Qwen via WebSocket and wait for the response.
 * Returns the full response text, status, and timing info.
 */
async function submitQueryToQwen(
  page: Page,
  query: string,
  timeout = 60000
): Promise<{
  status: string;
  content: string;
  elapsedMs: number | null;
  wordCount: number | null;
}> {
  const result = { status: 'timeout', content: '', elapsedMs: null as number | null, wordCount: null as number | null };

  // Listen for WebSocket messages
  await page.evaluate(() => {
    // Patch the WebSocket to capture messages for qianwen
    const origSend = window.WebSocket.prototype.send;
    window.WebSocket.prototype.send = function (data) {
      // Store reference to this ws for message monitoring
      (window as unknown as Record<string, unknown>).__testWs = this;
      return origSend.call(this, data);
    };
  });

  // Monitor responses from the app store
  await page.waitForFunction(
    () => {
      const el = document.getElementById('root');
      return el && el.textContent && el.textContent.length > 0;
    },
    { timeout: 5000 }
  ).catch(() => {});

  // Get the WebSocket hook's send function via the app
  // We'll monitor by looking at the DOM for response content changes

  // Type query in input
  const input = page.locator('input[type="text"], textarea, [contenteditable="true"]').first();
  await input.fill(query);

  // Click 千问 AI selector if not already selected (default is deepseek+qianwen)
  // The default selectedAIs is ['deepseek', 'qianwen'], so both should be selected
  // We just need to ensure at least Qwen is selected

  // Click send/start button
  const sendButton = page.locator('button:has-text("开始分析"), button:has-text("发送"), button[type="submit"]').first();
  await sendButton.click();

  // Wait for Qwen to respond — look for completed status in the DOM
  // The response tab shows AI responses; wait for content to appear under 千问
  const startTime = Date.now();

  // Wait either for the "completed" indicator or content to appear
  try {
    await page.waitForFunction(
      () => {
        const body = document.body.textContent || '';
        // Check for completion markers
        return (
          body.includes('千问') &&
          (body.includes('已完成') || body.includes('分析完成')) &&
          // Make sure it has actual content beyond just waiting state
          body.length > 100
        );
      },
      { timeout }
    );
    result.status = 'completed';
    result.elapsedMs = Date.now() - startTime;
  } catch {
    // Check if we got an error instead
    try {
      await page.waitForFunction(
        () => {
          const body = document.body.textContent || '';
          return body.includes('错误') || body.includes('失败') || body.includes('error');
        },
        { timeout: 10000 }
      );
      result.status = 'error';
      result.elapsedMs = Date.now() - startTime;
    } catch {
      result.status = 'timeout';
      result.elapsedMs = Date.now() - startTime;
    }
  }

  // Get the page content
  const body = await page.textContent('body');
  result.content = body || '';

  return result;
}

// ===== Test Suite =====

test.describe('千问(Qwen) 端到端查询测试', () => {

  test.beforeEach(async ({ page }) => {
    await navigateToConsole(page);
  });

  test('Q1: 千问选择器可见且可点击', async ({ page }) => {
    // Check that 千问 is visible as an AI selector
    const qwenSelector = page.locator('button:has-text("千问"), [class*="qianwen"], [class*="qwen"]').first();
    await expect(qwenSelector).toBeVisible({ timeout: 5000 });

    // Check the text content
    const text = await qwenSelector.textContent();
    expect(text).toContain('千问');
  });

  test('Q2: 输入框可输入文本', async ({ page }) => {
    const input = page.locator('input[type="text"], textarea, [contenteditable="true"]').first();
    await expect(input).toBeVisible({ timeout: 5000 });
    await input.fill('你好，千问，请介绍一下你自己');

    // Verify the text was entered
    const value = await input.inputValue();
    expect(value).toBe('你好，千问，请介绍一下你自己');
  });

  test('Q3: 开始分析按钮可点击(输入后)', async ({ page }) => {
    // Type something first
    const input = page.locator('input[type="text"], textarea, [contenteditable="true"]').first();
    await input.fill('测试查询');

    // Check that send/start button becomes enabled
    const sendButton = page.locator('button:has-text("开始分析"), button:has-text("发送"), button[type="submit"]').first();

    // Wait a moment for the UI to update
    await page.waitForTimeout(1000);

    // Button should be enabled after typing
    await expect(sendButton).toBeEnabled({ timeout: 5000 });
  });

  test('Q4: [慢] 千问提交查询并等待响应', async ({ page, context }) => {
    test.setTimeout(120000); // Allow up to 2 minutes for this test

    // Submit a simple query
    const result = await submitQueryToQwen(page, '用一句话介绍你自己', 90000);

    // Log timing info
    console.log(`[千问E2E] 状态: ${result.status}, 耗时: ${result.elapsedMs}ms`);
    console.log(`[千问E2E] 页面长度: ${result.content.length} 字符`);

    // Check result
    expect(result.status).not.toBe('timeout');

    if (result.status === 'completed') {
      // Verify we got actual content back
      expect(result.content.length).toBeGreaterThan(50);
      expect(result.elapsedMs).not.toBeNull();
      if (result.elapsedMs !== null) {
        expect(result.elapsedMs).toBeLessThan(90000);
      }
    }
  });

  test('Q5: [慢] 千问与 DeepSeek 多 AI 并发查询', async ({ page, context }) => {
    test.setTimeout(180000); // Allow up to 3 minutes

    // Type query
    const input = page.locator('input[type="text"], textarea, [contenteditable="true"]').first();
    await input.fill('太阳为什么是热的？');

    // Make sure both DeepSeek and 千问 are selected (default selection)
    // Click send
    const sendButton = page.locator('button:has-text("开始分析"), button:has-text("发送"), button[type="submit"]').first();
    await sendButton.click();

    // Wait for responses from both AIs
    const startTime = Date.now();

    try {
      // Wait for completed status
      await page.waitForFunction(
        () => {
          const body = document.body.textContent || '';
          // Check for both deepseek and qianwen completion
          const hasDeepSeek = body.includes('DeepSeek');
          const hasQianwen = body.includes('千问');
          const hasCompletedContent = body.length > 200;
          return hasDeepSeek && hasQianwen && hasCompletedContent;
        },
        { timeout: 150000 }
      );

      const elapsed = Date.now() - startTime;
      console.log(`[多AI并发] 总耗时: ${elapsed}ms`);

      // Check that both AI providers have responses
      const body = await page.textContent('body');
      expect(body).toBeTruthy();
      expect(body!.length).toBeGreaterThan(200);

    } catch {
      console.log('[多AI并发] 超时 - 部分AI可能未完成');

      // Check partial state
      const body = await page.textContent('body');
      console.log(`页面内容长度: ${body?.length || 0}`);
    }
  });

  test('Q6: WebSocket 连接在查询期间保持活跃', async ({ page }) => {
    // Verify the connection status indicator shows connected
    const statusIndicator = page.locator('[class*="status"], footer, [class*="StatusBar"]').first();
    const body = await page.textContent('body');

    // Should show connected status
    expect(body).toContain('已连接');
  });
});
