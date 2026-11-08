import { Badge, Group, Paper, Skeleton, Stack, Text, Title } from "@mantine/core";
import { adminBookingsApiList, calendarApiGet, eventTypesApiList } from "../../api/sdk.gen.ts";
import type { Booking, EventType } from "../../api/types.gen.ts";
import { RequestBoundary } from "../../request/RequestBoundary.tsx";
import { useRequest } from "../../request/useRequest.ts";
import { asUtc, dayAndMonth, localTime, weekdayLong, zoneLabel } from "../calendarFormat.ts";

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

const minutesBetween = (booking: Booking) =>
  (new Date(booking.end).getTime() - new Date(booking.start).getTime()) / 60_000;

function BookingCard({
  booking,
  typeName,
  zone,
  nearest,
}: {
  booking: Booking;
  typeName: string;
  zone: string;
  nearest: boolean;
}) {
  // Instants arrive in the calendar zone's offset, so the date and times are read off the text.
  const day = asUtc(booking.start.slice(0, 10));
  return (
    <Paper
      component="article"
      withBorder
      radius="md"
      p="md"
      style={{
        borderLeft: `4px solid var(--mantine-color-brand-${nearest ? 5 : 2})`,
      }}
    >
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
        <Stack gap={2} miw={0} style={{ overflowWrap: "anywhere" }}>
          <Text fw={700}>{`${dayAndMonth.format(day)}, ${weekdayLong.format(day)}`}</Text>
          <Text fw={700}>{`${localTime(booking.start)} – ${localTime(booking.end)} ${zone}`}</Text>
          <Text>{booking.guestName}</Text>
          <Text size="sm" c="dimmed">
            {booking.guestEmail}
          </Text>
          {booking.topic && (
            <Text size="sm" style={{ overflowWrap: "anywhere", whiteSpace: "pre-line" }}>
              {`Тема: ${booking.topic}`}
            </Text>
          )}
        </Stack>
        <Stack gap={4} align="flex-end">
          <Badge variant="light">{typeName}</Badge>
          <Text size="xs" c="dimmed">
            {formatDuration(minutesBetween(booking))}
          </Text>
          {nearest && (
            <Badge color="green" variant="dot">
              Ближайшая
            </Badge>
          )}
        </Stack>
      </Group>
    </Paper>
  );
}

function BookingsSkeleton() {
  return (
    <>
      {[0, 1, 2].map((n) => (
        <Skeleton key={n} height={104} radius="md" />
      ))}
    </>
  );
}

/** `/admin/bookings`: the upcoming meetings of all event types, nearest first and highlighted. */
export default function AdminBookings() {
  // One request for the three things the page needs, so it has one skeleton and one retry.
  const page = useRequest(async () => {
    const [bookings, eventTypes, calendar] = await Promise.all([
      adminBookingsApiList(),
      eventTypesApiList(),
      calendarApiGet(),
    ]);
    if (!bookings.data || !eventTypes.data || !calendar.data) return { error: true };
    return {
      data: { bookings: bookings.data, eventTypes: eventTypes.data, calendar: calendar.data },
    };
  });

  return (
    <Stack>
      <Title order={2}>Предстоящие встречи</Title>
      <RequestBoundary request={page} skeleton={<BookingsSkeleton />}>
        {({ bookings, eventTypes, calendar }) => {
          if (bookings.length === 0) {
            return (
              <Paper withBorder radius="lg" p="xl">
                <Text c="dimmed" ta="center">
                  Предстоящих встреч нет. Когда гость запишется, встреча появится здесь.
                </Text>
              </Paper>
            );
          }
          const names = new Map(eventTypes.map((type: EventType) => [type.id, type.name]));
          const zone = zoneLabel(calendar.timezone);
          return bookings.map((booking, index) => (
            <BookingCard
              key={booking.id}
              booking={booking}
              typeName={names.get(booking.eventTypeId) ?? booking.eventTypeId}
              zone={zone}
              nearest={index === 0}
            />
          ));
        }}
      </RequestBoundary>
    </Stack>
  );
}
