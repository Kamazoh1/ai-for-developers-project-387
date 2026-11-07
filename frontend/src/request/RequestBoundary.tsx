import { Alert, Button, Skeleton, Stack } from "@mantine/core";
import type { ReactNode } from "react";
import type { RequestState } from "./useRequest.ts";

type Props<T> = {
  request: { state: RequestState<T>; reload: () => void };
  /** Replaces the default skeleton lines. */
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
};

/** Renders a skeleton while loading, the standard retry alert on failure, else `children`. */
export function RequestBoundary<T>({ request, skeleton, children }: Props<T>) {
  const { state, reload } = request;

  if (state.status === "loading") {
    return (
      <Stack role="status" aria-label="Загрузка" gap="xs">
        {skeleton ?? (
          <>
            <Skeleton height={20} width="40%" />
            <Skeleton height={20} width="60%" />
          </>
        )}
      </Stack>
    );
  }

  if (state.status === "error") {
    return (
      <Alert color="red" title="Не удалось загрузить данные. Попробуйте ещё раз">
        <Button variant="light" color="red" size="xs" onClick={reload}>
          Повторить
        </Button>
      </Alert>
    );
  }

  return <>{children(state.data)}</>;
}
