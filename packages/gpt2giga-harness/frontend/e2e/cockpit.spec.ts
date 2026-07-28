import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test("renders and navigates without console errors or horizontal overflow", async ({
  page,
}, testInfo) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/local-access");
  await page.getByRole("button", { name: "Recover this browser" }).click();
  await expect(page).toHaveURL(/\/cockpit-v2\/settings$/);

  await page.goto("/cockpit-v2/work");
  await expect(page).toHaveURL(/\/cockpit-v2\/work(?:\/[^/]+)?$/);
  await expect(page).toHaveTitle("GigaLoom");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.locator(".surface-shell")).not.toBeEmpty();
  await expectNoHorizontalOverflow(page);

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/cockpit-v2\/settings$/);
  await expect(page.locator(".surface-shell")).not.toBeEmpty();
  await expectNoHorizontalOverflow(page);

  await page.screenshot({
    fullPage: false,
    path: testInfo.outputPath("cockpit-settings.png"),
  });
  expect(pageErrors, "uncaught browser errors").toEqual([]);
  expect(consoleErrors, "browser console errors").toEqual([]);
});

async function expectNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}
