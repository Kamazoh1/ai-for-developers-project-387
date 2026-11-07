import { useNavigate } from "react-router";

/** The browser's Back and Forward, as buttons inside the router (see `renderAppWithHistory`). */
export default function HistoryButtons() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate(-1)}>history back</button>
      <button onClick={() => navigate(1)}>history forward</button>
    </>
  );
}
