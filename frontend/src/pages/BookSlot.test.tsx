import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl, booking, eventType, slotWindow } from "../test/api.ts";
import { renderApp, renderAppWithHistory } from "../test/render.tsx";
import { server } from "../test/server.ts";

const BOOKINGS = apiUrl("/api/bookings");
const SLOTS = apiUrl("/api/event-types/:id/slots");
const FIRST_SLOT = "09:00 – 09:30";

/** Opens the type, picks 6 November, and returns once its slots are listed. */
async function openDay() {
  server.use(http.get(apiUrl("/api/event-types/:id"), () => HttpResponse.json(eventType())));
  renderApp("/book/intro-call");
  await userEvent.click(await screen.findByRole("button", { name: /^6 ноября/ }));
}

async function pickFirstSlot() {
  await openDay();
  await userEvent.click(screen.getByRole("button", { name: FIRST_SLOT }));
}

async function fillAndSubmit(name = "Мария", email = "maria@example.com") {
  const form = screen.getByRole("form", { name: "Запись на 09:00" });
  const nameInput = within(form).getByLabelText("Имя");
  const emailInput = within(form).getByLabelText("Email");
  await userEvent.clear(nameInput);
  await userEvent.type(nameInput, name);
  await userEvent.clear(emailInput);
  await userEvent.type(emailInput, email);
  await userEvent.click(within(form).getByRole("button", { name: "Записаться" }));
}

const error = (status: number, code: string, extra: object = {}) =>
  HttpResponse.json({ code, message: code, ...extra }, { status });

describe("booking a slot", () => {
  it("offers the slots of the day as buttons and shows the form for the chosen one", async () => {
    await openDay();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: FIRST_SLOT }));

    const form = screen.getByRole("form", { name: "Запись на 09:00" });
    expect(within(form).getByLabelText("Имя")).toBeVisible();
    expect(within(form).getByLabelText("Email")).toBeVisible();
    expect(screen.getByRole("button", { name: FIRST_SLOT })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("sends the booking and confirms it with type, date, time, zone and owner", async () => {
    let sent: unknown;
    server.use(
      http.get(SLOTS, () => HttpResponse.json(slotWindow({ "2026-11-06": [["09:00", "09:30"]] }))),
      http.post(BOOKINGS, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(booking(), { status: 201 });
      }),
    );
    await pickFirstSlot();

    await fillAndSubmit("Мария", "maria@example.com");

    const confirmation = await screen.findByRole("region", {
      name: "Запись подтверждена",
    });
    expect(sent).toEqual({
      eventTypeId: "intro-call",
      start: "2026-11-06T09:00:00+03:00",
      guestName: "Мария",
      guestEmail: "maria@example.com",
      topic: "",
    });
    expect(within(confirmation).getByText("Знакомство")).toBeVisible();
    expect(within(confirmation).getByText(/6 ноября, пятница/)).toBeVisible();
    expect(within(confirmation).getByText(/09:00 – 09:30.*МСК/)).toBeVisible();
    expect(within(confirmation).getByText(/Алексей Иванов/)).toBeVisible();
    expect(within(confirmation).getByText(/Мария/)).toBeVisible();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Дни записи" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /К выбору типа/ })).toHaveAttribute("href", "/book");
  });

  it("sends the optional topic and shows it on the confirmation", async () => {
    let sent: { topic?: string } = {};
    server.use(
      http.get(SLOTS, () => HttpResponse.json(slotWindow({ "2026-11-06": [["09:00", "09:30"]] }))),
      http.post(BOOKINGS, async ({ request }) => {
        sent = (await request.json()) as { topic?: string };
        return HttpResponse.json(booking({ topic: "Обсудить тариф" }), { status: 201 });
      }),
    );
    await pickFirstSlot();
    const form = screen.getByRole("form", { name: "Запись на 09:00" });
    await userEvent.type(within(form).getByLabelText("Тема (необязательно)"), "Обсудить тариф");

    await fillAndSubmit();

    const confirmation = await screen.findByRole("region", { name: "Запись подтверждена" });
    expect(sent.topic).toBe("Обсудить тариф");
    expect(within(confirmation).getByText("Тема: Обсудить тариф")).toBeVisible();
  });

  it("shows server validation errors under the fields and keeps what was typed", async () => {
    server.use(
      http.post(BOOKINGS, () =>
        error(422, "validation_error", {
          fields: [
            { field: "guestName", message: "bad" },
            { field: "guestEmail", message: "bad" },
          ],
        }),
      ),
    );
    await pickFirstSlot();

    await fillAndSubmit("  ", "not-an-email");

    const form = screen.getByRole("form", { name: "Запись на 09:00" });
    expect(within(form).getByLabelText("Имя")).toHaveAccessibleDescription("От 1 до 100 символов");
    expect(within(form).getByLabelText("Email")).toHaveAccessibleDescription(
      "Введите email в формате name@example.com, не длиннее 50 символов",
    );
    expect(within(form).getByLabelText("Email")).toHaveValue("not-an-email");
    expect(within(form).getByRole("button", { name: "Записаться" })).toBeEnabled();
  });

  it("disables the button while the request runs, so the form is sent once", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    let requests = 0;
    server.use(
      http.post(BOOKINGS, async () => {
        requests += 1;
        await gate;
        return HttpResponse.json(booking(), { status: 201 });
      }),
    );
    await pickFirstSlot();

    await fillAndSubmit();
    const button = screen.getByRole("button", { name: "Записаться" });
    expect(button).toBeDisabled();
    await userEvent.click(button);

    release();
    await screen.findByRole("region", { name: "Запись подтверждена" });
    expect(requests).toBe(1);
  });

  it("says the time is taken, refreshes the slots and returns to the choice", async () => {
    server.use(
      http.get(
        SLOTS,
        () =>
          HttpResponse.json(
            slotWindow({
              "2026-11-06": [
                ["09:00", "09:30"],
                ["10:00", "10:30"],
              ],
            }),
          ),
        { once: true },
      ),
      http.get(SLOTS, () => HttpResponse.json(slotWindow({ "2026-11-06": [["10:00", "10:30"]] }))),
      http.post(BOOKINGS, () => error(409, "slot_taken")),
    );
    await pickFirstSlot();

    await fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Это время уже занято. Выберите другое",
    );
    expect(await screen.findByRole("button", { name: "10:00 – 10:30" })).toBeVisible();
    expect(screen.queryByRole("button", { name: FIRST_SLOT })).not.toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it("says the time is unavailable when the slot is no longer valid", async () => {
    server.use(http.post(BOOKINGS, () => error(422, "invalid_slot")));
    await pickFirstSlot();

    await fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent("Время недоступно");
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: FIRST_SLOT })).toBeVisible();
  });

  it("asks to try again when the service is busy, keeping the typed data", async () => {
    server.use(http.post(BOOKINGS, () => error(503, "service_busy"), { once: true }));
    await pickFirstSlot();

    await fillAndSubmit("Мария", "maria@example.com");

    const form = screen.getByRole("form", { name: "Запись на 09:00" });
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Сервис занят. Попробуйте ещё раз",
    );
    expect(within(form).getByLabelText("Имя")).toHaveValue("Мария");

    await userEvent.click(within(form).getByRole("button", { name: "Записаться" }));

    expect(await screen.findByRole("region", { name: "Запись подтверждена" })).toBeVisible();
  });

  it("treats a 503 without the service_busy code as a general failure", async () => {
    server.use(http.post(BOOKINGS, () => error(503, "upstream_unavailable"), { once: true }));
    await pickFirstSlot();

    await fillAndSubmit("Мария", "maria@example.com");

    const form = screen.getByRole("form", { name: "Запись на 09:00" });
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Не удалось записаться. Попробуйте ещё раз",
    );
    expect(within(form).getByLabelText("Имя")).toHaveValue("Мария");
  });

  it("reports a network failure at the form and lets the guest try again", async () => {
    server.use(http.post(BOOKINGS, () => HttpResponse.error(), { once: true }));
    await pickFirstSlot();

    await fillAndSubmit();

    const form = screen.getByRole("form", { name: "Запись на 09:00" });
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Не удалось записаться. Попробуйте ещё раз",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Записаться" }));
    expect(await screen.findByRole("region", { name: "Запись подтверждена" })).toBeVisible();
  });

  it("shows the general failure notice when only fields the form does not show are rejected", async () => {
    server.use(
      http.post(
        BOOKINGS,
        () => error(422, "validation_error", { fields: [{ field: "start", message: "bad" }] }),
        { once: true },
      ),
    );
    await pickFirstSlot();

    await fillAndSubmit("Мария", "maria@example.com");

    const form = screen.getByRole("form", { name: "Запись на 09:00" });
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Не удалось записаться. Попробуйте ещё раз",
    );
    expect(within(form).getByLabelText("Имя")).toHaveValue("Мария");
    expect(within(form).getByLabelText("Email")).toHaveValue("maria@example.com");
    expect(within(form).getByLabelText("Имя")).not.toBeInvalid();
  });

  it("does not show a booking confirmed for one type under another type's address", async () => {
    server.use(
      http.get(apiUrl("/api/event-types/:id"), ({ params }) =>
        HttpResponse.json(
          params.id === "b"
            ? eventType({ id: "b", name: "Тип Б" })
            : eventType({ id: "a", name: "Тип А" }),
        ),
      ),
    );
    renderAppWithHistory(["/book/a", "/book/b"], 0);
    await userEvent.click(await screen.findByRole("button", { name: /^6 ноября/ }));
    await userEvent.click(screen.getByRole("button", { name: FIRST_SLOT }));
    await fillAndSubmit();
    const confirmation = await screen.findByRole("region", { name: "Запись подтверждена" });
    expect(within(confirmation).getByText("Тип А")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "history forward" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Тип Б" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Запись подтверждена" })).not.toBeInTheDocument();
    expect(await screen.findByRole("group", { name: "Дни записи" })).toBeVisible();
  });

  it("switches the form to another slot when the guest picks one", async () => {
    server.use(
      http.get(SLOTS, () =>
        HttpResponse.json(
          slotWindow({
            "2026-11-06": [
              ["09:00", "09:30"],
              ["10:00", "10:30"],
            ],
          }),
        ),
      ),
    );
    await pickFirstSlot();

    await userEvent.click(screen.getByRole("button", { name: "10:00 – 10:30" }));

    expect(screen.getByRole("form", { name: "Запись на 10:00" })).toBeVisible();
    expect(screen.queryByRole("form", { name: "Запись на 09:00" })).not.toBeInTheDocument();
  });
});
