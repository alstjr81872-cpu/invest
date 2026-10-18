import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
const password =
  process.env.E2E_PASSWORD ||
  (process.env.E2E_PASSWORD_FILE
    ? readFileSync(process.env.E2E_PASSWORD_FILE, "utf8").trim()
    : "");
if (!password)
  throw new Error(
    "Set E2E_PASSWORD or E2E_PASSWORD_FILE for your local owner account",
  );
const screenshots = "../.local/screenshots";
mkdirSync(screenshots, { recursive: true });
async function assertNoOverflow(page) {
  const size = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(size.scroll).toBeLessThanOrEqual(size.width + 1);
}
test("private login, charts, paper buy, analysis, explicit sell and reconnect", async ({
  page,
  context,
}) => {
  const exceptions: string[] = [];
  page.on("pageerror", (e) => exceptions.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "나의 연구실에 로그인" }),
  ).toBeVisible();
  await page.screenshot({
    path: screenshots + "/login-1440.png",
    fullPage: true,
  });
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "다음 투자를, 근거 있게." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "후보 분석하기", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "후보 분석하기", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "후보 분석하기", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".candidate-card").first()).toBeVisible();
  await page.screenshot({
    path: screenshots + "/dashboard-1440.png",
    fullPage: true,
  });
  await assertNoOverflow(page);
  await page.locator(".candidate-card").first().getByRole("button").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(".plot-container")).toBeVisible();
  await dialog.getByLabel("매수 수량 (주)", { exact: true }).fill("5");
  await page.screenshot({
    path: screenshots + "/detail-1440.png",
    fullPage: true,
  });
  await dialog
    .getByRole("button", { name: "모의 투자 주문 제출", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "내 투자의 흐름을 한눈에" }),
  ).toBeVisible();
  await expect(page.locator(".position-card").first()).toBeVisible();
  await expect(
    page.getByText("전량 체결 · 5/5주 체결", { exact: true }),
  ).toBeVisible();
  await page
    .locator(".position-card")
    .first()
    .getByRole("button", { name: "분석하기", exact: true })
    .click();
  await expect(
    page
      .locator(".analysis-card")
      .first()
      .getByRole("heading", { name: "이전 분석 대비 변화" }),
  ).toBeVisible();
  await page.screenshot({
    path: screenshots + "/analysis-1440.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "과거 검증", exact: true }).click();
  await page
    .getByRole("button", { name: "가격 전략 실험 실행", exact: true })
    .click();
  await expect(page.getByText("거래 수", { exact: true })).toBeVisible();
  await page
    .getByRole("navigation", { name: "주 메뉴", exact: true })
    .getByRole("button", { name: "내 투자", exact: true })
    .click();
  await page.screenshot({
    path: screenshots + "/portfolio-1440.png",
    fullPage: true,
  });
  const old = await page
    .locator(".position-card .big-number")
    .first()
    .textContent();
  await expect
    .poll(
      async () =>
        await page.locator(".position-card .big-number").first().textContent(),
      { timeout: 15000 },
    )
    .not.toBe(old);
  await context.setOffline(true);
  await expect(
    page.getByText("시세 또는 워커 연결을 확인하고 있어요.", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: screenshots + "/disconnected-1440.png",
    fullPage: true,
  });
  await context.setOffline(false);
  await expect(page.locator(".demo-banner")).toBeVisible();
  await expect(
    page.getByText("시세 또는 워커 연결을 확인하고 있어요.", { exact: false }),
  ).not.toBeVisible({ timeout: 35000 });
  await page
    .locator(".position-card")
    .first()
    .getByRole("button", { name: "일부 / 전량 모의 매도", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "전량 모의 매도 주문 제출", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "아직 체결된 보유 종목이 없어요" }),
  ).toBeVisible();
  // Responsive layouts and 200% browser-equivalent CSS viewport; form labels remain visible.
  for (const width of [360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const nav =
      width <= 950
        ? page.getByRole("navigation", { name: "모바일 주 메뉴", exact: true })
        : page.getByRole("navigation", { name: "주 메뉴", exact: true });
    await nav.getByRole("button", { name: "추천 종목", exact: true }).click();
    await assertNoOverflow(page);
    await page.screenshot({
      path: `${screenshots}/dashboard-${width}.png`,
      fullPage: true,
    });
    await nav.getByRole("button", { name: "설정", exact: true }).click();
    await assertNoOverflow(page);
    await expect(
      page.getByLabel("직접 입력 (2~20거래일)", { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `${screenshots}/settings-${width}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 720, height: 500 });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  await assertNoOverflow(page);
  await page.screenshot({
    path: screenshots + "/zoom-200.png",
    fullPage: true,
  });
  expect(exceptions).toEqual([]);
});

test("360px mobile login, order input, portfolio, analysis and explicit sell", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 850 });
  await page.goto("/");
  await page.screenshot({
    path: screenshots + "/login-360.png",
    fullPage: true,
  });
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  const nav = page.getByRole("navigation", {
    name: "모바일 주 메뉴",
    exact: true,
  });
  await expect(
    page.getByRole("button", { name: "후보 분석하기", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "후보 분석하기", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "후보 분석하기", exact: true }),
  ).toBeEnabled();
  await page.locator(".candidate-card").first().getByRole("button").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".plot-container")).toBeVisible();
  await assertNoOverflow(page);
  expect(
    await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1),
  ).toBeTruthy();
  await dialog.getByLabel("매수 수량 (주)", { exact: true }).fill("5");
  await dialog
    .getByRole("button", { name: "모의 투자 주문 제출", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: screenshots + "/order-360.png",
    fullPage: true,
  });
  await dialog
    .getByRole("button", { name: "모의 투자 주문 제출", exact: true })
    .click();
  await expect(page.locator(".position-card")).toHaveCount(1);
  await expect(
    page.getByText("전량 체결 · 5/5주 체결", { exact: true }).first(),
  ).toBeVisible();
  await assertNoOverflow(page);
  await page.screenshot({
    path: screenshots + "/portfolio-360.png",
    fullPage: true,
  });
  await page
    .locator(".position-card")
    .getByRole("button", { name: "분석하기", exact: true })
    .click();
  await expect(
    page
      .locator(".analysis-card")
      .first()
      .getByRole("heading", { name: "이전 분석 대비 변화" }),
  ).toBeVisible();
  await assertNoOverflow(page);
  await page.screenshot({
    path: screenshots + "/analysis-360.png",
    fullPage: true,
  });
  await nav.getByRole("button", { name: "내 투자", exact: true }).click();
  await page
    .locator(".position-card")
    .getByRole("button", { name: "일부 / 전량 모의 매도", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "전량 모의 매도 주문 제출", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "아직 체결된 보유 종목이 없어요" }),
  ).toBeVisible();
});
