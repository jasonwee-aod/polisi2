export default function ChatLandingPage() {
  return (
    <div style={{ width: "min(100%, 38rem)", display: "grid", gap: "1rem" }}>
      <span
        style={{
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          fontWeight: 700,
          color: "#4f6a5f"
        }}
      >
        New conversation
      </span>
      <h1 style={{ margin: 0, fontSize: "2.3rem" }}>Ask about a policy in BM or English.</h1>
      <p style={{ margin: 0, color: "#31443b", lineHeight: 1.7 }}>
        Start with a direct question. Replies will stream in here once the backend behavior
        lands, and your thread will stay attached to this account.
      </p>
    </div>
  );
}
