import { Navigate, Route, Routes } from "react-router";
import Layout from "./layout/Layout.tsx";
import Book from "./pages/Book.tsx";
import BookEventType from "./pages/BookEventType.tsx";
import Landing from "./pages/Landing.tsx";
import AdminBookings from "./pages/admin/AdminBookings.tsx";
import AdminEventTypes from "./pages/admin/AdminEventTypes.tsx";
import AdminLayout from "./pages/admin/AdminLayout.tsx";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Landing />} />
        <Route path="book" element={<Book />} />
        <Route path="book/:eventTypeId" element={<BookEventType />} />
        <Route path="admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="bookings" replace />} />
          <Route path="bookings" element={<AdminBookings />} />
          <Route path="event-types" element={<AdminEventTypes />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
