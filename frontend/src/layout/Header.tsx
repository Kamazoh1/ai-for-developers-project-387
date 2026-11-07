import { Container, Group } from "@mantine/core";
import { IconCalendarClock } from "@tabler/icons-react";
import { Link, NavLink } from "react-router";
import classes from "./Header.module.css";

export default function Header() {
  return (
    <Container size="lg" h="100%">
      <Group h="100%" justify="space-between" wrap="nowrap">
        <Link to="/" className={classes.logo} aria-label="Calendar">
          <IconCalendarClock className={classes.logoIcon} size={22} aria-hidden />
          <span className={classes.logoText}>Calendar</span>
        </Link>
        <Group component="nav" gap="xs" wrap="nowrap">
          <NavLink to="/book" className={classes.link}>
            Записаться
          </NavLink>
          <NavLink to="/admin" className={classes.link}>
            Админка
          </NavLink>
        </Group>
      </Group>
    </Container>
  );
}
