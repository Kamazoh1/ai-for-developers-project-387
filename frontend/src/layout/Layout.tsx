import { AppShell, Container } from "@mantine/core";
import { Outlet } from "react-router";
import Header from "./Header.tsx";

export default function Layout() {
  return (
    <AppShell header={{ height: 60 }}>
      <AppShell.Header>
        <Header />
      </AppShell.Header>
      <AppShell.Main>
        <Container size="lg" py="xl">
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
