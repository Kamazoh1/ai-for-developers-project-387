import { Anchor, Badge, Paper, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { calendarApiGet, eventTypesApiGet } from "../api/sdk.gen.ts";
import type { Booking, EventType } from "../api/types.gen.ts";
import { RequestBoundary } from "../request/RequestBoundary.tsx";
import { useRequest } from "../request/useRequest.ts";
import { asUtc, dayAndMonth, localTime, weekdayLong, zoneLabel } from "./calendarFormat.ts";
import { SlotPicker } from "./SlotPicker.tsx";

function BackToTypes() {
  return (
    <Anchor component={Link} to="/book" w="fit-content">
      <IconArrowLeft size={14} aria-hidden /> К выбору типа
    </Anchor>
  );
}

function Confirmation({
  booking,
  type,
  zone,
  owner,
}: {
  booking: Booking;
  type: EventType;
  zone: string;
  owner: string;
}) {
  // The booking arrives in the calendar zone's offset, so its date is the first 10 characters.
  const day = asUtc(booking.start.slice(0, 10));
  return (
    <Paper component="section" withBorder p="md" aria-label="Запись подтверждена">
      <Stack gap="xs">
        <Title order={2} size="h4">
          Запись подтверждена
        </Title>
        <Text fw={700}>{type.name}</Text>
        <Text>{`${dayAndMonth.format(day)}, ${weekdayLong.format(day)}`}</Text>
        <Text>{`${localTime(booking.start)} – ${localTime(booking.end)} ${zone}`}</Text>
        <Text c="dimmed">{`Вы записаны к: ${owner}`}</Text>
        <Text c="dimmed">{`${booking.guestName}, ${booking.guestEmail}`}</Text>
        {booking.topic && (
          <Text style={{ overflowWrap: "anywhere", whiteSpace: "pre-line" }}>
            {`Тема: ${booking.topic}`}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

/** `/book/:eventTypeId`: the type the guest chose, its 14-day window, free slots and booking form. */
export default function BookEventType() {
  const { eventTypeId = "" } = useParams();
  // React Router reuses this route's instance when only the id changes (Back, Forward, an edited
  // address); the key gives every event type its own state, so a confirmation never leaks across.
  return <EventTypeBooking key={eventTypeId} eventTypeId={eventTypeId} />;
}

function EventTypeBooking({ eventTypeId }: { eventTypeId: string }) {
  // An unknown id is an answer, not a failure: it resolves to `null`; anything else wrong is an error.
  const eventType = useRequest(async () => {
    const result = await eventTypesApiGet({ path: { id: eventTypeId } });
    return result.response?.status === 404 ? { data: null } : result;
  }, eventTypeId);
  const calendar = useRequest(() => calendarApiGet());
  // Once booked, the confirmation replaces the slots at the same address.
  const [booked, setBooked] = useState<Booking | null>(null);

  return (
    <Stack>
      <RequestBoundary request={eventType}>
        {(type) =>
          type === null ? (
            <>
              <Title order={1}>Тип события не найден</Title>
              <BackToTypes />
            </>
          ) : (
            <>
              <Title order={1}>{type.name}</Title>
              <Badge variant="light" w="fit-content">
                {`${type.durationMinutes} минут`}
              </Badge>
              {type.description && <Text c="dimmed">{type.description}</Text>}
              <RequestBoundary request={calendar}>
                {(settings) =>
                  booked ? (
                    <Confirmation
                      booking={booked}
                      type={type}
                      zone={zoneLabel(settings.timezone)}
                      owner={settings.owner.name}
                    />
                  ) : (
                    <SlotPicker
                      eventTypeId={type.id}
                      zone={zoneLabel(settings.timezone)}
                      onBooked={setBooked}
                    />
                  )
                }
              </RequestBoundary>
              <BackToTypes />
            </>
          )
        }
      </RequestBoundary>
    </Stack>
  );
}
