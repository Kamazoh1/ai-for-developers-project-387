import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl, eventType, slotWindow } from "../test/api.ts";
import { renderApp } from "../test/render.tsx";
import { server } from "../test/server.ts";

const DETAIL = apiUrl("/api/event-types/:id");
const notFound = () =>
  HttpResponse.json({ code: "event_type_not_found", message: "No event type" }, { status: 404 });

describe("a chosen event type", () => {
  it("opens the type named in the address", async () => {
    server.use(
      http.get(DETAIL, ({ params }) =>
        params.id === "code-review"
          ? HttpResponse.json(
              eventType({
                id: "code-review",
                name: "Разбор кода",
                description: "Смотрим ваш код вместе",
                durationMinutes: 60,
              }),
            )
          : notFound(),
      ),
    );

    renderApp("/book/code-review");

    expect(await screen.findByRole("heading", { level: 1, name: "Разбор кода" })).toBeVisible();
    const main = screen.getByRole("main");
    expect(within(main).getByText("Смотрим ваш код вместе")).toBeInTheDocument();
    expect(within(main).getByText("60 минут")).toBeInTheDocument();
    expect(within(main).getByRole("link", { name: /К выбору типа/ })).toHaveAttribute(
      "href",
      "/book",
    );
  });

  it("says the type is not found for an unknown address and links back to /book", async () => {
    server.use(http.get(DETAIL, notFound));
    renderApp("/book/nope");

    expect(await screen.findByText("Тип события не найден")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const back = within(screen.getByRole("main")).getByRole("link", { name: /К выбору типа/ });
    expect(back).toHaveAttribute("href", "/book");
  });

  it("shows a skeleton while the type loads", async () => {
    server.use(http.get(DETAIL, () => HttpResponse.json(eventType())));
    renderApp("/book/intro-call");

    expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument();
    await screen.findByRole("heading", { level: 1, name: "Знакомство" });
    await screen.findByRole("group", { name: "Дни записи" }); // the slots load after the type
    expect(screen.queryByRole("status", { name: "Загрузка" })).not.toBeInTheDocument();
  });

  it.each([
    ["a server error", () => HttpResponse.json({ code: "boom" }, { status: 500 })],
    ["a network failure", () => HttpResponse.error()],
  ])("offers a retry after %s, not a not-found message", async (_name, failure) => {
    server.use(
      http.get(DETAIL, failure, { once: true }),
      http.get(DETAIL, () => HttpResponse.json(eventType())),
    );
    renderApp("/book/intro-call");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось загрузить данные. Попробуйте ещё раз");
    expect(screen.queryByText("Тип события не найден")).not.toBeInTheDocument();

    await userEvent.click(within(alert).getByRole("button", { name: "Повторить" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Знакомство" })).toBeVisible();
  });

  it("returns to the list of types with the back link", async () => {
    server.use(
      http.get(DETAIL, () => HttpResponse.json(eventType())),
      http.get(apiUrl("/api/event-types"), () => HttpResponse.json([eventType()])),
    );
    renderApp("/book/intro-call");

    await userEvent.click(await screen.findByRole("link", { name: /К выбору типа/ }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Запись на звонок" }),
    ).toBeVisible();
  });
});

describe("free slots of a chosen event type", () => {
  const SLOTS = apiUrl("/api/event-types/:id/slots");

  function openType() {
    server.use(http.get(DETAIL, () => HttpResponse.json(eventType())));
    renderApp("/book/intro-call");
  }

  async function dayButtons() {
    const days = await screen.findByRole("group", { name: "Дни записи" });
    return within(days).getAllByRole("button");
  }

  it("shows the 14-day window, with days that have no slots grey and unavailable", async () => {
    server.use(
      http.get(SLOTS, () =>
        HttpResponse.json(
          slotWindow({ "2026-11-06": [["09:00", "09:30"]], "2026-11-09": [["10:00", "10:30"]] }),
        ),
      ),
    );
    openType();

    const buttons = await dayButtons();

    expect(buttons).toHaveLength(14);
    expect(buttons.filter((button) => button.hasAttribute("disabled"))).toHaveLength(12);
    expect(screen.getByRole("button", { name: /^6 ноября/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^9 ноября/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^5 ноября/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^18 ноября/ })).toBeDisabled();
  });

  it("shows the slots of the chosen day, as times in the calendar zone with its label", async () => {
    server.use(
      http.get(SLOTS, () =>
        HttpResponse.json(
          slotWindow({
            "2026-11-06": [
              ["09:00", "09:30"],
              ["17:30", "18:00"],
            ],
            "2026-11-09": [["10:00", "10:30"]],
          }),
        ),
      ),
    );
    openType();
    await dayButtons();
    expect(screen.queryByText("09:00 – 09:30")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^6 ноября/ }));

    const slots = screen.getByRole("region", { name: /Свободное время.*6 ноября/ });
    expect(within(slots).getByText("09:00 – 09:30")).toBeVisible();
    expect(within(slots).getByText("17:30 – 18:00")).toBeVisible();
    expect(within(slots).getByText(/МСК/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: /^9 ноября/ }));

    expect(screen.queryByText("09:00 – 09:30")).not.toBeInTheDocument();
    expect(screen.getByText("10:00 – 10:30")).toBeVisible();
  });

  it("marks the chosen day as pressed", async () => {
    openType();
    await dayButtons();

    await userEvent.click(screen.getByRole("button", { name: /^6 ноября/ }));

    expect(screen.getByRole("button", { name: /^6 ноября/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("says there is no free time at all and offers the way back to the types", async () => {
    server.use(http.get(SLOTS, () => HttpResponse.json(slotWindow())));
    openType();

    expect(
      await screen.findByText(
        "На ближайшие две недели свободного времени нет. Загляните позже или выберите другой тип звонка",
      ),
    ).toBeVisible();
    const buttons = await dayButtons();
    expect(buttons.every((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(
      within(screen.getByRole("main")).getByRole("link", { name: /К выбору типа/ }),
    ).toHaveAttribute("href", "/book");
  });

  it("does not show the empty message while there is free time", async () => {
    openType();
    await dayButtons();

    expect(screen.queryByText(/свободного времени нет/)).not.toBeInTheDocument();
  });

  it("offers a retry when slots fail to load, keeping the type on screen", async () => {
    server.use(
      http.get(SLOTS, () => HttpResponse.error(), { once: true }),
      http.get(SLOTS, () => HttpResponse.json(slotWindow({ "2026-11-06": [["09:00", "09:30"]] }))),
    );
    openType();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось загрузить данные. Попробуйте ещё раз");
    expect(screen.getByRole("heading", { level: 1, name: "Знакомство" })).toBeVisible();

    await userEvent.click(within(alert).getByRole("button", { name: "Повторить" }));

    expect(await dayButtons()).toHaveLength(14);
  });
});
