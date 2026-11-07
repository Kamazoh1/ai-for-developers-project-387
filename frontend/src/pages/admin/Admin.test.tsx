import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { CreateEventType, EventType } from "../../api/types.gen.ts";
import { apiUrl, eventType } from "../../test/api.ts";
import { renderApp } from "../../test/render.tsx";
import { server } from "../../test/server.ts";

const LIST = apiUrl("/api/event-types");
const CREATE = apiUrl("/api/admin/event-types");

describe("admin area", () => {
  it("opens the upcoming meetings from /admin", async () => {
    renderApp("/admin");

    expect(await screen.findByText(/Предстоящих встреч нет/)).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Разделы админки" });
    expect(within(nav).getByRole("link", { name: "Предстоящие встречи" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Типы событий" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("switches between the two tabs", async () => {
    renderApp("/admin/bookings");

    const nav = screen.getByRole("navigation", { name: "Разделы админки" });
    await userEvent.click(within(nav).getByRole("link", { name: "Типы событий" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Типы событий" })).toBeVisible();
    expect(within(nav).getByRole("link", { name: "Типы событий" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Предстоящие встречи" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});

describe("event types page", () => {
  it("shows each event type as a card with duration, name, id and description", async () => {
    server.use(
      http.get(LIST, () =>
        HttpResponse.json([
          eventType({
            id: "code-review",
            name: "Разбор кода",
            description: "Совместный просмотр проекта",
            durationMinutes: 30,
          }),
          eventType({ id: "intro", name: "Знакомство", description: "", durationMinutes: 15 }),
        ]),
      ),
    );

    renderApp("/admin/event-types");

    const cards = await screen.findAllByRole("article");
    expect(cards.map((card) => card.textContent)).toEqual([
      "30 минРазбор кода/code-reviewСовместный просмотр проекта",
      "15 минЗнакомство/introБез описания",
    ]);
  });

  it("invites the owner to create the first type when there are none", async () => {
    renderApp("/admin/event-types");

    expect(
      await screen.findByText(
        "Типов событий пока нет. Создайте первый, чтобы гости могли записаться.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Создать тип" })).toHaveLength(2);
  });

  it("shows a skeleton while loading", async () => {
    renderApp("/admin/event-types");

    expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument();
    await screen.findByText(/Типов событий пока нет/);
    expect(screen.queryByRole("status", { name: "Загрузка" })).not.toBeInTheDocument();
  });

  it("offers a retry when the list cannot be loaded", async () => {
    server.use(
      http.get(LIST, () => HttpResponse.json({ code: "boom" }, { status: 500 }), { once: true }),
    );

    renderApp("/admin/event-types");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось загрузить данные. Попробуйте ещё раз",
    );
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText(/Типов событий пока нет/)).toBeInTheDocument();
  });
});

describe("creating an event type", () => {
  /** A fake backend that remembers created types, as the real one does. */
  function backendWithTypes(onCreate?: (body: CreateEventType) => void) {
    const stored: EventType[] = [];
    server.use(
      http.get(LIST, () => HttpResponse.json(stored)),
      http.post(CREATE, async ({ request }) => {
        const body = (await request.json()) as CreateEventType;
        onCreate?.(body);
        const created = eventType({ description: "", ...body });
        stored.push(created);
        return HttpResponse.json(created, { status: 201 });
      }),
    );
  }

  async function openForm() {
    await screen.findByText(/Типов событий пока нет/);
    await userEvent.click(screen.getAllByRole("button", { name: "Создать тип" })[0]);
    return screen.getByRole("dialog");
  }

  async function fill(
    dialog: HTMLElement,
    values: { name?: string; id?: string; description?: string; duration?: string },
  ) {
    const type = async (label: string, value: string | undefined) => {
      if (value === undefined) return;
      const input = within(dialog).getByLabelText(new RegExp(label));
      await userEvent.clear(input);
      if (value) await userEvent.type(input, value);
    };
    await type("Название", values.name);
    await type("Идентификатор", values.id);
    await type("Описание", values.description);
    await type("Длительность", values.duration);
  }

  it("saves the type, closes the form and shows the new card at once", async () => {
    let sent: CreateEventType | undefined;
    backendWithTypes((body) => (sent = body));
    renderApp("/admin/event-types");

    const dialog = await openForm();
    await fill(dialog, {
      name: "Консультация",
      id: "consultation",
      description: "Разбор вопроса",
      duration: "60",
    });
    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const card = await screen.findByRole("article");
    expect(card).toHaveTextContent("60 минКонсультация/consultationРазбор вопроса");
    expect(sent).toEqual({
      id: "consultation",
      name: "Консультация",
      description: "Разбор вопроса",
      durationMinutes: 60,
    });
  });

  it("starts from an empty form every time it is opened", async () => {
    backendWithTypes();
    renderApp("/admin/event-types");

    const first = await openForm();
    await fill(first, { name: "Знакомство", id: "intro", duration: "15" });
    await userEvent.click(within(first).getByRole("button", { name: "Создать тип события" }));
    await screen.findByRole("article");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Создать тип" }));

    const second = screen.getByRole("dialog");
    expect(within(second).getByLabelText(/Название/)).toHaveValue("");
    expect(within(second).getByLabelText(/Идентификатор/)).toHaveValue("");
  });

  it("shows the server's validation errors under the fields and keeps the form open", async () => {
    server.use(
      http.get(LIST, () => HttpResponse.json([])),
      http.post(CREATE, () =>
        HttpResponse.json(
          {
            code: "validation_error",
            message: "Request validation failed",
            fields: [
              { field: "id", message: "String should match pattern" },
              { field: "durationMinutes", message: "Input should be a multiple of 5" },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    renderApp("/admin/event-types");

    const dialog = await openForm();
    await fill(dialog, { name: "Звонок", id: "Bad Id", duration: "7" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    expect(await within(dialog).findByText(/Только строчные латинские буквы/)).toBeVisible();
    expect(within(dialog).getByText(/Целое число минут от 5 до 480, кратное 5/)).toBeVisible();
    expect(within(dialog).getByLabelText(/Идентификатор/)).toHaveValue("Bad Id");
    expect(within(dialog).getByLabelText(/Название/)).not.toBeInvalid();
    expect(within(dialog).getByLabelText(/Идентификатор/)).toBeInvalid();
  });

  it("says the id is taken when the server reports a duplicate", async () => {
    server.use(
      http.get(LIST, () => HttpResponse.json([])),
      http.post(CREATE, () =>
        HttpResponse.json(
          { code: "event_type_exists", message: "An event type with this id already exists" },
          { status: 409 },
        ),
      ),
    );
    renderApp("/admin/event-types");

    const dialog = await openForm();
    await fill(dialog, { name: "Звонок", id: "intro", duration: "30" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    expect(await within(dialog).findByText("Тип с таким id уже есть")).toBeVisible();
    expect(within(dialog).getByLabelText(/Идентификатор/)).toBeInvalid();
  });

  it.each([
    ["a server error", () => HttpResponse.json({ code: "boom" }, { status: 500 })],
    ["a network failure", () => HttpResponse.error()],
  ])("keeps the entered values and lets the owner retry after %s", async (_name, failure) => {
    backendWithTypes();
    server.use(http.post(CREATE, failure, { once: true }));
    renderApp("/admin/event-types");

    const dialog = await openForm();
    await fill(dialog, { name: "Знакомство", id: "intro", duration: "15" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Не удалось создать тип. Попробуйте ещё раз",
    );
    expect(within(dialog).getByLabelText(/Идентификатор/)).toHaveValue("intro");

    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    expect(await screen.findByRole("article")).toHaveTextContent("Знакомство");
  });

  it("asks to try again when the service is busy, keeping the entered values", async () => {
    backendWithTypes();
    server.use(
      http.post(
        CREATE,
        () => HttpResponse.json({ code: "service_busy", message: "busy" }, { status: 503 }),
        { once: true },
      ),
    );
    renderApp("/admin/event-types");

    const dialog = await openForm();
    await fill(dialog, { name: "Знакомство", id: "intro", duration: "15" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Сервис занят. Попробуйте ещё раз",
    );
    expect(within(dialog).getByLabelText(/Идентификатор/)).toHaveValue("intro");

    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    expect(await screen.findByRole("article")).toHaveTextContent("Знакомство");
  });

  it("disables the submit button while the request is running", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    backendWithTypes();
    server.use(
      http.post(CREATE, async () => {
        await gate;
        return HttpResponse.json(eventType(), { status: 201 });
      }),
    );
    renderApp("/admin/event-types");

    const dialog = await openForm();
    await fill(dialog, { name: "Знакомство", id: "intro", duration: "15" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Создать тип события" }));

    expect(within(dialog).getByRole("button", { name: "Создать тип события" })).toBeDisabled();
    release();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
