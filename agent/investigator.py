"""The agent loop: Nemotron decides the next query, Zetaris answers, repeat, then report."""
import json
import os
import re
from datetime import datetime

from . import config, memory, prompts, station
from .llm import LLMError, chat
from .zetaris import SQLError, as_table, run_sql


def parse_action(text: str):
    """Pull the first JSON object out of the model's reply."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        # strict=False accepts raw line breaks inside strings (common in long SQL)
                        return json.loads(text[start:i + 1], strict=False)
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def investigate(question: str, on_event=None):
    """Run one investigation. on_event(kind, data) lets a UI or CLI show progress."""
    emit = on_event or (lambda kind, data: None)
    facts = station.facts()
    emit("station", {k: facts.get(k) for k in ("name", "from", "to")})
    try:
        recalled = memory.recall(question)
    except Exception as exc:  # graceful degradation: investigate without memory
        emit("warn", f"H-MEM recall unavailable: {exc}")
        recalled = {"context": "", "memories": [], "trace": {}}
    messages = [
        {"role": "system", "content": prompts.build_system(facts["text"]) + prompts.memory_block(recalled.get("context", ""))},
        {"role": "user", "content": question},
    ]
    trace = {"question": question, "station": facts.get("name"), "scope": facts.get("scope"), "started": datetime.now().isoformat(timespec="seconds"),
             "recalled": recalled, "steps": [], "receipts": []}
    if recalled.get("memories"):
        emit("memory", recalled)

    result = None
    for step in range(1, config.MAX_STEPS + 1):
        forcing = step == config.MAX_STEPS
        if forcing:
            messages.append({"role": "user", "content":
                             "Step limit reached. Give your final JSON answer now using only the evidence you have."})
        try:
            reply, receipt = chat(messages)
        except LLMError as exc:
            emit("error", str(exc))
            trace["error"] = str(exc)
            break
        trace["receipts"].append(receipt)
        action = parse_action(reply)
        if not action or "action" not in action:
            trace.setdefault("bad_replies", []).append({"step": step, "reply": reply[:1500]})
            emit("warn", f"Model reply was not valid JSON; asking it to retry. Start of reply: {reply[:120]!r}")
            messages += [{"role": "assistant", "content": reply[:2000]},
                         {"role": "user", "content":
                          "Your last reply was not valid JSON. Reply with exactly ONE JSON object and nothing else, e.g. "
                          '{"thought": "...", "action": "run_sql", "sql": "SELECT ..."} '
                          'or {"thought": "...", "action": "final", "findings": [...], "answer": "..."}'}]
            continue
        messages.append({"role": "assistant", "content": json.dumps(action)})
        emit("thought", {"step": step, "thought": action.get("thought", ""), "model": receipt.get("routed_model")})

        if action["action"] == "final":
            result = action
            break

        if action["action"] == "run_sql":
            sql = (action.get("sql") or "").strip()
            emit("sql", {"step": step, "sql": sql})
            try:
                cols, rows = run_sql(sql)
                table = as_table(cols, rows, config.ROWS_TO_MODEL)
                emit("rows", {"step": step, "count": len(rows), "table": as_table(cols, rows, 12),
                              "columns": cols, "rows": rows[:12]})
                trace["steps"].append({"step": step, "thought": action.get("thought"), "sql": sql,
                                       "rows": len(rows), "result": table})
                if len(rows) > config.ROWS_TO_MODEL:
                    note = (f"INCOMPLETE RESULT: you are seeing only {config.ROWS_TO_MODEL} of {len(rows)} rows. "
                            "Do NOT draw conclusions from it. Re-run with a filter (e.g. WHERE ABS(difference) > 1) "
                            "or aggregation so the result fits, or use a STANDARD CHECK.\n")
                else:
                    note = ""
                messages.append({"role": "user", "content": f"{note}Query result ({len(rows)} rows):\n{table}"})
            except SQLError as exc:
                if str(exc).startswith("Cannot reach Zetaris"):
                    trace["infra_error"] = True
                emit("sql_error", {"step": step, "error": str(exc)})
                trace["steps"].append({"step": step, "sql": sql, "error": str(exc)})
                messages.append({"role": "user", "content": f"SQL error: {exc}\nFix the SQL and try again."})
            continue

        messages.append({"role": "user", "content": "Unknown action. Use run_sql or final."})

    if result is None and "error" not in trace:
        # Step limit reached mid-investigation: ask once more for an answer, no more queries.
        messages.append({"role": "user", "content":
                         "No more queries are allowed. Reply now with the final JSON (action \"final\") "
                         "using only evidence from the query results above."})
        try:
            reply, receipt = chat(messages)
            trace["receipts"].append(receipt)
            action = parse_action(reply)
            if action and action.get("action") == "final":
                result = action
                emit("thought", {"step": "final", "thought": action.get("thought", ""), "model": receipt.get("routed_model")})
        except LLMError as exc:
            emit("error", str(exc))

    trace["result"] = result
    trace["finished"] = datetime.now().isoformat(timespec="seconds")
    save_trace(trace)
    if trace.get("infra_error"):
        emit("warn", "Zetaris was unreachable during this run, so its findings were NOT saved to H-MEM.")
    elif result and result.get("findings"):
        try:
            trace["memory_saved"] = memory.remember(result["findings"], trace["saved_to"], question)
            emit("memory_saved", trace["memory_saved"])
            save_trace(trace, trace["saved_to"])
        except Exception as exc:
            emit("warn", f"H-MEM could not save findings: {exc}")
    return result, trace


def save_trace(trace, name=None):
    os.makedirs("runs", exist_ok=True)
    name = name or datetime.now().strftime("runs/%Y%m%d-%H%M%S.json")
    with open(name, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2, default=str)
    trace["saved_to"] = name
