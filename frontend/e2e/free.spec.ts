import { test, expect } from "@playwright/test";

test("free mode has no idle polling and completes manual paper trading", async ({
  page,
}) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("websocket", () => errors.push("Unexpected free-mode WebSocket"));
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/"))
      requests.push(request.url());
  });
  await page.goto("/");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  const budget = page.getByRole("region", { name: "무료 사용량 보호" });
  await expect(budget).toBeVisible();
  const count = requests.length;
  // Longer than the old five-second polling period: no request may fire.
  await page.waitForTimeout(6500);
  expect(requests).toHaveLength(count);
  await page
    .getByRole("button", { name: "후보 분석하기", exact: true })
    .click();
  await page.locator(".candidate-card").first().getByRole("button").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".plot-container")).toBeVisible();
  await dialog.getByLabel("매수 수량 (주)", { exact: true }).fill("5");
  await dialog
    .getByRole("button", { name: "모의 투자 주문 제출", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "내 투자의 흐름을 한눈에" }),
  ).toBeVisible();
  await expect(page.locator(".position-card")).toHaveCount(0);
  const refresh = page.getByRole("button", {
    name: "시세·체결 갱신",
    exact: true,
  });
  await refresh.click();
  await expect(
    page.getByText("부분 체결 · 3/5주 체결", { exact: true }),
  ).toBeVisible();
  await refresh.click();
  await expect(
    page.getByText("전량 체결 · 5/5주 체결", { exact: true }),
  ).toBeVisible();
  await page
    .locator(".position-card")
    .getByRole("button", { name: "분석하기", exact: true })
    .click();
  await expect(page.locator(".analysis-card").first()).toBeVisible();
  await page
    .getByRole("navigation", { name: "주 메뉴", exact: true })
    .getByRole("button", { name: "내 투자", exact: true })
    .click();
  await page
    .locator(".position-card")
    .getByRole("button", { name: "일부 / 전량 모의 매도", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "전량 모의 매도 주문 제출", exact: true })
    .click();
  await refresh.click();
  await expect(refresh).toBeEnabled();
  await refresh.click();
  await expect(
    page.getByRole("heading", { name: "아직 체결된 보유 종목이 없어요" }),
  ).toBeVisible();
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth + 1,
      ),
    ).toBeTruthy();
    await expect(budget).toBeVisible();
  }
  expect(errors).toEqual([]);
});
