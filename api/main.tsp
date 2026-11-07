import "@typespec/http";

using TypeSpec.Http;

@service(#{ title: "Call Calendar" })
@server("http://localhost:8000", "Local development")
namespace CallCalendar;

model Health {
  status: "ok";
}

@route("/health")
interface Status {
  @get check(): Health;
}

model WorkingHours {
  /** Start of the owner's working day, in the calendar timezone. */
  start: plainTime;

  /** End of the owner's working day, in the calendar timezone. */
  end: plainTime;
}

model Owner {
  /** Display name of the calendar owner. */
  name: string;
}

/** Read-only calendar settings and the owner's profile. */
model CalendarSettings {
  /** IANA name of the calendar timezone, e.g. Europe/Moscow. */
  timezone: string;

  workingHours: WorkingHours;

  /** Step between allowed slot start times, in minutes. */
  slotStepMinutes: int32;

  /** Number of calendar days, starting today, in which slots can be booked. */
  bookingWindowDays: int32;

  owner: Owner;
}

@route("/api/calendar")
interface CalendarApi {
  @get get(): CalendarSettings;
}

// --- error model -----------------------------------------------------------
// Every error response is `{ code, message, fields? }`: `code` is the stable machine
// value the UI turns into Russian text, `message` is short English for developers.

model FieldError {
  /** Name of the offending request field, as it appears in the request body. */
  field: string;

  message: string;
}

/** The request body is malformed or breaks a field rule. */
@error
model ValidationError {
  @statusCode _: 422;
  code: "validation_error";
  message: string;

  /** One entry per invalid field. */
  fields: FieldError[];
}

/** An event type with this id already exists. */
@error
model EventTypeExists {
  @statusCode _: 409;
  code: "event_type_exists";
  message: string;
}

/** No event type has this id. */
@error
model EventTypeNotFound {
  @statusCode _: 404;
  code: "event_type_not_found";
  message: string;
}

/** The requested slot is not a valid, still bookable start: off the grid, outside working hours or the booking window, already started, or of an unknown event type. */
@error
model InvalidSlot {
  @statusCode _: 422;
  code: "invalid_slot";
  message: string;
}

/** The requested interval overlaps an existing booking, of any event type. */
@error
model SlotTaken {
  @statusCode _: 409;
  code: "slot_taken";
  message: string;
}

/** The database write lock was not free within 30 seconds (ADR 0002); the request changed nothing and can be retried. */
@error
model ServiceBusy {
  @statusCode _: 503;
  code: "service_busy";
  message: string;
}

// --- event types -----------------------------------------------------------

/** A kind of call the owner offers. */
model EventType {
  /** Owner-chosen slug; the type's only identifier (ADR 0003). */
  id: string;

  name: string;

  /** Empty when the owner gave none. */
  description: string;

  /** Length of the call, and of its slots, in minutes. */
  durationMinutes: int32;
}

model CreateEventType {
  /** Lowercase letters, numbers and hyphens, 1-40 characters. Uppercase is rejected, not normalized. */
  @minLength(1)
  @maxLength(40)
  @pattern("^[a-z0-9-]+$")
  id: string;

  @minLength(1)
  @maxLength(100)
  name: string;

  @maxLength(500)
  description?: string;

  /** Whole minutes, 5-480, a multiple of 5. */
  @minValue(5)
  @maxValue(480)
  durationMinutes: int32;
}

// --- slots -----------------------------------------------------------------

/** A free interval of one event type, as long as that type's duration. */
model Slot {
  /** Start instant, RFC 3339 with the calendar timezone's offset. Always on the 30-minute grid. */
  start: offsetDateTime;

  /** End instant, RFC 3339 with the calendar timezone's offset. Never later than the end of working hours. */
  end: offsetDateTime;
}

/** One calendar day of the booking window. */
model SlotDay {
  /** The day's local date in the calendar timezone. */
  date: plainDate;

  /** Free slots of this day in ascending order; empty when the day has none. */
  slots: Slot[];
}

/** The booking window of one event type. */
model Slots {
  /** One entry per day of the booking window, today first; days without free slots are included. */
  days: SlotDay[];
}

@route("/api/event-types")
interface EventTypesApi {
  /** All event types, in creation order. */
  @get list(): EventType[];

  /** One event type by its id. */
  @get get(@path id: string): EventType | EventTypeNotFound;

  /** Free slots of the event type for each day of the booking window. */
  @route("/{id}/slots")
  @get slots(@path id: string): Slots | EventTypeNotFound;
}

@route("/api/admin/event-types")
interface AdminEventTypesApi {
  /** Create an event type. `503 service_busy` if the write lock times out; nothing was created and the request can be retried. */
  @post create(@body body: CreateEventType):
    | {
        @statusCode _: 201;
        @body body: EventType;
      }
    | ValidationError
    | EventTypeExists
    | ServiceBusy;
}

// --- bookings --------------------------------------------------------------

/** A taken interval `[start, end)` of one event type and the guest who took it. */
model Booking {
  /** Assigned by the server. */
  id: int32;

  eventTypeId: string;

  /** Start instant, RFC 3339 with the calendar timezone's offset. */
  start: offsetDateTime;

  /** End instant, computed by the server from the event type's duration. */
  end: offsetDateTime;

  guestName: string;
  guestEmail: string;

  /** When the booking was made, RFC 3339 with the calendar timezone's offset. */
  createdAt: offsetDateTime;
}

model CreateBooking {
  eventTypeId: string;

  /** Any RFC 3339 offset is accepted and compared as an instant; it must equal the start of a free slot of the event type. */
  start: offsetDateTime;

  /** 1-100 characters after trimming surrounding whitespace. */
  @minLength(1)
  @maxLength(100)
  guestName: string;

  /** 1-50 characters after trimming surrounding whitespace, and a valid email address. */
  @minLength(1)
  @maxLength(50)
  guestEmail: string;
}

@route("/api/bookings")
interface BookingsApi {
  /** Book a free slot. The server checks the slot (`422 invalid_slot`) before overlaps (`409 slot_taken`); `503 service_busy` if the write lock times out. */
  @post create(@body body: CreateBooking):
    | {
        @statusCode _: 201;
        @body body: Booking;
      }
    | ValidationError
    | InvalidSlot
    | SlotTaken
    | ServiceBusy;
}

@route("/api/admin/bookings")
interface AdminBookingsApi {
  /** Upcoming bookings of all event types, earliest start first: those that end later than now, so a meeting in progress is still listed. No pagination. */
  @get list(): Booking[];
}
