import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl, calendar, eventType } from "../test/api.ts";
import { renderApp } from "../test/render.tsx";
import { server } from "../test/server.ts";

describe("booking page", () => {
  it("shows whom the guest is booking a call with", async () => {
    server.use(
      http.get(apiUrl("/api/calendar"), () =>
        HttpResponse.json(calendar({ owner: { name: "Мария Петрова" } })),
      ),
    );

    renderApp("/book");

    expect(await screen.findByText("Запись к: Мария Петрова")).toBeInTheDocument();
  });

  it("shows a skeleton while the owner is loading", async () => {
    renderApp("/book");

    expect(screen.getAllByRole("status", { name: "Загрузка" }).length).toBeGreaterThan(0);
    await screen.findByText(/Запись к:/);
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Загрузка" })).not.toBeInTheDocument(),
    );
  });

  it.each([
    ["a server error", () => HttpResponse.json({ code: "boom" }, { status: 500 })],
    ["a network failure", () => HttpResponse.error()],
  ])("offers a retry after %s", async (_name, failure) => {
    server.use(http.get(apiUrl("/api/calendar"), failure, { once: true }));

    renderApp("/book");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось загрузить данные. Попробуйте ещё раз");
    expect(screen.queryByText(/Запись к:/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText("Запись к: Алексей Иванов")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

const LIST = apiUrl("/api/event-types");
const EMPTY = "Владелец пока не добавил типы звонков. Загляните позже.";

describe("choosing an event type", () => {
  it("lists each type as a row with minutes, name and description", async () => {
    server.use(
      http.get(LIST, () =>
        HttpResponse.json([
          eventType({
            id: "intro-call",
            name: "Знакомство",
            description: "Короткий созвон",
            durationMinutes: 15,
          }),
          eventType({
            id: "code-review",
            name: "Разбор кода",
            description: "",
            durationMinutes: 60,
          }),
        ]),
      ),
    );

    renderApp("/book");

    expect(await screen.findByRole("link", { name: /Знакомство/ })).toHaveTextContent(
      "15минутЗнакомствоКороткий созвон",
    );
    expect(screen.getByRole("link", { name: /Разбор кода/ })).toHaveTextContent(
      "60минутРазбор кодаБез описания",
    );
    expect(within(screen.getByRole("main")).getAllByRole("link")).toHaveLength(2);
  });

  it("opens a type by clicking anywhere on its row", async () => {
    server.use(
      http.get(LIST, () => HttpResponse.json([eventType()])),
      http.get(apiUrl("/api/event-types/intro-call"), () => HttpResponse.json(eventType())),
    );
    renderApp("/book");

    const row = await screen.findByRole("link", { name: /Знакомство/ });
    expect(row).toHaveAttribute("href", "/book/intro-call");
    await userEvent.click(screen.getByText("Короткий созвон"));

    expect(await screen.findByRole("heading", { level: 1, name: "Знакомство" })).toBeVisible();
  });

  it("asks the guest to come back later when there are no types, without links", async () => {
    renderApp("/book");

    expect(await screen.findByText(EMPTY)).toBeInTheDocument();
    expect(within(screen.getByRole("main")).queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows a skeleton while the types load", async () => {
    server.use(http.get(LIST, () => HttpResponse.json([eventType()])));
    renderApp("/book");

    expect(screen.getAllByRole("status", { name: "Загрузка" }).length).toBeGreaterThan(0);
    await screen.findByRole("link", { name: /Знакомство/ });
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Загрузка" })).not.toBeInTheDocument(),
    );
  });

  it.each([
    ["a server error", () => HttpResponse.json({ code: "boom" }, { status: 500 })],
    ["a network failure", () => HttpResponse.error()],
  ])("offers a retry when the types fail to load after %s", async (_name, failure) => {
    server.use(http.get(LIST, failure, { once: true }));
    renderApp("/book");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось загрузить данные. Попробуйте ещё раз");
    expect(screen.queryByText(EMPTY)).not.toBeInTheDocument();

    await userEvent.click(within(alert).getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText(EMPTY)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the landing call to action working when there are no types", async () => {
    renderApp("/");

    await userEvent.click(
      within(screen.getByRole("main")).getByRole("link", { name: /Записаться/ }),
    );

    expect(await screen.findByText(EMPTY)).toBeInTheDocument();
  });
});
