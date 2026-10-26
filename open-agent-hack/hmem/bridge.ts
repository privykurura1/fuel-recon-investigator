// JSON bridge between the Python agent and the Meterless H-MEM engine.
// Reads one JSON request on stdin, writes one JSON reply on stdout.
//
//   {"op":"recall","query":"...","topN":5,"threshold":0.08}   (spec default 0.35 is tuned down: section 13)
//   {"op":"remember","findings":[...],"source":"runs/2026...json","question":"..."}
//   {"op":"feedback","id":"mem_...","kind":"helpful|not_helpful|wrong"}
//   {"op":"ledger","limit":20}
//   {"op":"stats"}
//   {"op":"list"}
//
// State persists in memory/hmem/ (state.json + append-only ledger.jsonl).

import path from "node:path";
import { fileURLToPath } from "node:url";
import { HMEM } from "./reference/src/index.ts";
import type { MemoryRecord } from "./reference/src/index.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const persistDir = process.env.HMEM_DIR ?? path.join(here, "..", "memory", "hmem");
const hmem = new HMEM({ persistDir, actor: "fuel-recon-investigator" });

type Finding = {
  title?: string; status?: string; what?: string; evidence?: string[];
  value_usd?: number; on_duty?: string;
};

const CONFIDENCE: Record<string, number> = { confirmed_loss: 0.9, explained: 0.85, unresolved: 0.6 };

const STOP = new Set(["the","and","for","was","were","why","any","our","this","that","with","from","does","did","is","are","what","which","who","how","not","than","has","have","into","per","all"]);

// Keyword tags from the finding title and the question, so H-MEM's tag/keyword
// signals can match later questions (the reference embedder is a hash mock).
function keywordTags(...texts: string[]): string[] {
  const words = texts.join(" ").toLowerCase().match(/[a-z0-9-]{3,}/g) ?? [];
  return [...new Set(words.filter((w) => !STOP.has(w)))].slice(0, 10);
}

// Identity of a finding = its status + the facts it is about (pumps, tanks, dates, delivery notes,
// bank references), not the model's wording. Re-investigating the same facts supersedes the old memory.
function factKey(status: string, f: Finding): string {
  const text = [f.title, f.what, ...(f.evidence ?? [])].join(" ").toUpperCase();
  const ids = new Set<string>();
  // Station IDs (P1, T2, PUMP-07, DN-1043), cash references (SF-1011-DAY) and ISO dates.
  // Words like US$ amounts or plain numbers are not IDs: an ID needs letters followed by digits.
  for (const m of text.matchAll(/\b(SF-\d{4}-[A-Z0-9]+|20\d\d-\d\d-\d\d|[A-Z]{1,5}-?\d{1,6})\b/g)) ids.add(m[1]);
  const facts = [...ids].sort().join("|");
  return facts ? `finding:${status}:${facts}` : `finding:${status}:${slug(f.title ?? "")}`;
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
}

function current(tag: string): MemoryRecord | undefined {
  return hmem.store.all().find((m) => m.tags.includes(tag) && !m.supersededBy);
}

function remember(findings: Finding[], source: string, question: string) {
  const saved: { id: string; supersedes?: string; content: string }[] = [];
  for (const f of findings) {
    const status = f.status ?? "unresolved";
    // Only proven facts become memories: a loss shown by the data, or a gap the data explains.
    if ((status !== "confirmed_loss" && status !== "explained") || !f.title) continue;
    const key = factKey(status, f);
    const evidence = (f.evidence ?? []).slice(0, 4).join("; ");
    const content =
      `[${status}] ${f.title}: ${f.what ?? ""}` +
      (f.value_usd ? ` Value US$${f.value_usd}.` : "") +
      (f.on_duty ? ` On duty: ${f.on_duty}.` : "") +
      (evidence ? ` Evidence: ${evidence}` : "");
    const previous = current(key);
    if (previous && previous.content === content) {
      hmem.store.touch(previous.id);           // same finding again: reinforce, don't duplicate
      saved.push({ id: previous.id, content });
      continue;
    }
    const rec = hmem.add({
      content,
      type: "factual",
      layer: status === "confirmed_loss" ? "long_term" : "working",
      tags: [key, `status:${status}`, "project:fuel-recon", ...keywordTags(f.title, question)],
      confidence: CONFIDENCE[status] ?? 0.6,
      source: `investigation:${source}`,
      provenance: { origin: "model_response", learnedAt: Date.now(), label: `Investigation: ${question}`, refs: [source] },
      supersedes: previous?.id,
    });
    if (previous) hmem.store.update(previous.id, { supersededBy: rec.id });
    saved.push({ id: rec.id, supersedes: previous?.id, content });
  }
  const conflicts = hmem.conflicts.scan().map((c) => ({ a: c.memoryA, b: c.memoryB, reason: c.reason }));
  return { saved, conflicts };
}

function recall(query: string, topN = 5, threshold = 0.08) {
  const r = hmem.query(query, { topN, threshold });
  return {
    context: r.context,
    memories: r.memories.map((m) => ({
      id: m.memory.id, content: m.memory.content, relevance: Number(m.relevance.toFixed(3)),
      layer: m.memory.layer, confidence: m.memory.confidence,
    })),
    trace: r.trace,
  };
}

async function main() {
  let raw = "";
  for await (const chunk of process.stdin) raw += chunk;
  const req = JSON.parse(raw || "{}");
  let out: unknown;
  switch (req.op) {
    case "recall": out = recall(String(req.query ?? ""), req.topN ?? 5, req.threshold ?? 0.08); break;
    case "remember": out = remember(req.findings ?? [], String(req.source ?? "unknown"), String(req.question ?? "")); break;
    case "feedback": hmem.feedback(req.id, req.kind); out = { ok: true, memory: hmem.store.get(req.id) }; break;
    case "ledger": out = hmem.ledger.all().slice(-(req.limit ?? 20)); break;
    case "list": out = hmem.store.all().map((m) => ({
      id: m.id, content: m.content, layer: m.layer, confidence: Number(m.confidence.toFixed(2)),
      tags: m.tags.filter((t) => t.startsWith("status:") || t === "review"),
      supersededBy: m.supersededBy ?? null, accessCount: m.accessCount,
    })); break;
    case "stats": out = { memories: hmem.store.all().length, ledger: hmem.ledger.stats(), persistDir }; break;
    default: throw new Error(`unknown op ${req.op}`);
  }
  process.stdout.write(JSON.stringify(out, (k, v) => (k === "embedding" ? undefined : v)));
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({ error: String(err?.message ?? err) }));
  process.exitCode = 1;
});
