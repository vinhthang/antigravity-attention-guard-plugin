import sys
import os
import json
import re
import shlex
from ledger import Ledger

DEFAULT_THINKING_MODELS = ["opus", "gemini-4", "gemini 4"]

def get_primary_model(data=None):
    if isinstance(data, dict):
        model = data.get("modelName") or data.get("model") or data.get("model_name")
        if model:
            return str(model).strip()
    env_model = os.environ.get("AGY_PRIMARY_MODEL") or os.environ.get("ANTIGRAVITY_MODEL")
    if env_model:
        return env_model.strip()
    return ""

def is_thinking_model(model_name):
    if not model_name or not isinstance(model_name, str):
        return False
    env_models = os.environ.get("ATTENTION_GUARD_THINKING_MODELS")
    if env_models:
        candidates = [m.strip().lower() for m in env_models.split(",") if m.strip()]
    else:
        candidates = [m.lower() for m in DEFAULT_THINKING_MODELS]
    name_lower = model_name.lower()
    return any(cand in name_lower for cand in candidates)

def is_markdown_file(file_path):
    if not file_path or not isinstance(file_path, str):
        return False
    path_lower = file_path.lower()
    return path_lower.endswith(".md") or path_lower.endswith(".markdown")

def is_build_command(cmd_str):
    if not cmd_str or not isinstance(cmd_str, str):
        return False
    try:
        tokens = shlex.split(cmd_str)
    except Exception:
        tokens = cmd_str.split()
    while tokens and tokens[0] == "rtk":
        tokens.pop(0)
    if not tokens:
        return False

    bin_name = os.path.basename(tokens[0]).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if bin_name.endswith(ext):
            bin_name = bin_name[:-len(ext)]
            break

    # Direct build tools / generators
    if bin_name in {"make", "cmake", "ninja"}:
        return True

    # Python pip
    if bin_name in {"pip", "pip3"}:
        return True

    # python -m pip ... or python setup.py ...
    if bin_name in {"python", "python3"}:
        i = 1
        while i < len(tokens):
            arg = tokens[i]
            if arg == "-m":
                if i + 1 < len(tokens):
                    return tokens[i + 1].lower() == "pip"
                return False
            if arg.startswith("-m") and len(arg) > 2:
                return arg[2:].lower() == "pip"
            if arg == "-c":
                return False
            if arg in {"-W", "-X", "--check-hash-based-pycs"}:
                i += 2
                continue
            if arg.startswith("-"):
                i += 1
                continue
            script_base = os.path.basename(arg).lower()
            if script_base == "setup.py":
                return any(t.lower() in {"build", "install", "bdist_wheel", "sdist", "develop"} for t in tokens[i + 1:])
            return False
        return False

    # Cargo
    if bin_name == "cargo":
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"build", "check", "install"} for t in lower_tokens):
            return True

    # Go
    if bin_name == "go":
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"build", "install"} for t in lower_tokens):
            return True

    # Node / JS
    if bin_name in {"npm", "pnpm", "yarn", "bun"}:
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"install", "i", "ci", "add", "build", "compile"} for t in lower_tokens):
            return True
        if "run" in lower_tokens and any(t in {"build", "compile"} for t in lower_tokens):
            return True

    # Java / JVM build tools
    if bin_name in {"mvn", "mvnw"}:
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"compile", "install", "package", "verify", "build"} for t in lower_tokens):
            return True

    if bin_name in {"gradle", "gradlew"}:
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"build", "compile", "assemble", "install"} for t in lower_tokens):
            return True

    return False

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

_TRANSCRIPT_CACHE = {}

def clear_transcript_cache():
    _TRANSCRIPT_CACHE.clear()

def parse_transcript(transcript_path: str) -> dict:
    empty_result = {
        "turn_id": 0,
        "lines_count": 0,
        "tokens": [],
        "first_system_sender": None,
        "steps": [],
        "active_bg_tasks": [],
        "active_timers_since_wakeup": [],
        "has_delegation_in_turn": False,
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
    active_timers_since_wakeup = []
    current_turn_delegated = False
    active_context_chars = 0
    has_valid_json_steps = False
    planner_tool_calls = []
    valid_schedule_calls = []

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
                        active_context_chars += len(str(step.get("content") or ""))
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
                    current_turn_delegated = False
                    active_timers_since_wakeup.clear()

                if source == "SYSTEM" and stype == "SYSTEM_MESSAGE":
                    active_timers_since_wakeup.clear()
                    content = str(step.get("content") or "")
                    for m in system_sender_task_pattern.finditer(content):
                        tid = m.group(1).strip()
                        if tid in active_bg_tasks:
                            active_bg_tasks.remove(tid)
                    for m in system_task_finish_pattern.finditer(content):
                        tid = m.group(1).strip()
                        if tid in active_bg_tasks:
                            active_bg_tasks.remove(tid)

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
                        if any(
                            isinstance(tc, dict)
                            and tc.get("name") in ("invoke_subagent", "default_api:invoke_subagent", "send_message", "default_api:send_message")
                            for tc in tcs
                        ):
                            current_turn_delegated = True
                        for tc in tcs:
                            if isinstance(tc, dict) and tc.get("name") in ("schedule", "default_api:schedule"):
                                args = tc.get("args") or {}
                                dur_raw = args.get("DurationSeconds")
                                cron_raw = args.get("CronExpression")
                                cond_raw = str(args.get("TimerCondition") or "never").strip().lower().strip('"\'')
                                # REQ-028: Watchdog timer requires DurationSeconds (>= 60s), not a cron schedule
                                if not cron_raw and dur_raw is not None:
                                    try:
                                        dur_val = int(dur_raw)
                                        if dur_val >= 60 and cond_raw in ("any", "never"):
                                            valid_schedule_calls.append(tc)
                                            call_key = f"schedule_call_{step.get('step_index', idx)}"
                                            if call_key not in active_timers_since_wakeup:
                                                active_timers_since_wakeup.append(call_key)
                                    except (ValueError, TypeError) as conv_err:
                                        _ = conv_err

                if stype == "GENERIC":
                    content = str(step.get("content") or "")
                    m_bg = task_bg_pattern.search(content) if ("Command output:" not in content and "Command exited with code" not in content) else None
                    if m_bg:
                        task_id = m_bg.group(1).strip()
                        is_own_task = True
                        if "/" in task_id:
                            path_parts = abs_p.split(os.sep)
                            if "brain" in path_parts:
                                brain_idx = path_parts.index("brain")
                                if brain_idx + 1 < len(path_parts):
                                    conv_from_path = path_parts[brain_idx + 1]
                                    is_own_task = task_id.startswith(f"{conv_from_path}/")
                        if is_own_task:
                            m_desc = task_desc_pattern.search(content)
                            desc = m_desc.group(1).strip() if m_desc else ""
                            if desc.startswith("Timer:"):
                                if valid_schedule_calls:
                                    valid_schedule_calls.pop(0)
                                    if task_id not in active_timers_since_wakeup:
                                        active_timers_since_wakeup.append(task_id)
                            elif not desc.startswith("Cron:"):
                                matched_tc = None
                                if planner_tool_calls:
                                    for i, tc in enumerate(planner_tool_calls):
                                        if tc.get("name") in ("run_command", "default_api:run_command"):
                                            tc_args = tc.get("args") or {}
                                            tc_summary = str(tc_args.get("toolSummary") or "").strip().strip('"\'')
                                            tc_cmd = str(tc_args.get("CommandLine") or "").strip().strip('"\'')
                                            if (tc_summary and (tc_summary in desc or desc in tc_summary)) or \
                                               (tc_cmd and (tc_cmd in desc or desc in tc_cmd)):
                                                matched_tc = planner_tool_calls.pop(i)
                                                break
                                    if not matched_tc:
                                        for i, tc in enumerate(planner_tool_calls):
                                            if tc.get("name") in ("run_command", "default_api:run_command"):
                                                matched_tc = planner_tool_calls.pop(i)
                                                break
                                raw_is_daemon = (matched_tc.get("args") or {}).get("IsDaemon") if matched_tc else False
                                is_daemon = raw_is_daemon if isinstance(raw_is_daemon, bool) else (str(raw_is_daemon or "").strip().lower().strip('"\'') in ("true", "1", "yes"))
                                if not is_daemon and task_id not in active_bg_tasks:
                                    active_bg_tasks.append(task_id)

                    if "Command exited with code" in content or "Completed At:" in content:
                        for i, tc in enumerate(planner_tool_calls):
                            if tc.get("name") in ("run_command", "default_api:run_command"):
                                tc_args = tc.get("args") or {}
                                tc_summary = str(tc_args.get("toolSummary") or "").strip().strip('"\'')
                                tc_cmd = str(tc_args.get("CommandLine") or "").strip().strip('"\'')
                                if (tc_summary and tc_summary in content) or (tc_cmd and tc_cmd in content):
                                    planner_tool_calls.pop(i)
                                    break
                        else:
                            for i, tc in enumerate(planner_tool_calls):
                                if tc.get("name") in ("run_command", "default_api:run_command"):
                                    planner_tool_calls.pop(i)
                                    break

                    m_cancel = task_cancel_pattern.search(content)
                    if m_cancel:
                        cancelled_id = m_cancel.group(1).strip()
                        if cancelled_id in active_bg_tasks:
                            active_bg_tasks.remove(cancelled_id)
                        if cancelled_id in active_timers_since_wakeup:
                            active_timers_since_wakeup.remove(cancelled_id)
                            for t in reversed(list(active_timers_since_wakeup)):
                                if t.startswith("schedule_call_"):
                                    active_timers_since_wakeup.remove(t)
                                    break

        result = {
            "turn_id": turn_id,
            "lines_count": lines_count,
            "tokens": tokens,
            "first_system_sender": first_system_sender,
            "steps": steps,
            "active_bg_tasks": active_bg_tasks,
            "active_timers_since_wakeup": active_timers_since_wakeup,
            "has_delegation_in_turn": current_turn_delegated,
            "active_context_chars": active_context_chars,
            "has_valid_json_steps": has_valid_json_steps,
        }
        _TRANSCRIPT_CACHE[abs_p] = (st.st_mtime_ns, st.st_size, result)
        return result
    except Exception as exc:
        sys.stderr.write(f"Warning in parse_transcript: {exc}\n")
        return empty_result

def get_turn_state(transcript_path):
    parsed = parse_transcript(transcript_path)
    return parsed["turn_id"], parsed["lines_count"]

def is_subagent(data, ledger=None):
    transcript_path = data.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        return False, False, 0, None, None

    conv_id = data.get("conversationId", "unknown")
    parsed = parse_transcript(transcript_path)
    turn_id = parsed["turn_id"]
    tokens = parsed["tokens"]

    try:
        if tokens:
            if ledger is None:
                ledger = Ledger()
            for token in reversed(tokens):
                with ledger._get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT payload FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?",
                        (f'%"{token}"%',),
                    )
                    row = cursor.fetchone()
                    if row:
                        payload_data = json.loads(row[0])
                        may_delegate = payload_data.get("may_delegate", False)
                        remaining_depth = payload_data.get("remaining_depth", 0)
                        parent_conv_id = payload_data.get("parent_conv_id", "unknown")
                        parent_turn_id = payload_data.get("parent_turn_id", "unknown")

                        if conv_id == parent_conv_id:
                            continue

                        w_row = conn.execute(
                            "SELECT parent_conv_id, parent_turn_id FROM work_items WHERE work_id = ?",
                            (token,)
                        ).fetchone()
                        if w_row:
                            if w_row[0]:
                                parent_conv_id = w_row[0]
                            if w_row[1]:
                                parent_turn_id = w_row[1]

                        t_row = conn.execute(
                            "SELECT claimed, claimed_by FROM tokens WHERE token_id = ?",
                            (token,)
                        ).fetchone()
                        newly_claimed = (t_row is None or t_row[0] == 0 or t_row[1] is None)

                        if ledger.claim_token(token, conv_id):
                            if newly_claimed:
                                ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "WORK_CLAIMED")
                                ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "RUNNING")
                            return True, may_delegate, remaining_depth, parent_conv_id, parent_turn_id

        if os.environ.get("AGY_DISABLE_SENDER_FALLBACK") != "1":
            parent_conv_id = parsed.get("first_system_sender")
            if parent_conv_id and parent_conv_id != conv_id:
                parent_turn_id = "0"
                if ledger is None:
                    ledger = Ledger()
                with ledger._get_connection() as conn:
                    w_row = conn.execute(
                        """
                        SELECT w.parent_conv_id, w.parent_turn_id
                        FROM work_items w
                        LEFT JOIN tokens t ON w.work_id = t.token_id
                        WHERE t.claimed_by = ? OR w.work_id = ?
                        ORDER BY w.updated_at DESC, w.created_at DESC
                        LIMIT 1
                        """,
                        (conv_id, conv_id)
                    ).fetchone()
                    if w_row:
                        if w_row[0]:
                            parent_conv_id = w_row[0]
                        if w_row[1]:
                            parent_turn_id = w_row[1]
                return True, False, 0, parent_conv_id, parent_turn_id

    except Exception as exc:
        sys.stderr.write(f"Error in is_subagent: {exc}\n")

    return False, False, 0, None, None


