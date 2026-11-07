import { Button, Card, Group, Modal, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconPlus } from "@tabler/icons-react";
import { eventTypesApiList } from "../../api/sdk.gen.ts";
import type { EventType } from "../../api/types.gen.ts";
import { RequestBoundary } from "../../request/RequestBoundary.tsx";
import { useRequest } from "../../request/useRequest.ts";
import EventTypeForm from "./EventTypeForm.tsx";

function EventTypeCard({ eventType }: { eventType: EventType }) {
  return (
    <Card component="article" withBorder radius="lg" padding="lg">
      <Text fz={32} fw={700} c="brand" lh={1}>
        {eventType.durationMinutes}
        <Text span size="sm" c="dimmed">
          {" мин"}
        </Text>
      </Text>
      <Text fw={600} mt="xs">
        {eventType.name}
      </Text>
      <Text size="xs" c="dimmed">
        {`/${eventType.id}`}
      </Text>
      <Text size="sm" c="dimmed" mt="xs" lineClamp={3}>
        {eventType.description || "Без описания"}
      </Text>
    </Card>
  );
}

export default function AdminEventTypes() {
  const eventTypes = useRequest(() => eventTypesApiList());
  const [opened, { open, close }] = useDisclosure(false);

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Типы событий</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={open}>
          Создать тип
        </Button>
      </Group>
      <RequestBoundary request={eventTypes}>
        {(types) =>
          types.length === 0 ? (
            <Paper withBorder radius="lg" p="xl">
              <Stack align="center" gap="sm">
                <Text c="dimmed" ta="center">
                  Типов событий пока нет. Создайте первый, чтобы гости могли записаться.
                </Text>
                <Button variant="light" onClick={open}>
                  Создать тип
                </Button>
              </Stack>
            </Paper>
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
              {types.map((type) => (
                <EventTypeCard key={type.id} eventType={type} />
              ))}
            </SimpleGrid>
          )
        }
      </RequestBoundary>
      <Modal opened={opened} onClose={close} title="Новый тип события">
        <EventTypeForm
          onCreated={() => {
            close();
            eventTypes.reload();
          }}
        />
      </Modal>
    </Stack>
  );
}
