import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp as renderAt } from "./test/render.tsx";

describe("landing page", () => {
  it("presents the product and what is available right now", () => {
    renderAt("/");

    const main = screen.getByRole("main");
    expect(within(main).getByText("Быстрая запись на звонок")).toBeInTheDocument();
    expect(within(main).getByRole("heading", { level: 1, name: "Calendar" })).toBeInTheDocument();
    expect(
      within(main).getByText(
        "Один экран, понятные слоты, быстрая бронь. Выберите время и запишитесь на звонок без лишних шагов.",
      ),
    ).toBeInTheDocument();

    expect(
      within(main).getByRole("heading", { name: "Что доступно прямо сейчас" }),
    ).toBeInTheDocument();
    const features = within(main).getAllByRole("listitem");
    expect(features.map((item) => item.textContent)).toEqual([
      "Звонки разной длительности на выбор.",
      "Свободные слоты на ближайшие две недели.",
      "Проверка конфликта при бронировании.",
    ]);
  });

  it("invites the guest to book a call", () => {
    renderAt("/");

    const cta = within(screen.getByRole("main")).getByRole("link", { name: /Записаться/ });
    expect(cta).toHaveAttribute("href", "/book");
  });
});

describe("header", () => {
  it("links to the home page and to both sections without highlighting any on the landing", () => {
    renderAt("/");

    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Calendar" })).toHaveAttribute("href", "/");

    const book = within(header).getByRole("link", { name: "Записаться" });
    const admin = within(header).getByRole("link", { name: "Админка" });
    expect(book).toHaveAttribute("href", "/book");
    expect(admin).toHaveAttribute("href", "/admin");
    expect(book).not.toHaveAttribute("aria-current");
    expect(admin).not.toHaveAttribute("aria-current");
    expect(within(header).queryByRole("link", { name: "Предстоящие события" })).toBeNull();
  });

  it.each([
    ["/book", "Записаться", "Админка"],
    ["/admin/bookings", "Админка", "Записаться"],
    ["/admin/event-types", "Админка", "Записаться"],
  ])("highlights only the current section on %s", (path, current, other) => {
    renderAt(path);

    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: current })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(header).getByRole("link", { name: other })).not.toHaveAttribute("aria-current");
  });
});

describe("routing", () => {
  it("opens the booking page from the landing call to action", async () => {
    renderAt("/");

    await userEvent.click(
      within(screen.getByRole("main")).getByRole("link", { name: /Записаться/ }),
    );

    expect(screen.getByRole("heading", { level: 1, name: "Запись на звонок" })).toBeInTheDocument();
  });

  it("opens the admin area from the header", async () => {
    renderAt("/");

    await userEvent.click(
      within(screen.getByRole("banner")).getByRole("link", { name: "Админка" }),
    );

    expect(await screen.findByText(/Предстоящих встреч нет/)).toBeInTheDocument();
  });

  it("sends the old /events address to the landing page, without a redirect page of its own", () => {
    renderAt("/events");

    expect(screen.getByRole("heading", { level: 1, name: "Calendar" })).toBeInTheDocument();
  });

  it("sends an unknown address back to the landing page", () => {
    renderAt("/no-such-page");

    expect(screen.getByRole("heading", { level: 1, name: "Calendar" })).toBeInTheDocument();
  });
});
