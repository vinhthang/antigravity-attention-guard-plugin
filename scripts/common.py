import sys
import os
import json
import re

def is_markdown_file(file_path):
    if not file_path or not isinstance(file_path, str):
        return False
    path_lower = file_path.lower()
    return path_lower.endswith(".md") or path_lower.endswith(".markdown")

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

_TRANSCRIPT_CACHE = {}

def clear_transcript_cache():
    _TRANSCRIPT_CACHE.clear()

def _remove_matching_task_id(target_list: list, task_id: str):
    tid_clean = task_id.strip()
    tid_base = tid_clean.split("/")[-1]
    matched = [t for t in target_list if t == tid_clean or t.split("/")[-1] == tid_base]
    for m in matched:
        target_list.remove(m)


_CMD_TOOLS = ("run_command", "default_api:run_command")
_ASYNC_OR_WORKFLOW_TOOLS = (
    "run_command", "default_api:run_command",
    "run_workflow", "default_api:run_workflow",
)


def _pop_matching_planner_call(
    planner_tool_calls: list,
    match_text: str,
    bidirectional: bool = False,
    is_cmd_exit: bool = False,
    is_sync_completion: bool = False,
):
    if not planner_tool_calls:
        return None
    allowed_names = _CMD_TOOLS if is_cmd_exit else _ASYNC_OR_WORKFLOW_TOOLS
    eligible = []
    for i, tc in enumerate(planner_tool_calls):
        tname = tc.get("name")
        if tname not in allowed_names:
            continue
        tc_args = tc.get("args") or {}
        if tname in _CMD_TOOLS:
            tc_summary = str(tc_args.get("toolSummary") or "").strip().strip('"\'')
            tc_cmd = str(tc_args.get("CommandLine") or "").strip().strip('"\'')
            candidates = (tc_summary, tc_cmd)
            has_explicit_label = bool(tc_summary)
            raw_d = tc_args.get("IsDaemon")
            is_daemon_call = raw_d if isinstance(raw_d, bool) else (str(raw_d or "").strip().lower().strip('"\'') in ("true", "1", "yes"))
        else:
            tc_desc = str(tc_args.get("Description") or tc_args.get("description") or "").strip().strip('"\'')
            candidates = (tc_desc,)
            has_explicit_label = bool(tc_desc)
            is_daemon_call = False
        eligible.append((i, has_explicit_label, tname in _CMD_TOOLS, is_daemon_call))
        for cand in candidates:
            if cand and (cand in match_text or (bidirectional and match_text and match_text in cand)):
                return planner_tool_calls.pop(i)
    if is_sync_completion and not is_cmd_exit:
        predicates = (
            lambda lbl, is_cmd, is_d: not lbl and not is_cmd,
            lambda lbl, is_cmd, is_d: not is_cmd,
            lambda lbl, is_cmd, is_d: not lbl and not is_d,
            lambda lbl, is_cmd, is_d: not is_d,
        )
    elif is_cmd_exit:
        predicates = (
            lambda lbl, is_cmd, is_d: not lbl and not is_d,
            lambda lbl, is_cmd, is_d: not is_d,
        )
    else:
        predicates = (
            lambda lbl, is_cmd, is_d: not lbl and is_d,
            lambda lbl, is_cmd, is_d: not lbl,
            lambda lbl, is_cmd, is_d: is_cmd,
        )
    for pred in predicates:
        for i, has_explicit_label, is_cmd, is_daemon_call in eligible:
            if pred(has_explicit_label, is_cmd, is_daemon_call):
                return planner_tool_calls.pop(i)
    if eligible:
        return planner_tool_calls.pop(eligible[0][0])
    return None


def parse_transcript(transcript_path: str) -> dict:
    empty_result = {
        "turn_id": 0,
        "lines_count": 0,
        "tokens": [],
        "first_system_sender": None,
        "steps": [],
        "active_bg_tasks": [],
        "active_context_chars": 0,
        "has_valid_json_steps": False,
    }
    if not transcript_path or not os.path.exists(transcript_path):
        return empty_result

    abs_p = os.path.abspath(transcript_path)
    try:
        st = os.stat(abs_p)
        cache_entry = _TRANSCRIPT_CACHE.get(abs_p)
        if cache_entry and cache_entry[0] == st.st_mtime_ns and cache_entry[1] == st.st_size:
            return cache_entry[2]
    except OSError:
        return empty_result

    turn_id = 0
    lines_count = 0
    tokens = []
    first_system_sender = None
    steps = []
    active_bg_tasks = []
    active_context_chars = 0
    has_valid_json_steps = False
    planner_tool_calls = []

    token_pattern = re.compile(r'\[ANTIGRAVITY_TOKEN:([a-fA-F0-9\-]+)\]')
    sender_pattern = re.compile(r'\bsender=([0-9a-fA-F\-]{36})\b')
    task_bg_pattern = re.compile(r'Tool is running as a background task with task id:\s*([^\s/]+/task-\d+|task-\d+)')
    task_desc_pattern = re.compile(r'Task Description:\s*(.*)')
    task_cancel_pattern = re.compile(r'Task "([^"]+)" cancel+ed\.')
    system_sender_task_pattern = re.compile(r'\bsender=([^\s/]+/task-\d+|task-\d+)\b')
    system_task_finish_pattern = re.compile(r'Task id "([^"]+)"\s+(?:finished|was cancel+ed)')

    try:
        with open(abs_p, "r", encoding="utf-8") as f:
            for idx, raw_line in enumerate(f):
                line_str = raw_line.strip()
                if not line_str:
                    continue
                lines_count += 1
                try:
                    step = json.loads(line_str)
                except Exception:
                    step = {}
                steps.append((idx, line_str, step))

                if isinstance(step, dict) and bool(step):
                    has_valid_json_steps = True
                    stype_raw = step.get("type", "")
                    content_str = str(step.get("content") or "")
                    if stype_raw in ("CHECKPOINT", "COMPACTION") or "compacted" in str(stype_raw).lower() or "resuming from a compaction" in content_str.lower():
                        active_context_chars = 0
                    else:
                        if stype_raw in ("USER_INPUT", "SYSTEM_MESSAGE") and "<context_summary>" in content_str.lower():
                            active_context_chars = 0
                        active_context_chars += len(content_str)
                        tool_calls = step.get("tool_calls") or []
                        if tool_calls:
                            try:
                                active_context_chars += len(json.dumps(tool_calls))
                            except Exception as exc:
                                _ = exc

                source = str(step.get("source", ""))
                stype = step.get("type", "")

                if source.startswith("USER") and stype == "USER_INPUT":
                    turn_id = step.get("step_index", turn_id)

                if source == "SYSTEM" and stype == "SYSTEM_MESSAGE":
                    content = str(step.get("content") or "")
                    for m in system_sender_task_pattern.finditer(content):
                        _remove_matching_task_id(active_bg_tasks, m.group(1))
                    for m in system_task_finish_pattern.finditer(content):
                        _remove_matching_task_id(active_bg_tasks, m.group(1))

                if stype in ("USER_INPUT", "SYSTEM_MESSAGE"):
                    content = str(step.get("content") or "")
                    for match in token_pattern.finditer(content):
                        tok = match.group(1)
                        if tok not in tokens:
                            tokens.append(tok)

                if lines_count == 1 and source == "SYSTEM" and stype == "SYSTEM_MESSAGE":
                    content = str(step.get("content") or "")
                    m = sender_pattern.search(content)
                    if m:
                        first_system_sender = m.group(1)

                if stype == "PLANNER_RESPONSE":
                    tcs = step.get("tool_calls") or []
                    if isinstance(tcs, list):
                        planner_tool_calls = [tc for tc in tcs if isinstance(tc, dict)]

                if stype == "GENERIC":
                    content = str(step.get("content") or "")
                    step_status = step.get("status")
                    is_candidate_bg = (
                        step_status in ("RUNNING", None, "")
                        and "Completed At:" not in content
                        and "Command exited with code" not in content
                        and "The command exited with code" not in content
                        and "Command output:" not in content
                        and ("Task logs are available at:" in content or "YOU MUST TAKE ONE OF THE FOLLOWING TWO ACTIONS:" in content or "Task Description:" in content)
                    )
                    m_bg = task_bg_pattern.search(content) if is_candidate_bg else None
                    if m_bg:
                        task_id = m_bg.group(1).strip()
                        is_own_task = True
                        if "/" in task_id:
                            path_parts = abs_p.split(os.sep)
                            if "brain" in path_parts:
                                brain_idx = path_parts.index("brain")
                                after_brain = path_parts[brain_idx + 1 : brain_idx + 2]
                                if after_brain:
                                    is_own_task = task_id.startswith(f"{after_brain[0]}/")
                        if is_own_task:
                            m_desc = task_desc_pattern.search(content)
                            desc = m_desc.group(1).strip() if m_desc else ""
                            if not desc.startswith(("Timer:", "Cron:")):
                                matched_tc = _pop_matching_planner_call(
                                    planner_tool_calls,
                                    desc,
                                    bidirectional=True,
                                    is_cmd_exit=False,
                                )
                                is_daemon = False
                                if matched_tc and matched_tc.get("name") in _CMD_TOOLS:
                                    raw_is_daemon = (matched_tc.get("args") or {}).get("IsDaemon")
                                    is_daemon = raw_is_daemon if isinstance(raw_is_daemon, bool) else (str(raw_is_daemon or "").strip().lower().strip('"\'') in ("true", "1", "yes"))
                                if not is_daemon and task_id not in active_bg_tasks:
                                    active_bg_tasks.append(task_id)

                    if "Command exited with code" in content or "Completed At:" in content:
                        is_cmd_exit = ("Command exited with code" in content or "Command output:" in content)
                        _pop_matching_planner_call(
                            planner_tool_calls,
                            content,
                            bidirectional=False,
                            is_cmd_exit=is_cmd_exit,
                            is_sync_completion=True,
                        )

                    m_cancel = task_cancel_pattern.search(content)
                    if m_cancel:
                        cancelled_id = m_cancel.group(1).strip()
                        _remove_matching_task_id(active_bg_tasks, cancelled_id)

        result = {
            "turn_id": turn_id,
            "lines_count": lines_count,
            "tokens": tokens,
            "first_system_sender": first_system_sender,
            "steps": steps,
            "active_bg_tasks": active_bg_tasks,
            "active_context_chars": active_context_chars,
            "has_valid_json_steps": has_valid_json_steps,
        }
        _TRANSCRIPT_CACHE[abs_p] = (st.st_mtime_ns, st.st_size, result)
        return result
    except Exception as exc:
        sys.stderr.write(f"Warning in parse_transcript: {exc}\n")
        return empty_result

def scan_transcript_header(transcript_path: str, max_lines: int = 10) -> dict:
    empty = {
        "turn_id": 0,
        "lines_scanned": 0,
        "tokens": [],
        "first_system_sender": None,
    }
    if not transcript_path or not os.path.exists(transcript_path):
        return empty

    tokens: list[str] = []
    first_system_sender: str | None = None
    turn_id = 0
    lines_scanned = 0
    token_pattern = re.compile(r'\[ANTIGRAVITY_TOKEN:([a-fA-F0-9\-]+)\]')
    sender_pattern = re.compile(r'\bsender=([0-9a-fA-F\-]{36})\b')

    try:
        with open(os.path.abspath(transcript_path), "r", encoding="utf-8", errors="replace") as f:
            while lines_scanned < max_lines:
                raw_line = f.readline(65536)
                if not raw_line:
                    break
                if not raw_line.endswith("\n"):
                    while True:
                        chunk = f.readline(65536)
                        if not chunk or chunk.endswith("\n"):
                            break
                line_str = raw_line.strip()
                if not line_str:
                    continue
                lines_scanned += 1
                try:
                    step = json.loads(line_str)
                except Exception:
                    if '"PLANNER_RESPONSE"' not in line_str and (
                        '"USER_INPUT"' in line_str or '"SYSTEM_MESSAGE"' in line_str
                    ):
                        for match in token_pattern.finditer(line_str):
                            tok = match.group(1)
                            if tok not in tokens:
                                tokens.append(tok)
                        if lines_scanned == 1 and '"SYSTEM_MESSAGE"' in line_str:
                            m = sender_pattern.search(line_str)
                            if m:
                                first_system_sender = m.group(1)
                    continue
                if not isinstance(step, dict):
                    continue
                source = str(step.get("source", ""))
                stype = step.get("type", "")
                if source.startswith("USER") and stype == "USER_INPUT":
                    turn_id = step.get("step_index", turn_id)
                if stype in ("USER_INPUT", "SYSTEM_MESSAGE"):
                    content = str(step.get("content") or "")
                    for match in token_pattern.finditer(content):
                        tok = match.group(1)
                        if tok not in tokens:
                            tokens.append(tok)
                if lines_scanned == 1 and source == "SYSTEM" and stype == "SYSTEM_MESSAGE":
                    content = str(step.get("content") or "")
                    m = sender_pattern.search(content)
                    if m:
                        first_system_sender = m.group(1)
    except Exception as exc:
        sys.stderr.write(f"Warning in scan_transcript_header: {exc}\n")

    return {
        "turn_id": turn_id,
        "lines_scanned": lines_scanned,
        "tokens": tokens,
        "first_system_sender": first_system_sender,
    }


def extract_active_bg_tasks(transcript_path: str) -> list[str]:
    if not transcript_path or not os.path.exists(transcript_path):
        return []
    return list(parse_transcript(transcript_path).get("active_bg_tasks") or [])


def validate_no_raw_log_dump(text: str) -> tuple[bool, str | None]:
    if not isinstance(text, str) or not text:
        return True, None
    if re.search(r"\x1b\[", text):
        return (
            False,
            "Attention Guard: Raw ANSI escape sequence detected in send_message; summarize cleanly without terminal logs.",
        )
    tb_frames = re.findall(r'File "[^"]+", line \d+', text)
    if len(tb_frames) >= 4:
        return (
            False,
            f"Attention Guard: Raw traceback ({len(tb_frames)} traceback frames detected) in send_message; summarize root cause concisely.",
        )
    if "=== test session starts ===" in text and len(text) > 2000:
        return (
            False,
            "Attention Guard: Raw pytest output ('=== test session starts ===' > 2,000 chars) detected in send_message; report concise test counts instead.",
        )
    return True, None


def is_subagent(data, ledger=None):
    conv_id = data.get("conversationId", "unknown") if isinstance(data, dict) else "unknown"
    transcript_path = data.get("transcriptPath", "") if isinstance(data, dict) else ""

    try:
        header = None
        if transcript_path and os.path.exists(transcript_path):
            header = scan_transcript_header(transcript_path, max_lines=10)
            allow_sender = os.environ.get("AGY_DISABLE_SENDER_FALLBACK") != "1"
            if (
                header["lines_scanned"] > 0
                and not header["tokens"]
                and (not allow_sender or not header["first_system_sender"])
            ):
                return False, False, 0, None, None

        if ledger is None:
            from ledger import Ledger
            ledger = Ledger()

        claimed_tok = ledger.get_claimed_token_by_conv(conv_id)
        if claimed_tok is not None:
            parent_conv_id = claimed_tok.get("parent_conv_id") or ""
            if parent_conv_id != conv_id:
                return (
                    True,
                    bool(claimed_tok.get("may_delegate", 0)),
                    int(claimed_tok.get("remaining_depth", 0)),
                    parent_conv_id or "unknown",
                    "0",
                )

        if header is None:
            return False, False, 0, None, None

        turn_id = header["turn_id"]
        tokens = header["tokens"]

        if tokens:
            for token in reversed(tokens):
                tok_row = ledger.get_token(token)
                found_source = tok_row is not None
                may_delegate = bool(tok_row.get("may_delegate", 0)) if tok_row else False
                remaining_depth = int(tok_row.get("remaining_depth", 0)) if tok_row else 0
                parent_conv_id = (tok_row.get("parent_conv_id") or "") if tok_row else ""
                parent_turn_id = "0"

                if not tok_row or not parent_conv_id:
                    with ledger._get_connection() as conn:
                        row = conn.execute(
                            "SELECT payload FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?",
                            (f'%"{token}"%',),
                        ).fetchone()
                    if row:
                        found_source = True
                        payload_data = json.loads(row[0])
                        may_delegate = bool(payload_data.get("may_delegate", may_delegate))
                        remaining_depth = int(payload_data.get("remaining_depth", remaining_depth))
                        parent_conv_id = str(payload_data.get("parent_conv_id") or parent_conv_id or "unknown")
                        parent_turn_id = str(payload_data.get("parent_turn_id") or "0")

                if not found_source:
                    continue

                if parent_conv_id and conv_id == parent_conv_id:
                    continue

                newly_claimed = (
                    tok_row is None
                    or tok_row.get("claimed", 0) == 0
                    or tok_row.get("claimed_by") is None
                )
                if ledger.claim_token(token, conv_id):
                    if newly_claimed:
                        ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "WORK_CLAIMED")
                    return (
                        True,
                        may_delegate,
                        remaining_depth,
                        parent_conv_id or "unknown",
                        parent_turn_id,
                    )

        if os.environ.get("AGY_DISABLE_SENDER_FALLBACK") != "1":
            parent_conv_id = header.get("first_system_sender")
            if parent_conv_id and parent_conv_id != conv_id:
                return True, False, 0, parent_conv_id, "0"

    except Exception as exc:
        sys.stderr.write(f"Error in is_subagent: {exc}\n")

    return False, False, 0, None, None


