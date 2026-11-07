import { Badge, Button, List, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconArrowRight } from "@tabler/icons-react";
import { Link } from "react-router";
import classes from "./Landing.module.css";

const FEATURES = [
  "Звонки разной длительности на выбор.",
  "Свободные слоты на ближайшие две недели.",
  "Проверка конфликта при бронировании.",
];

export default function Landing() {
  return (
    <>
      <div className={classes.backdrop} aria-hidden />
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="xl" mt={{ base: 0, md: 24 }}>
        <Stack align="flex-start" gap="md">
          <Badge variant="white" size="lg">
            Быстрая запись на звонок
          </Badge>
          <Title order={1} fz={{ base: 36, md: 44 }}>
            Calendar
          </Title>
          <Text size="lg" c="dimmed">
            Один экран, понятные слоты, быстрая бронь. Выберите время и запишитесь на звонок без
            лишних шагов.
          </Text>
          <Button component={Link} to="/book" size="lg" rightSection={<IconArrowRight size={18} />}>
            Записаться
          </Button>
        </Stack>
        <Paper withBorder radius="lg" p="lg">
          <Title order={3} mb="sm">
            Что доступно прямо сейчас
          </Title>
          <List size="sm" c="dimmed" spacing="xs">
            {FEATURES.map((feature) => (
              <List.Item key={feature}>{feature}</List.Item>
            ))}
          </List>
        </Paper>
      </SimpleGrid>
    </>
  );
}
