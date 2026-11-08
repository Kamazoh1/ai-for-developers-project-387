import {
  Alert,
  Button,
  Group,
  Paper,
  Skeleton,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useState } from "react";
import { eventTypesApiSlots } from "../api/sdk.gen.ts";
import type { Booking, SlotDay } from "../api/types.gen.ts";
import { RequestBoundary } from "../request/RequestBoundary.tsx";
import { useRequest } from "../request/useRequest.ts";
import { BookingForm } from "./BookingForm.tsx";
import {
  asUtc,
  dayAndMonth,
  localTime,
  slotLabel,
  weekdayLong,
  weekdayShort,
} from "./calendarFormat.ts";

function DayButton({
  day,
  selected,
  onSelect,
}: {
  day: SlotDay;
  selected: boolean;
  onSelect: () => void;
}) {
  const date = asUtc(day.date);
  return (
    <Button
      variant={selected ? "filled" : "default"}
      disabled={day.slots.length === 0}
      aria-pressed={selected}
      aria-label={`${dayAndMonth.format(date)}, ${weekdayLong.format(date)}`}
      onClick={onSelect}
      h={56}
      px={4}
    >
      <Stack gap={0} align="center">
        <Text size="xs" tt="uppercase" inherit fw={400}>
          {weekdayShort.format(date)}
        </Text>
        <Text fw={700} fz="lg" lh={1.2} inherit>
          {date.getUTCDate()}
        </Text>
      </Stack>
    </Button>
  );
}

function SlotsSkeleton() {
  return (
    <SimpleGrid cols={{ base: 4, xs: 7 }} spacing="xs">
      {Array.from({ length: 14 }, (_, n) => (
        <Skeleton key={n} height={56} />
      ))}
    </SimpleGrid>
  );
}

const SLOT_LOST: Record<"taken" | "unavailable", string> = {
  taken: "Это время уже занято. Выберите другое",
  unavailable: "Время недоступно",
};

type WindowProps = {
  days: SlotDay[];
  zone: string;
  eventTypeId: string;
  selectedDate: string | null;
  onSelectDate: (date: string) => void;
  notice: string | null;
  topic: string;
  onTopicChange: (topic: string) => void;
  onBooked: (booking: Booking) => void;
  onSlotLost: (reason: "taken" | "unavailable") => void;
};

function Window({
  days,
  zone,
  eventTypeId,
  selectedDate,
  onSelectDate,
  notice,
  topic,
  onTopicChange,
  onBooked,
  onSlotLost,
}: WindowProps) {
  const [selectedStart, setSelectedStart] = useState<string | null>(null);
  const selected = days.find((day) => day.date === selectedDate);
  const chosen = selected?.slots.find((slot) => slot.start === selectedStart);

  const nothingFree = days.every((day) => day.slots.length === 0);

  return (
    <Stack>
      {notice && (
        <Alert color="yellow" role="alert">
          {notice}
        </Alert>
      )}
      <SimpleGrid cols={{ base: 4, xs: 7 }} spacing="xs" role="group" aria-label="Дни записи">
        {days.map((day) => (
          <DayButton
            key={day.date}
            day={day}
            selected={day.date === selectedDate}
            onSelect={() => {
              onSelectDate(day.date);
              setSelectedStart(null);
            }}
          />
        ))}
      </SimpleGrid>
      {selected ? (
        <Paper
          component="section"
          withBorder
          p="md"
          aria-label={`Свободное время, ${dayAndMonth.format(asUtc(selected.date))}`}
        >
          <Stack gap="sm">
            <Group justify="space-between" align="baseline">
              <Title order={2} size="h4">
                {`${dayAndMonth.format(asUtc(selected.date))}, ${weekdayLong.format(asUtc(selected.date))}`}
              </Title>
              <Text size="sm" c="dimmed">{`Время по ${zone}`}</Text>
            </Group>
            <SimpleGrid cols={{ base: 2, xs: 3, sm: 4 }} spacing="xs" component="ul" p={0} m={0}>
              {selected.slots.map((slot) => (
                <li key={slot.start} style={{ listStyle: "none" }}>
                  <Button
                    fullWidth
                    variant={slot.start === selectedStart ? "filled" : "default"}
                    aria-pressed={slot.start === selectedStart}
                    onClick={() => setSelectedStart(slot.start)}
                  >
                    {slotLabel(slot)}
                  </Button>
                </li>
              ))}
            </SimpleGrid>
            {chosen && (
              <BookingForm
                key={chosen.start}
                eventTypeId={eventTypeId}
                start={chosen.start}
                time={localTime(chosen.start)}
                topic={topic}
                onTopicChange={onTopicChange}
                onBooked={onBooked}
                onSlotLost={(reason) => {
                  setSelectedStart(null);
                  onSlotLost(reason);
                }}
              />
            )}
          </Stack>
        </Paper>
      ) : nothingFree ? (
        <Text c="dimmed">
          На ближайшие две недели свободного времени нет. Загляните позже или выберите другой тип
          звонка
        </Text>
      ) : (
        <Text c="dimmed">Выберите день, чтобы увидеть свободное время.</Text>
      )}
    </Stack>
  );
}

/**
 * The booking window of an event type: 14 days to choose from, the free slots of the chosen
 * one, and the booking form of the chosen slot. A slot that turns out taken or invalid sends
 * the guest back to the choice with a notice, and the slots are loaded again.
 */
export function SlotPicker({
  eventTypeId,
  zone,
  onBooked,
}: {
  eventTypeId: string;
  zone: string;
  onBooked: (booking: Booking) => void;
}) {
  const slots = useRequest(() => eventTypesApiSlots({ path: { id: eventTypeId } }), eventTypeId);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Kept here, not in the form: a slot lost to another guest must not cost the guest their text.
  const [topic, setTopic] = useState("");

  return (
    <RequestBoundary request={slots} skeleton={<SlotsSkeleton />}>
      {({ days }) => (
        <Window
          days={days}
          zone={zone}
          eventTypeId={eventTypeId}
          selectedDate={selectedDate}
          onSelectDate={(date) => {
            setSelectedDate(date);
            setNotice(null);
          }}
          notice={notice}
          topic={topic}
          onTopicChange={setTopic}
          onBooked={onBooked}
          onSlotLost={(reason) => {
            setNotice(SLOT_LOST[reason]);
            slots.reload();
          }}
        />
      )}
    </RequestBoundary>
  );
}
