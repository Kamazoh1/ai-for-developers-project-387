import { http, HttpResponse } from "msw";
import { apiUrl, booking, calendar, slotWindow } from "./api.ts";

/**
 * Happy-path defaults for every endpoint the app calls. A test overrides what it
 * cares about with `server.use(...)`; add a default here when a new endpoint ships.
 */
export const handlers = [
  http.get(apiUrl("/api/calendar"), () => HttpResponse.json(calendar())),
  http.get(apiUrl("/api/event-types"), () => HttpResponse.json([])),
  http.get(apiUrl("/api/admin/bookings"), () => HttpResponse.json([])),
  http.get(apiUrl("/api/event-types/:id/slots"), () =>
    HttpResponse.json(slotWindow({ "2026-11-06": [["09:00", "09:30"]] })),
  ),
  http.post(apiUrl("/api/bookings"), async ({ request }) => {
    const body = (await request.json()) as {
      eventTypeId: string;
      start: string;
      guestName: string;
      guestEmail: string;
      topic?: string;
    };
    return HttpResponse.json(booking({ ...body, topic: body.topic ?? "" }), { status: 201 });
  }),
];
