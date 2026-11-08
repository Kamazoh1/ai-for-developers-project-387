import { Alert, Button, Stack, TextInput } from "@mantine/core";
import { type SubmitEvent, useState } from "react";
import { bookingsApiCreate } from "../api/sdk.gen.ts";
import type { Booking, CreateBooking } from "../api/types.gen.ts";

/** Russian rule per request field, shown under the input when the server rejects it. */
const FIELD_RULES: Record<string, string> = {
  guestName: "От 1 до 100 символов",
  guestEmail: "Введите email в формате name@example.com, не длиннее 50 символов",
  topic: "Не длиннее 500 символов",
};

type Errors = Partial<Record<string, string>>;

type Outcome =
  | { kind: "booked"; booking: Booking }
  | { kind: "invalid"; errors: Errors }
  | { kind: "taken" }
  | { kind: "unavailable" }
  | { kind: "busy" }
  | { kind: "failed" };

/**
 * Outcome of the booking call, read straight from the SDK result: the SDK does not throw
 * on error responses, and `useRequest` only covers GETs. A network failure rejects.
 */
async function book(body: CreateBooking): Promise<Outcome> {
  try {
    const result = await bookingsApiCreate({ body });
    if (result.data) return { kind: "booked", booking: result.data };
    const error = result.error;
    if (error?.code === "validation_error") {
      const errors: Errors = {};
      for (const { field } of error.fields) {
        if (field in FIELD_RULES) errors[field] = FIELD_RULES[field];
      }
      // Rejected fields the form does not show (the slot, the type) leave nothing to point at:
      // that is a failure of the request, not of what the guest typed.
      if (Object.keys(errors).length > 0) return { kind: "invalid", errors };
    }
    if (error?.code === "slot_taken") return { kind: "taken" };
    if (error?.code === "invalid_slot") return { kind: "unavailable" };
    if (error?.code === "service_busy") return { kind: "busy" };
  } catch {
    // fall through: handled like any other failure
  }
  return { kind: "failed" };
}

type Props = {
  eventTypeId: string;
  /** Start of the chosen slot, an RFC 3339 instant. */
  start: string;
  /** Local start time, e.g. `09:00`, for the form's name. */
  time: string;
  onBooked: (booking: Booking) => void;
  /** The slot cannot be booked any more (`taken` or `unavailable`): choose another. */
  onSlotLost: (reason: "taken" | "unavailable") => void;
};

/** Name and email of the guest for one chosen slot. */
export function BookingForm({ eventTypeId, start, time, onBooked, onSlotLost }: Props) {
  const [guestName, setGuestName] = useState("");
  const [guestEmail, setGuestEmail] = useState("");
  const [topic, setTopic] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setErrors({});
    setNotice(null);
    const outcome = await book({ eventTypeId, start, guestName, guestEmail, topic });
    setPending(false);
    switch (outcome.kind) {
      case "booked":
        return onBooked(outcome.booking);
      case "taken":
      case "unavailable":
        return onSlotLost(outcome.kind);
      case "invalid":
        return setErrors(outcome.errors);
      case "busy":
        return setNotice("Сервис занят. Попробуйте ещё раз");
      case "failed":
        return setNotice("Не удалось записаться. Попробуйте ещё раз");
    }
  };

  return (
    <form onSubmit={submit} noValidate aria-label={`Запись на ${time}`}>
      <Stack gap="sm">
        {notice && (
          <Alert color="red" role="alert">
            {notice}
          </Alert>
        )}
        <TextInput
          label="Имя"
          autoComplete="name"
          value={guestName}
          onChange={(e) => setGuestName(e.currentTarget.value)}
          error={errors.guestName}
        />
        <TextInput
          label="Email"
          type="email"
          autoComplete="email"
          value={guestEmail}
          onChange={(e) => setGuestEmail(e.currentTarget.value)}
          error={errors.guestEmail}
        />
        <TextInput
          label="Тема (необязательно)"
          value={topic}
          onChange={(e) => setTopic(e.currentTarget.value)}
          error={errors.topic}
        />
        <Button type="submit" loading={pending}>
          Записаться
        </Button>
      </Stack>
    </form>
  );
}
