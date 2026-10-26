"""Command line: python -m agent.main "Why was diesel short on 8 October?" """
import sys
import textwrap

from .investigator import investigate


def show(kind, data):
    if kind == "station":
        print(f"[Station] {data.get('name')}  ({data.get('from')} to {data.get('to')})")
    elif kind == "memory":
        print("\n[H-MEM] recalled past findings:")
        for m in data["memories"]:
            print(f"   - ({m['relevance']}, {m['layer']}) {m['content'][:160]}  <{m['id']}>")
    elif kind == "memory_saved":
        for s in data.get("saved", []):
            extra = f" (supersedes {s['supersedes']})" if s.get("supersedes") else ""
            print(f"[H-MEM] saved {s['id']}{extra}")
        for c in data.get("conflicts", []):
            print(f"[H-MEM] conflict flagged: {c['a']} vs {c['b']} ({c['reason']})")
    elif kind == "thought":
        print(f"\n[step {data['step']}] {data['thought']}   (model: {data['model']})")
    elif kind == "sql":
        print(textwrap.indent(data["sql"], "   SQL> "))
    elif kind == "rows":
        print(f"   -> {data['count']} rows")
        print(textwrap.indent(data["table"], "      "))
    elif kind == "sql_error":
        print(f"   !! SQL error: {data['error'][:300]}")
    elif kind in ("warn", "error"):
        print(f"\n[{kind}] {data}")


def report(result, trace):
    print("\n" + "=" * 70)
    if not result:
        print("No final answer. See the trace file for details.")
    else:
        print("ANSWER:", result.get("answer", ""))
        for f in result.get("findings", []):
            print(f"\n* {f.get('title')}  [{f.get('status')}]")
            print(textwrap.indent(textwrap.fill(f.get("what", ""), 90), "  "))
            for e in f.get("evidence", []):
                print("    evidence:", e)
            if f.get("value_usd"):
                print(f"    value: US${f['value_usd']}")
            if f.get("on_duty"):
                print(f"    on duty: {f['on_duty']}")
    models = sorted({r.get("routed_model") for r in trace["receipts"] if r.get("routed_model")})
    receipts = [r.get("receipt_id") for r in trace["receipts"] if r.get("receipt_id")]
    print("\nPowered by:", ", ".join(models) or "unknown", "via Meterless Nightshift")
    print(f"Nightshift receipts: {len(receipts)} (first: {receipts[0] if receipts else '-'})")
    print("Trace saved to:", trace.get("saved_to"))


def main():
    question = " ".join(sys.argv[1:]).strip() or input("Question: ").strip()
    result, trace = investigate(question, on_event=show)
    report(result, trace)


if __name__ == "__main__":
    main()
