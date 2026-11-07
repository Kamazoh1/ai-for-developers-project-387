# Call Calendar

A simplified Cal.com: guests book calls of the owner's event types into free slots on a single shared calendar.

## Language

**Owner**:
The single predefined profile that owns the calendar: it creates event types and sees upcoming bookings. Has no account and does not sign in.
_Avoid_: Admin, host, user

**Guest**:
A person who books a slot, identified only by the name and email they enter. Has no account.
_Avoid_: User, client, customer, invitee

**Admin area**:
The part of the interface where the owner manages event types and sees upcoming bookings. Open to anyone who knows its address, since there is no sign-in.
_Avoid_: Dashboard, panel

**Event type**:
A kind of call the owner offers, defined by an id, a name, a description and a duration. Slots and bookings take their length from it.
_Avoid_: Meeting type, call type, service

**Slot**:
A candidate interval for an event type: as long as that type's duration and starting at an allowed start time within the owner's working hours. A slot is free unless it overlaps a booking.
_Avoid_: Time, appointment time, interval

**Booking**:
A taken interval of one event type, together with the name and email of the guest who took it. Bookings never overlap, whatever their event types.
_Avoid_: Event, reservation, appointment, meeting

**Calendar timezone**:
The time zone in which the calendar's days and working hours are defined. Every slot belongs to a day of this zone.
_Avoid_: Server timezone, owner timezone, local time

**Booking window**:
The range of days, from today onward, in which slots can be booked. Days outside it are unavailable.
_Avoid_: Horizon, availability range
