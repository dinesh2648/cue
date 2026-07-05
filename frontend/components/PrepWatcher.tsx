"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { api } from "@/lib/api";

// App-wide watcher: keeps polling a prep that's generating even after the user leaves the
// meeting view, and pops a toast when it's ready (or fails). The MeetingPrepPanel registers
// an event on start and clears it if the panel itself renders the finished brief.
type Toast = { id: number; msg: string; kind: "ok" | "err"; href?: string };
type Ctx = { watch: (eventId: string) => void; clear: (eventId: string) => void };

const PrepWatcherCtx = createContext<Ctx>({ watch: () => {}, clear: () => {} });
export const usePrepWatcher = () => useContext(PrepWatcherCtx);

export default function PrepWatcherProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const toast = useCallback(
    (msg: string, kind: "ok" | "err", href?: string) => {
      const id = ++nextId.current;
      setToasts((t) => [...t, { id, msg, kind, href }]);
      setTimeout(() => dismiss(id), 9000);
    },
    [dismiss]
  );

  const clear = useCallback((eventId: string) => {
    const t = timers.current.get(eventId);
    if (t) clearTimeout(t);
    timers.current.delete(eventId);
  }, []);

  const watch = useCallback(
    (eventId: string) => {
      if (timers.current.has(eventId)) return; // already watching
      let tries = 0;
      const tick = async () => {
        tries += 1;
        if (tries > 40) { timers.current.delete(eventId); return; } // ~4 min cap
        try {
          const r = await api.meetingPrep(eventId, false);
          if (r.generating) {
            timers.current.set(eventId, setTimeout(tick, 6000));
            return;
          }
          timers.current.delete(eventId);
          if (r.error) toast("Couldn't generate prep notes — open the meeting to retry.", "err");
          else toast(`✓ Prep ready${r.title ? " — " + r.title : ""}`, "ok", (process.env.NEXT_PUBLIC_BASE_PATH || "") + "/");
        } catch {
          timers.current.set(eventId, setTimeout(tick, 8000)); // transient network error — retry
        }
      };
      timers.current.set(eventId, setTimeout(tick, 6000));
    },
    [toast]
  );

  return (
    <PrepWatcherCtx.Provider value={{ watch, clear }}>
      {children}
      {toasts.length > 0 && (
        <div className="toast-wrap">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`toast ${t.kind}`}
              role="status"
              onClick={() => { if (t.href) window.location.href = t.href; dismiss(t.id); }}
              style={{ cursor: t.href ? "pointer" : "default" }}
            >
              <span>{t.msg}</span>
              <button className="toast-x" aria-label="Dismiss" onClick={(e) => { e.stopPropagation(); dismiss(t.id); }}>×</button>
            </div>
          ))}
        </div>
      )}
    </PrepWatcherCtx.Provider>
  );
}
