import type { Slot } from "../api/types.gen.ts";

// Days are plain dates ("2026-11-06"); format them as UTC so the guest's zone cannot shift them.
export const weekdayShort = new Intl.DateTimeFormat("ru-RU", {
  weekday: "short",
  timeZone: "UTC",
});
export const dayAndMonth = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
  timeZone: "UTC",
});
export const weekdayLong = new Intl.DateTimeFormat("ru-RU", {
  weekday: "long",
  timeZone: "UTC",
});

export const asUtc = (date: string) => new Date(`${date}T00:00:00Z`);

// Browsers disagree on Russian zone abbreviations (`МСК`, `MSK` or `GMT+3`), so name them ourselves.
const RUSSIAN_ZONES: Record<string, string> = {
  "Europe/Kaliningrad": "МСК−1",
  "Europe/Moscow": "МСК",
  "Europe/Samara": "МСК+1",
  "Asia/Yekaterinburg": "МСК+2",
  "Asia/Omsk": "МСК+3",
  "Asia/Krasnoyarsk": "МСК+4",
  "Asia/Irkutsk": "МСК+5",
  "Asia/Yakutsk": "МСК+6",
  "Asia/Vladivostok": "МСК+7",
  "Asia/Magadan": "МСК+8",
  "Asia/Kamchatka": "МСК+9",
};

/** Short label of the calendar timezone: `МСК` for Moscow, else the browser's name (`GMT+9`). */
export function zoneLabel(timeZone: string): string {
  const known = RUSSIAN_ZONES[timeZone];
  if (known) return known;
  const parts = new Intl.DateTimeFormat("ru-RU", {
    timeZone,
    timeZoneName: "short",
  }).formatToParts(new Date());
  return parts.find((part) => part.type === "timeZoneName")?.value ?? timeZone;
}

/** `09:00` out of `2026-11-06T09:00:00+03:00`: slots arrive in the calendar zone's offset. */
export const localTime = (instant: string) => instant.slice(11, 16);

export const slotLabel = (slot: Slot) => `${localTime(slot.start)} – ${localTime(slot.end)}`;
