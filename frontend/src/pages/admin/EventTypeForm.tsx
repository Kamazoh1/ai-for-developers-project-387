import { Alert, Button, NumberInput, Stack, TextInput, Textarea } from "@mantine/core";
import { type SubmitEvent, useState } from "react";
import { adminEventTypesApiCreate } from "../../api/sdk.gen.ts";

/** Russian rule per request field, shown under the input when the server rejects it. */
const FIELD_RULES: Record<string, string> = {
  id: "Только строчные латинские буквы, цифры и дефис, от 1 до 40 символов",
  name: "От 1 до 100 символов",
  description: "Не больше 500 символов",
  durationMinutes: "Целое число минут от 5 до 480, кратное 5",
};

type Errors = Partial<Record<string, string>>;

/**
 * Outcome of the create call, read straight from the SDK result: the SDK does not throw
 * on error responses, and `useRequest` only covers GETs. A network failure rejects.
 */
type Outcome = { ok: true } | { ok: false; errors: Errors; notice?: string };

async function create(
  body: Parameters<typeof adminEventTypesApiCreate>[0]["body"],
): Promise<Outcome> {
  try {
    const result = await adminEventTypesApiCreate({ body });
    if (result.data) return { ok: true as const };
    const error = result.error;
    if (error?.code === "validation_error") {
      const errors: Errors = {};
      for (const { field } of error.fields)
        errors[field] = FIELD_RULES[field] ?? "Неверное значение";
      return { ok: false as const, errors };
    }
    if (error?.code === "event_type_exists") {
      return { ok: false as const, errors: { id: "Тип с таким id уже есть" } };
    }
    if (error?.code === "service_busy") {
      return { ok: false as const, errors: {}, notice: "Сервис занят. Попробуйте ещё раз" };
    }
  } catch {
    // fall through: handled like any other failure
  }
  return { ok: false as const, errors: {}, notice: "Не удалось создать тип. Попробуйте ещё раз" };
}

export default function EventTypeForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [description, setDescription] = useState("");
  const [duration, setDuration] = useState<number | string>(30);
  const [errors, setErrors] = useState<Errors>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setErrors({});
    setNotice(null);
    const outcome = await create({
      id,
      name,
      description,
      durationMinutes: Number(duration),
    });
    setPending(false);
    if (outcome.ok) {
      onCreated();
    } else {
      setErrors(outcome.errors);
      setNotice(outcome.notice ?? null);
    }
  };

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        {notice && (
          <Alert color="red" role="alert">
            {notice}
          </Alert>
        )}
        <TextInput
          label="Название"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          error={errors.name}
        />
        <TextInput
          label="Идентификатор (slug)"
          description="Попадёт в адрес: /book/ваш-id. Изменить его потом нельзя"
          placeholder="intro-call"
          value={id}
          onChange={(e) => setId(e.currentTarget.value)}
          error={errors.id}
        />
        <Textarea
          label="Описание"
          autosize
          minRows={2}
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          error={errors.description}
        />
        <NumberInput
          label="Длительность, минут"
          step={5}
          value={duration}
          onChange={setDuration}
          error={errors.durationMinutes}
        />
        <Button type="submit" loading={pending}>
          Создать тип события
        </Button>
      </Stack>
    </form>
  );
}
