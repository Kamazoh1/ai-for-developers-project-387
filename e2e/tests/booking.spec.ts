import { expect, test, type Page } from "@playwright/test";

/**
 * Picks the first day after today that has free time and returns its label (`6 ноября, пятница`).
 * The window starts today and today's slots only exist before the working day ends,
 * so the test never depends on the wall clock or on a fixed date.
 */
async function pickFirstFreeDayAfterToday(page: Page): Promise<string> {
  const days = page.getByRole("group", { name: "Дни записи" }).getByRole("button");
  await expect(days).toHaveCount(14);
  for (let index = 1; index < 14; index++) {
    const day = days.nth(index);
    if (await day.isEnabled()) {
      const label = await day.getAttribute("aria-label");
      await day.click();
      return label!;
    }
  }
  throw new Error("no day with free slots in the booking window");
}

async function fillGuest(page: Page, name: string, email: string) {
  await page.getByLabel("Имя").fill(name);
  await page.getByLabel("Email").fill(email);
}

test("two guests race for one slot, the owner sees the winner", async ({
  page,
  browser,
  baseURL,
  request,
}) => {
  const run = Date.now().toString(36);
  const slug = `e2e-${run}`;
  const typeName = `Знакомство ${run}`;
  const guest = { name: `Мария Петрова ${run}`, email: `maria-${run}@example.com` };

  // Setup: the owner's event type, created through the real API.
  const created = await request.post("/api/admin/event-types", {
    data: { id: slug, name: typeName, description: "Короткий созвон", durationMinutes: 30 },
  });
  expect(created.status()).toBe(201);

  // Guest 1 chooses a slot and fills in the form...
  await page.goto(`/book/${slug}`);
  const dayLabel = await pickFirstFreeDayAfterToday(page);
  const slotButton = page.getByRole("region", { name: /^Свободное время/ }).getByRole("button");
  const slotLabel = (await slotButton.first().textContent())!; // e.g. "09:00 – 09:30"
  await slotButton.first().click();
  await fillGuest(page, guest.name, guest.email);

  // ...while guest 2, in a separate browser, has the same slot open with a filled-in form.
  const secondGuest = await browser.newContext({ baseURL, locale: "ru-RU" });
  const page2 = await secondGuest.newPage();
  await page2.goto(`/book/${slug}`);
  await page2.getByRole("button", { name: dayLabel, exact: true }).click();
  await page2.getByRole("button", { name: slotLabel, exact: true }).click();
  await fillGuest(page2, "Пётр Сидоров", `petr-${run}@example.com`);

  // Guest 1 books first and sees the confirmation: type, day, time and zone.
  await page.getByRole("button", { name: "Записаться" }).click();
  const confirmation = page.getByRole("region", { name: "Запись подтверждена" });
  await expect(confirmation).toContainText(typeName);
  await expect(confirmation).toContainText(dayLabel);
  await expect(confirmation).toContainText(`${slotLabel} МСК`);

  // Guest 2 submits the same slot and is told it is gone; the slot disappears from the list.
  await page2.getByRole("button", { name: "Записаться" }).click();
  await expect(page2.getByRole("alert")).toHaveText("Это время уже занято. Выберите другое");
  await expect(page2.getByRole("button", { name: slotLabel, exact: true })).toHaveCount(0);
  await secondGuest.close();

  // The owner opens the admin area and sees the meeting of guest 1, and only that one.
  const owner = await browser.newContext({ baseURL, locale: "ru-RU" });
  const adminPage = await owner.newPage();
  await adminPage.goto("/admin/bookings");
  const meetings = adminPage.getByRole("article");
  await expect(meetings).toHaveCount(1);
  const meeting = meetings.first();
  await expect(meeting).toContainText(guest.name);
  await expect(meeting).toContainText(guest.email);
  await expect(meeting).toContainText(typeName);
  await expect(meeting).toContainText(dayLabel);
  await expect(meeting).toContainText(`${slotLabel} МСК`);
  await expect(meeting).toContainText("Ближайшая");
  await owner.close();
});
