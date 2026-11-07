import { useCallback, useEffect, useEffectEvent, useState } from "react";
import { client } from "../api/client.gen.ts";

// The API address is configurable. Empty means same-origin `/api`, which the Vite dev
// server proxies to the backend (vite.config.ts); set VITE_API_URL to call another host.
client.setConfig({ baseUrl: import.meta.env.VITE_API_URL ?? "" });

export type RequestState<T> =
  | { status: "loading" }
  | { status: "error" }
  | { status: "success"; data: T };

/** What every generated SDK call resolves to (they run with `throwOnError: false`). */
type SdkResult<T> = Promise<{ data?: T; error?: unknown }>;

/**
 * Runs a generated SDK call on mount and again whenever `key` changes; `reload` runs it
 * again on demand. A network failure or an error response both end in the `error` state.
 * Pass whatever the call depends on (an id, say) as `key`.
 *
 *     const calendar = useRequest(() => calendarApiGet());
 *     const slots = useRequest(() => eventTypesSlots({ path: { id } }), id);
 */
export function useRequest<T>(
  call: () => SdkResult<T>,
  key: string | number = "",
): { state: RequestState<T>; reload: () => void } {
  const [attempt, setAttempt] = useState(0);
  // The outcome is stored with the request it belongs to; any other request is "loading".
  const [settled, setSettled] = useState<{ token: string; state: RequestState<T> } | null>(null);
  const token = `${key}:${attempt}`;
  const run = useEffectEvent(call);

  useEffect(() => {
    let current = true;
    const settle = (state: RequestState<T>) => current && setSettled({ token, state });
    run().then(
      (result) =>
        settle(
          result.error === undefined && result.data !== undefined
            ? { status: "success", data: result.data }
            : { status: "error" },
        ),
      () => settle({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, [token]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const state: RequestState<T> = settled?.token === token ? settled.state : { status: "loading" };
  return { state, reload };
}
