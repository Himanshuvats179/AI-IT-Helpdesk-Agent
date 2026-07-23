import type { Message } from "../api/types";

export function Conversation({ messages }: { messages: Message[] }) {
  return (
    <div className="card">
      <h3>Conversation</h3>
      <div className="conversation">
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            <div className="who">{m.role === "user" ? m.author ?? "user" : m.role}</div>
            {m.body}
          </div>
        ))}
        {messages.length === 0 && <div className="muted">No messages.</div>}
      </div>
    </div>
  );
}
