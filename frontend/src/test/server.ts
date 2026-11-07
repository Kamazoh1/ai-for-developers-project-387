import { setupServer } from "msw/node";
import { handlers } from "./handlers.ts";

/** The fake network, started and reset around every test by `setup.ts`. */
export const server = setupServer(...handlers);
