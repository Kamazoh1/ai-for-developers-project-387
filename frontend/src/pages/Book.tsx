import { Group, Paper, Skeleton, Stack, Text, Title } from "@mantine/core";
import { IconArrowRight } from "@tabler/icons-react";
import { Link } from "react-router";
import { calendarApiGet, eventTypesApiList } from "../api/sdk.gen.ts";
import type { EventType } from "../api/types.gen.ts";
import { RequestBoundary } from "../request/RequestBoundary.tsx";
import { useRequest } from "../request/useRequest.ts";
import classes from "./Book.module.css";

function EventTypeRow({ eventType }: { eventType: EventType }) {
  return (
    <Paper
      component={Link}
      to={`/book/${eventType.id}`}
      withBorder
      radius="md"
      p="md"
      className={classes.row}
    >
      <Group wrap="nowrap" gap="lg">
        <Stack gap={0} align="center" w={64} className={classes.minutes}>
          <Text fz={28} fw={700} lh={1} c="brand">
            {eventType.durationMinutes}
          </Text>
          <Text size="xs" c="dimmed">
            минут
          </Text>
        </Stack>
        <Stack gap={2} className={classes.text}>
          <Text fw={600}>{eventType.name}</Text>
          <Text size="sm" c="dimmed" truncate>
            {eventType.description || "Без описания"}
          </Text>
        </Stack>
        <IconArrowRight size={18} aria-hidden />
      </Group>
    </Paper>
  );
}

function RowsSkeleton() {
  return (
    <>
      <Skeleton height={76} radius="md" />
      <Skeleton height={76} radius="md" />
    </>
  );
}

export default function Book() {
  const calendar = useRequest(() => calendarApiGet());
  const eventTypes = useRequest(() => eventTypesApiList());

  return (
    <Stack>
      <Title order={1}>Запись на звонок</Title>
      <RequestBoundary request={calendar}>
        {(settings) => <Text>{`Запись к: ${settings.owner.name}`}</Text>}
      </RequestBoundary>
      <RequestBoundary request={eventTypes} skeleton={<RowsSkeleton />}>
        {(types) =>
          types.length === 0 ? (
            <Paper withBorder radius="lg" p="xl">
              <Text c="dimmed" ta="center">
                Владелец пока не добавил типы звонков. Загляните позже.
              </Text>
            </Paper>
          ) : (
            <Stack gap="xs">
              {types.map((type) => (
                <EventTypeRow key={type.id} eventType={type} />
              ))}
            </Stack>
          )
        }
      </RequestBoundary>
    </Stack>
  );
}
