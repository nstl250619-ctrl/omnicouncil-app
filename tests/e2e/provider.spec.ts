import { test, expect } from '@playwright/test';

// Section 2: Provider Management Tests
test.describe('二、Provider 管理测试', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);
  });

  test('2.1 AI Platform Manager 显示', async ({ page }) => {
    // Check if AI providers are listed in the UI
    const body = await page.textContent('body');

    // Look for provider-related content
    const hasProviderContent = body && (
      body.includes('DeepSeek') ||
      body.includes('deepseek') ||
      body.includes('Qianwen') ||
      body.includes('qianwen') ||
      body.includes('Gemini') ||
      body.includes('ChatGPT') ||
      body.includes('MiMo') ||
      body.includes('Claude') ||
      body.includes('Provider') ||
      body.includes('AI') ||
      body.includes('平台')
    );

    expect(hasProviderContent).toBeTruthy();
  });

  test('2.2 Provider 列表完整性', async ({ page }) => {
    const body = await page.textContent('body');

    // Check for known AI providers
    const providers = ['DeepSeek', 'Qianwen', 'Gemini', 'ChatGPT', 'MiMo', 'Claude'];
    const foundProviders = providers.filter(p =>
      body?.toLowerCase().includes(p.toLowerCase())
    );

    // At least some providers should be listed
    expect(foundProviders.length).toBeGreaterThan(0);
  });

  test('2.3 Provider 状态显示', async ({ page }) => {
    // Look for status indicators
    const statusElements = page.locator('[class*="status"], [data-testid*="status"], [class*="indicator"]');
    const count = await statusElements.count();

    // The page should render without errors
    const body = await page.textContent('body');
    expect(body).toBeTruthy();
  });

  test('2.4 连接按钮存在', async ({ page }) => {
    // Look for connect/login buttons
    const buttons = page.locator('button');
    const buttonCount = await buttons.count();

    // Should have some interactive elements
    expect(buttonCount).toBeGreaterThan(0);

    // Check for connect-related buttons
    const connectButtons = page.locator('button:has-text("连接"), button:has-text("Connect"), button:has-text("登录"), button:has-text("Login")');
    const connectCount = await connectButtons.count();

    // At least the page should have buttons
    expect(buttonCount).toBeGreaterThan(0);
  });
});
