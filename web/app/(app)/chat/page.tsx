export default function ChatLandingPage() {
  return (
    <section
      style={{
        width: "min(100%, 40rem)",
        display: "grid",
        gap: "1rem",
        justifySelf: "center"
      }}
    >
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
      <div
        style={{
          display: "grid",
          gap: "0.6rem",
          padding: "1rem 1.1rem",
          borderRadius: "1.25rem",
          border: "1px solid rgba(20, 35, 29, 0.1)",
          background: "rgba(246, 247, 241, 0.9)"
        }}
      >
        <strong>BM ready</strong>
        <p style={{ margin: 0, color: "#4f6a5f" }}>
          Example prompts: &quot;Apakah bantuan zakat untuk pelajar IPT?&quot; or
          &quot;What childcare subsidies are available for working parents?&quot;
        </p>
      </div>
    </section>
  );
}
