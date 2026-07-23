# Frontend — AI IT Helpdesk Agent

This is the face of the project: a small, dependency-light **React + Vite +
TypeScript** single-page app. Its job is to let you **file a ticket and then watch
the agent think and act in real time** — every classification, KB lookup, tool
call, policy decision, and confidence score scrolls past live — and to give a
human the controls to step in (approve an action, submit an OTP, take over,
override the outcome).

It is intentionally a thin client. The backend holds all the logic; the frontend
just **renders state and streams events.** There is no Redux, no data-fetching
library, no component framework — just React hooks, `fetch`, and the browser's
native `EventSource`. That keeps it easy to read and easy to reason about.

---

## Run it

```bash
npm install
npm run dev          # http://localhost:5173
```

`npm run dev` starts Vite on port 5173. During development Vite **proxies** API and
SSE calls (`/v1`, `/healthz`, `/readyz`) to the FastAPI backend on
`http://localhost:8000` (see `vite.config.ts`), so the browser talks to one origin
and there are no CORS headaches. Point it elsewhere with `VITE_BACKEND_URL`.

> Make sure the backend is running first (see [`../backend/README.md`](../backend/README.md)).
> The top bar shows the active model and warns you if `ANTHROPIC_API_KEY` isn't set.

Other scripts: `npm run build` (type-check + production bundle) · `npm run preview`
(serve the built bundle).

---

## What you see on screen

The layout is a classic two-pane console (`App.tsx`):

```
┌──────────────┬───────────────────────────────────────────────┐
│  Sidebar     │  Main panel  (the selected ticket)            │
│              │                                               │
│  • Intake    │  • Header: status / priority / flags / cost   │
│    (new      │  • Verify panel   (only when awaiting OTP)     │
│     ticket)  │  • HITL panel     (approve / deny / override)  │
│  • Ticket    │  • Conversation   (the user ↔ agent thread)    │
│    list      │  • Reply box      (answer as the user)         │
│              │  • Agent trace    (the live event stream)      │
└──────────────┴───────────────────────────────────────────────┘
```

The sidebar polls the ticket list every few seconds so new and updated tickets
appear on their own. Selecting one opens the detail view on the right.

---

## How the live trace works (the interesting part)

This is what makes the agent's behavior *legible* instead of a black box.

1. When you open a ticket, the **`useEventStream` hook** opens a native
   `EventSource` to `GET /v1/tickets/:id/stream` — a **Server-Sent Events** (SSE)
   connection. SSE is the right tool here: it's one-directional (server → browser),
   auto-reconnects, and runs over plain HTTP, so it sails through the Vite proxy.
2. The backend, on connect, **replays everything that already happened** to this
   ticket and then keeps streaming new events as they occur. So whether you open
   the ticket while the agent is mid-run or hours later, you see the full story.
3. Each event carries a **sequence number**. The hook keeps a `Set` of sequence
   numbers it has already shown and ignores duplicates — important because a
   reconnect re-sends the backlog. The result is a clean, gap-free, in-order log.
4. **`AgentTrace.tsx`** renders each event with an icon and a human-readable line:
   `◆ phase`, `💭 thought`, `🔧 tool_call`, `🛡️ policy`, `🎯 confidence`,
   `🚨 escalated`, `✅ resolved`, and so on. A little "live / idle" dot shows
   whether the stream is currently connected.
5. As events arrive, the detail view also **re-fetches the ticket** (its status,
   confidence, and cost have probably changed), with a slow backstop poll in case
   any event is ever missed.

So the trace you watch is exactly the sequence of events the agent emitted on the
backend — there's no separate "frontend logic" guessing what happened.

---

## Stepping in: human-in-the-loop

The agent deliberately pauses and waits for a human in a few situations, and the
UI surfaces the right control for each:

- **Awaiting identity verification** → the **Verify panel** appears so you can
  submit the OTP (demo code `123456`). The agent resumes and completes the
  privileged action.
- **Awaiting approval** (e.g. *install Slack*) → the **HITL panel** offers
  **Approve / Deny**. Approving runs the parked action and lets the agent finish.
- **Any ticket** → the HITL panel also exposes overrides — **take over**,
  **force-resolve**, **force-escalate**, or **reply as a specialist** — so a human
  always has the final say.
- **Follow-up** → after a resolve the agent asks "is it working?"; you answer in
  the normal **reply box** (`yes` / `no`), which drives the close-or-reopen loop.

Every one of these actions starts a fresh agent run on the backend, and you watch
the result stream straight back into the trace.

---

## Project structure

```
frontend/
├── index.html
├── vite.config.ts          dev server + proxy to the backend
└── src/
    ├── main.tsx            React entry point
    ├── App.tsx             two-pane layout, ticket list polling, top bar
    ├── styles.css          all styling (plain CSS, no framework)
    ├── api/
    │   ├── client.ts       a tiny typed wrapper over fetch — the ONLY place
    │   │                   that knows backend URLs (config, tickets, messages,
    │   │                   verify, approve, hitl, escalation)
    │   └── types.ts        TypeScript shapes mirroring the backend's responses
    ├── hooks/
    │   └── useEventStream.ts   the SSE subscription + sequence de-duplication
    └── components/
        ├── TicketIntake.tsx    the "new ticket" form (+ example prompts)
        ├── TicketList.tsx      the sidebar list
        ├── TicketDetail.tsx    orchestrates the detail pane + wires up the stream
        ├── Conversation.tsx    the user ↔ agent message thread
        ├── AgentTrace.tsx      renders the live event stream
        ├── HitlPanel.tsx       approve / deny / override controls
        ├── VerifyPanel.tsx     the OTP entry panel
        └── Badges.tsx          status / priority / confidence / flag chips
```

### One rule worth keeping

**All backend access goes through `src/api/client.ts`.** It's the single typed
boundary between the UI and the server: if an endpoint changes, there's exactly
one file to update, and every component stays blissfully unaware of URLs and
request shapes. The live trace is the one exception — it uses `EventSource`
directly inside `useEventStream`, because SSE isn't a `fetch` call.
