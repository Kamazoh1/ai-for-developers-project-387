import type { Booking, CalendarSettings, EventType, Slots } from "../api/types.gen.ts";

/** Base URL the app talks to in tests (see `test.env` in vite.config.ts). */
const API_URL = import.meta.env.VITE_API_URL;

/** Absolute URL of an API path, for msw handlers: `http.get(apiUrl("/api/calendar"), ...)`. */
export function apiUrl(path: string): string {
  return `${API_URL}${path}`;
}

/** Contract-shaped fixtures. Each takes overrides: `calendar({ owner: { name: "Анна" } })`. */
export function calendar(overrides: Partial<CalendarSettings> = {}): CalendarSettings {
  return {
    timezone: "Europe/Moscow",
    workingHours: { start: "09:00:00", end: "18:00:00" },
    slotStepMinutes: 30,
    bookingWindowDays: 14,
    owner: { name: "Алексей Иванов" },
    ...overrides,
  };
}

export function eventType(overrides: Partial<EventType> = {}): EventType {
  return {
    id: "intro-call",
    name: "Знакомство",
    description: "Короткий созвон",
    durationMinutes: 15,
    ...overrides,
  };
}

/** First day of the fixture booking window (a Thursday); see `slotWindow`. */
export const WINDOW_START = "2026-11-05";

/** A slot's start and end as local times, e.g. `["09:00", "09:30"]`. */
export type SlotTimes = [start: string, end: string];

/**
 * A booking window of 14 days from `WINDOW_START`, Moscow time (+03:00). Days not listed
 * in `freeByDate` are empty: `slotWindow({ "2026-11-06": [["09:00", "09:30"]] })`.
 */
export function slotWindow(freeByDate: Record<string, SlotTimes[]> = {}): Slots {
  const first = new Date(`${WINDOW_START}T00:00:00Z`);
  const days = Array.from({ length: 14 }, (_, n) => {
    const date = new Date(first.getTime() + n * 86_400_000).toISOString().slice(0, 10);
    const slots = (freeByDate[date] ?? []).map(([start, end]) => ({
      start: `${date}T${start}:00+03:00`,
      end: `${date}T${end}:00+03:00`,
    }));
    return { date, slots };
  });
  return { days };
}

/** A confirmed booking; the defaults match the first fixture slot (`slotWindow`, 06 Nov 09:00-09:30). */
export function booking(overrides: Partial<Booking> = {}): Booking {
  return {
    id: 1,
    eventTypeId: "intro-call",
    start: "2026-11-06T09:00:00+03:00",
    end: "2026-11-06T09:30:00+03:00",
    guestName: "Мария",
    guestEmail: "maria@example.com",
    topic: "",
    createdAt: "2026-11-05T10:00:00+03:00",
    ...overrides,
  };
}
