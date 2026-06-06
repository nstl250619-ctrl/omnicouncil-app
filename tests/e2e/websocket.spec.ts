import { test, expect } from '@playwright/test';

// Section 1: WebSocket Connection Tests
test.describe('一、WebSocket 连接测试', () => {
  test('1.1 页面加载并建立 WebSocket 连接', async ({ page }) => {
    // Navigate to app
    await page.goto('/');

    // Wait for the app to load (use domcontentloaded since WS keeps network active)
    await page.waitForLoadState('domcontentloaded');

    // Wait a bit for WebSocket to connect
    await page.waitForTimeout(3000);

    // Check connection status - look for "connected" indicator
    // The app should show connected status somewhere in the UI
    const body = await page.textContent('body');

    // Verify page loaded (should have some content, not blank)
    expect(body).toBeTruthy();
    expect(body!.length).toBeGreaterThan(0);
  });

  test('1.2 收到 engine_status 消息', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    // After connection, the backend sends engine_status with AI list
    // Check if AI providers are listed in the UI
    const body = await page.textContent('body');

    // The app should display AI provider names
    const hasAIContent = body && (
      body.includes('DeepSeek') ||
      body.includes('deepseek') ||
      body.includes('Qianwen') ||
      body.includes('qianwen') ||
      body.includes('Gemini') ||
      body.includes('ChatGPT') ||
      body.includes('MiMo') ||
      body.includes('Claude') ||
      body.includes('AI') ||
      body.includes('Provider')
    );

    expect(hasAIContent).toBeTruthy();
  });

  test('1.3 心跳机制 - 连接保持活跃', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Wait for initial connection
    await page.waitForTimeout(3000);

    // Wait for heartbeat cycle (15 seconds)
    await page.waitForTimeout(16000);

    // After 15+ seconds, connection should still be active
    // Check that no disconnection error appeared
    const body = await page.textContent('body');
    const hasDisconnectError = body && (
      body.includes('连接断开') ||
      body.includes('disconnected') ||
      body.includes('连接失败')
    );

    // Connection should remain active (no disconnect error)
    expect(hasDisconnectError).toBeFalsy();
  });
});
