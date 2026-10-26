"""Memory: the Meterless H-MEM engine (official reference implementation, in hmem/).

Python talks to it through hmem/bridge.ts (JSON in, JSON out). H-MEM ranks past
findings with its hybrid formula, keeps an append-only trust ledger of every
create/read/update, and supersedes an old finding when a new investigation
revises it instead of piling up duplicates.

Setup once:  cd hmem  &&  npm install
Check spec:  cd hmem  &&  npm run conformance      (13/13 checks)
"""
import json
import os
import re
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HMEM_DIR = os.path.join(ROOT, "hmem")
TSX_CLI = os.path.join(HMEM_DIR, "node_modules", "tsx", "dist", "cli.mjs")
BRIDGE = os.path.join(HMEM_DIR, "bridge.ts")


class MemoryError_(RuntimeError):
    pass


SAMPLE_SCOPE = "sunrise-fuels-harare-sample-data:2026-10-01:2026-10-14"


def store_dir(scope: str = "") -> str:
    """Each station's memories live in their own H-MEM store, so one station's findings
    never show up in another's investigation. The sample keeps the original folder."""
    if not scope:
        from .loader import current_station
        scope = current_station().get("scope", "")
    if not scope or scope == SAMPLE_SCOPE:
        return os.path.join(ROOT, "memory", "hmem")
    safe = re.sub(r"[^A-Za-z0-9-]+", "_", scope)[:80]
    return os.path.join(ROOT, "memory", "stations", safe)


def _call(request: dict, timeout: int = 60, scope: str = ""):
    node = shutil.which("node")
    if not node:
        raise MemoryError_("Node.js not found. Install Node 20+ from nodejs.org.")
    if not os.path.exists(TSX_CLI):
        raise MemoryError_("H-MEM not installed. Run:  cd hmem  then  npm install")
    p = subprocess.run([node, TSX_CLI, BRIDGE], input=json.dumps(request), capture_output=True,
                       text=True, encoding="utf-8", timeout=timeout, cwd=ROOT,
                       env={**os.environ, "HMEM_DIR": os.environ.get("HMEM_DIR") or store_dir(scope)})
    try:
        out = json.loads(p.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MemoryError_(f"H-MEM bridge output not JSON: {p.stdout[:200]} {p.stderr[:300]}") from exc
    if isinstance(out, dict) and out.get("error"):
        raise MemoryError_(out["error"])
    return out


def recall(question: str, limit: int = 5):
    """Returns {'context': str, 'memories': [...], 'trace': {...}} from H-MEM retrieval."""
    return _call({"op": "recall", "query": question, "topN": limit})


def remember(findings, source: str = "", question: str = ""):
    """Store findings (confirmed losses go to long-term memory). Returns saved ids and conflicts."""
    return _call({"op": "remember", "findings": findings, "source": source, "question": question})


def feedback(memory_id: str, kind: str):
    """kind: helpful | not_helpful | wrong  (H-MEM adjusts confidence: +0.05 / -0.03 / -0.20)."""
    return _call({"op": "feedback", "id": memory_id, "kind": kind})


def ledger(limit: int = 20):
    return _call({"op": "ledger", "limit": limit})


def stats():
    return _call({"op": "stats"})


def list_all():
    return _call({"op": "list"})


if __name__ == "__main__":
    # python -m agent.memory stats | ledger [n] | feedback <memory-id> helpful|not_helpful|wrong
    import sys
    args = sys.argv[1:] or ["stats"]
    if args[0] == "ledger":
        for e in ledger(int(args[1]) if len(args) > 1 else 20):
            print(e.get("timestamp"), e.get("action"), e.get("memoryId"), e.get("actor"))
    elif args[0] == "feedback" and len(args) == 3:
        m = feedback(args[1], args[2])["memory"]
        print(f"{m['id']} confidence now {m['confidence']:.2f} tags {m['tags'][:3]}")
    else:
        print(json.dumps(stats(), indent=2))
