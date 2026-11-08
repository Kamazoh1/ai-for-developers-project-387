import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Booking } from "../../api/types.gen.ts";
import { apiUrl, booking, eventType } from "../../test/api.ts";
import { renderApp } from "../../test/render.tsx";
import { server } from "../../test/server.ts";

const BOOKINGS = apiUrl("/api/admin/bookings");
const TYPES = apiUrl("/api/event-types");

function backendWith(bookings: Booking[]) {
  server.use(
    http.get(BOOKINGS, () => HttpResponse.json(bookings)),
    http.get(TYPES, () =>
      HttpResponse.json([
        eventType({ id: "intro-call", name: "Знакомство", durationMinutes: 15 }),
        eventType({ id: "code-review", name: "Разбор кода", durationMinutes: 90 }),
      ]),
    ),
  );
}

describe("upcoming meetings page", () => {
  it("shows each meeting as a card with when, who, the type name and the duration", async () => {
    backendWith([
      booking({
        id: 1,
        eventTypeId: "intro-call",
        start: "2026-11-06T09:00:00+03:00",
        end: "2026-11-06T09:30:00+03:00",
        guestName: "Мария",
        guestEmail: "maria@example.com",
      }),
    ]);

    renderApp("/admin/bookings");

    const card = await screen.findByRole("article");
    expect(within(card).getByText("6 ноября, пятница")).toBeVisible();
    expect(within(card).getByText("09:00 – 09:30 МСК")).toBeVisible();
    expect(within(card).getByText("Мария")).toBeVisible();
    expect(within(card).getByText("maria@example.com")).toBeVisible();
    // The booking carries only the type id: the name comes from the event types list.
    expect(within(card).getByText("Знакомство")).toBeVisible();
    expect(within(card).getByText("30 мин")).toBeVisible();
  });

  it("shows the guest's topic as plain text, and only on bookings that have one", async () => {
    backendWith([
      booking({ id: 1, guestName: "Анна", topic: "Обсудить <i>релиз</i>" }),
      booking({ id: 2, guestName: "Борис", topic: "" }),
    ]);

    renderApp("/admin/bookings");

    const [withTopic, withoutTopic] = await screen.findAllByRole("article");
    expect(within(withTopic).getByText("Тема: Обсудить <i>релиз</i>")).toBeVisible();
    expect(within(withoutTopic).queryByText(/Тема:/)).not.toBeInTheDocument();
  });

  it("keeps the line breaks the guest typed in the topic", async () => {
    backendWith([booking({ id: 1, guestName: "Анна", topic: "Первое\nВторое" })]);

    renderApp("/admin/bookings");

    const [card] = await screen.findAllByRole("article");
    // `pre-line` shows the break; without it the browser folds the text into one line.
    expect(within(card).getByText(/Тема: Первое/)).toHaveStyle({ whiteSpace: "pre-line" });
  });

  it("lists meetings in the order the server returns them and shows long durations in hours", async () => {
    backendWith([
      booking({
        id: 1,
        eventTypeId: "intro-call",
        start: "2026-11-06T09:00:00+03:00",
        end: "2026-11-06T09:15:00+03:00",
        guestName: "Анна",
      }),
      booking({
        id: 2,
        eventTypeId: "code-review",
        start: "2026-11-07T15:00:00+03:00",
        end: "2026-11-07T16:30:00+03:00",
        guestName: "Борис",
      }),
    ]);

    renderApp("/admin/bookings");

    const cards = await screen.findAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText("Анна")).toBeVisible();
    expect(within(cards[1]).getByText("Борис")).toBeVisible();
    expect(within(cards[1]).getByText("7 ноября, суббота")).toBeVisible();
    expect(within(cards[1]).getByText("Разбор кода")).toBeVisible();
    expect(within(cards[1]).getByText("1 ч 30 мин")).toBeVisible();
  });

  it("marks only the nearest meeting", async () => {
    backendWith([
      booking({ id: 1, guestName: "Анна" }),
      booking({ id: 2, guestName: "Борис", start: "2026-11-07T10:00:00+03:00" }),
      booking({ id: 3, guestName: "Вера", start: "2026-11-08T10:00:00+03:00" }),
    ]);

    renderApp("/admin/bookings");

    const cards = await screen.findAllByRole("article");
    expect(within(cards[0]).getByText("Ближайшая")).toBeVisible();
    expect(within(cards[1]).queryByText("Ближайшая")).not.toBeInTheDocument();
    expect(within(cards[2]).queryByText("Ближайшая")).not.toBeInTheDocument();
    expect(screen.getAllByText("Ближайшая")).toHaveLength(1);
  });

  it("shows the type id when the type is not in the list", async () => {
    backendWith([booking({ eventTypeId: "gone-type" })]);

    renderApp("/admin/bookings");

    expect(within(await screen.findByRole("article")).getByText("gone-type")).toBeVisible();
  });

  it("explains that there are no upcoming meetings", async () => {
    renderApp("/admin/bookings");

    expect(
      await screen.findByText(
        "Предстоящих встреч нет. Когда гость запишется, встреча появится здесь.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("shows a skeleton while loading", async () => {
    backendWith([booking()]);

    renderApp("/admin/bookings");

    expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument();
    await screen.findByRole("article");
    expect(screen.queryByRole("status", { name: "Загрузка" })).not.toBeInTheDocument();
  });

  it.each([
    ["the meetings", BOOKINGS],
    ["the event types", TYPES],
  ])("offers a retry when %s cannot be loaded", async (_name, url) => {
    backendWith([booking({ guestName: "Мария" })]);
    server.use(
      http.get(url, () => HttpResponse.json({ code: "boom" }, { status: 500 }), { once: true }),
    );

    renderApp("/admin/bookings");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось загрузить данные. Попробуйте ещё раз",
    );
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));

    expect(within(await screen.findByRole("article")).getByText("Мария")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
