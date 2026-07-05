"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { MeetingPrep } from "@/lib/types";

// Minimal, safe markdown → React for the prep brief: ## / ### headings, - / * bullets,
// **bold**, [text](url), bare URLs, and paragraphs. No raw HTML, no new deps.
function renderInline(text: string, keyBase: string) {
  const nodes: React.ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)|(https?:\/\/[^\s)]+)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[1]) nodes.push(<b key={`${keyBase}-b${k++}`}>{m[1]}</b>);
    else if (m[2]) nodes.push(<a key={`${keyBase}-l${k++}`} href={m[3]} target="_blank" rel="noreferrer">{m[2]}</a>);
    else if (m[4]) nodes.push(<a key={`${keyBase}-u${k++}`} href={m[4]} target="_blank" rel="noreferrer">{m[4].replace(/^https?:\/\//, "")}</a>);
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

const cells = (l: string) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const isSep = (l: string) => /^\s*\|?[\s:|-]+\|?\s*$/.test(l) && l.includes("-");

export function Markdown({ md }: { md: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = md.split("\n");
  let bullets: string[] = [];
  let key = 0;
  const flush = () => {
    if (bullets.length) {
      const items = bullets;
      blocks.push(
        <ul key={`ul${key++}`} className="prep-ul">
          {items.map((b, i) => <li key={i}>{renderInline(b, `li${key}-${i}`)}</li>)}
        </ul>
      );
      bullets = [];
    }
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    // GFM table: header row + separator row, then body rows
    if (isRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
      flush();
      const header = cells(line);
      const body: string[][] = [];
      i += 2;
      while (i < lines.length && isRow(lines[i])) { body.push(cells(lines[i])); i++; }
      i--;
      const kk = key++;
      blocks.push(
        <div key={`tw${kk}`} className="prep-tablewrap">
          <table className="prep-table">
            <thead><tr>{header.map((h, j) => <th key={j}>{renderInline(h, `th${kk}-${j}`)}</th>)}</tr></thead>
            <tbody>{body.map((r, ri) => (
              <tr key={ri}>{header.map((_, ci) => <td key={ci}>{renderInline(r[ci] ?? "", `td${kk}-${ri}-${ci}`)}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>
      );
      continue;
    }
    if (/^###\s+/.test(line)) { flush(); blocks.push(<h4 key={`h${key++}`} className="prep-h">{renderInline(line.replace(/^###\s+/, ""), `h${key}`)}</h4>); }
    else if (/^##\s+/.test(line)) { flush(); blocks.push(<h3 key={`h${key++}`} className="prep-h">{renderInline(line.replace(/^##\s+/, ""), `h${key}`)}</h3>); }
    else if (/^#\s+/.test(line)) { flush(); blocks.push(<h3 key={`h${key++}`} className="prep-h">{renderInline(line.replace(/^#\s+/, ""), `h${key}`)}</h3>); }
    else if (/^(---+|\*\*\*+|___+)$/.test(line.trim())) { flush(); /* horizontal rule — skip */ }
    else if (/^\s*[-*]\s+/.test(line)) { bullets.push(line.replace(/^\s*[-*]\s+/, "")); }
    else if (line.trim() === "") { flush(); }
    else { flush(); blocks.push(<p key={`p${key++}`} className="prep-p">{renderInline(line, `p${key}`)}</p>); }
  }
  flush();
  return <div className="prep-md">{blocks}</div>;
}

const PREP_HINTS = [
  "Reading your calendar invite & attendees…",
  "Checking Jira tickets & GitHub activity…",
  "Scanning recent emails…",
  "Searching Notion & shared docs…",
  "Pulling it together into your brief…",
];

export default function MeetingPrepPanel({ eventId }: { eventId: string }) {
  const [prep, setPrep] = useState<MeetingPrep | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  // Generation runs in the background server-side; poll until it's ready.
  const poll = async (refresh = false) => {
    setError(null);
    try {
      const r = await api.meetingPrep(eventId, refresh);
      if (!alive.current) return;
      if (r.generating) {
        setGenerating(true);
        timer.current = setTimeout(() => poll(false), 4000);
      } else if (r.error) {
        setGenerating(false);
        setError(r.error);
      } else {
        setGenerating(false);
        setPrep(r as MeetingPrep);
      }
    } catch (e) {
      if (!alive.current) return;
      setGenerating(false);
      setError(e instanceof Error ? e.message : "Failed to prepare notes");
    }
  };

  const start = (refresh = false) => {
    if (timer.current) clearTimeout(timer.current);
    setGenerating(true);
    if (refresh) setPrep(null);
    poll(refresh);
  };

  useEffect(() => {
    alive.current = true;
    start(false);
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId]);

  // Rotate the progress hint while generating (cosmetic — reflects what prep actually does).
  useEffect(() => {
    if (!generating || prep) return;
    const t = setInterval(() => setHint((h) => (h + 1) % PREP_HINTS.length), 3000);
    return () => clearInterval(t);
  }, [generating, prep]);

  return (
    <div className="prep-panel">
      {generating && !prep ? (
        <div className="prep-loading">
          <span className="prep-spinner" aria-hidden="true" />
          <span>{PREP_HINTS[hint]}<small style={{ opacity: 0.7 }}> · up to a minute</small></span>
        </div>
      ) : error && !prep ? (
        <div className="prep-error">
          {error} <button className="btn sm" onClick={() => start(true)}>Retry</button>
        </div>
      ) : prep ? (
        <>
          <Markdown md={prep.markdown} />
          <div className="prep-foot">
            {prep.sources.length > 0 && (
              <span className="prep-sources">
                {prep.sources.map((s, i) => (
                  <span key={i} className="source-chip" title={s.detail}>{s.label}</span>
                ))}
              </span>
            )}
            <span className="prep-meta">
              {prep.engine === "claude+mcp" ? "researched live" : prep.engine === "llm" ? "from your notes" : "limited context"}
              {" · "}
              <button className="prep-refresh" onClick={() => start(true)} disabled={generating}>
                {generating ? "refreshing…" : "↻ refresh"}
              </button>
            </span>
          </div>
        </>
      ) : null}
    </div>
  );
}
