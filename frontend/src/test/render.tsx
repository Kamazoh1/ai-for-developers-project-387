import { MantineProvider } from "@mantine/core";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import App from "../App.tsx";
import HistoryButtons from "./HistoryButtons.tsx";

/** Seam 2: the whole `<App />` in an in-memory router; the network is faked by msw. */
export function renderApp(path = "/") {
  return render(
    <MantineProvider env="test">
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </MantineProvider>,
  );
}

/**
 * Like `renderApp`, but with a browser-like history: `entries` are the visited addresses, the
 * app opens at `index`, and the "history back" / "history forward" buttons play the browser's
 * Back and Forward, which keep React Router's route instances alive.
 */
export function renderAppWithHistory(entries: string[], index: number) {
  return render(
    <MantineProvider env="test">
      <MemoryRouter initialEntries={entries} initialIndex={index}>
        <HistoryButtons />
        <App />
      </MemoryRouter>
    </MantineProvider>,
  );
}
