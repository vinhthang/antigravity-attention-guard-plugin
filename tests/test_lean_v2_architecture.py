import importlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_script_module(module_name: str, script_filename: str):
    spec = importlib.util.spec_from_file_location(module_name, str(SCRIPTS_DIR / script_filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_hook(mod, payload: dict) -> dict:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    mod.main(argv=[mod.__name__], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())


def _setup_isolated_env(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGY_DISABLE_METRICS_PUSH", "1")
    import ledger
    importlib.reload(ledger)
    import common
    importlib.reload(common)
    common.clear_transcript_cache()
    return ledger, common


def _seed_subagent(
    ledger_mod,
    tmp_path: Path,
    token: str,
    conv_id: str = "sub-conv-1",
    parent_conv_id: str = "parent-conv-1",
    may_delegate: bool = False,
    remaining_depth: int = 0,
    in_system_message: bool = False,
    extra_steps: list[dict] | None = None,
) -> Path:
    db = ledger_mod.Ledger()
    db.issue_token(
        token,
        may_delegate=may_delegate,
        remaining_depth=remaining_depth,
        parent_conv_id=parent_conv_id,
    )
    transcript = tmp_path / f"{conv_id}.jsonl"
    if in_system_message:
        header = {
            "step_index": 0,
            "source": "SYSTEM",
            "type": "SYSTEM_MESSAGE",
            "content": f"<SYSTEM_MESSAGE>[ANTIGRAVITY_TOKEN:{token}]\nMission.</SYSTEM_MESSAGE>",
        }
    else:
        header = {
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "content": f"[ANTIGRAVITY_TOKEN:{token}]\n\nDo the work.",
        }
    lines = [json.dumps(header)]
    for st in extra_steps or []:
        lines.append(json.dumps(st))
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return transcript


def test_ac_042_1_hooks_topology_deleted_bloat_and_primary_autonomy(tmp_path, monkeypatch):
    _setup_isolated_env(tmp_path, monkeypatch)

    hooks_data = json.loads((REPO_ROOT / "hooks.json").read_text(encoding="utf-8"))
    all_events = set()
    enforce_matchers = []
    inject_matchers = []
    for group_val in hooks_data.values():
        assert isinstance(group_val, dict)
        for ev_name, entries in group_val.items():
            all_events.add(ev_name)
            for entry in entries:
                matcher = entry.get("matcher", "")
                for hook in entry.get("hooks", []):
                    cmd = hook.get("command", "")
                    if "enforce-delegation.py" in cmd:
                        enforce_matchers.append(matcher)
                    if "inject-rules.py" in cmd:
                        inject_matchers.append(matcher)

    assert all_events == {"PreToolUse"}
    assert "PreInvocation" not in all_events
    assert "PostToolUse" not in all_events
    assert "Stop" not in all_events
    assert len(enforce_matchers) == 1
    assert "read_file" not in enforce_matchers[0]
    assert ".*" != enforce_matchers[0]
    assert inject_matchers == ["invoke_subagent"]

    for retired in [
        REPO_ROOT / "scripts" / "attention-check.py",
        REPO_ROOT / "scripts" / "attention-refresh.py",
        REPO_ROOT / "scripts" / "record-tool-result.py",
        REPO_ROOT / "scripts" / "fsm.py",
        REPO_ROOT / "scripts" / "payload_validator.py",
        REPO_ROOT / "schemas",
    ]:
        assert not retired.exists(), f"Retired artifact still exists: {retired}"

    enforce_mod = _load_script_module("enforce_delegation_v2", "enforce-delegation.py")
    transcript = tmp_path / "primary.jsonl"
    transcript.write_text(
        json.dumps({"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Fix bug"}) + "\n",
        encoding="utf-8",
    )

    for model_name in ("Gemini 4 Carbon (High)", "Claude Opus 4.6"):
        for tool_name, args in [
            ("write_file", {"Path": str(tmp_path / "app.py"), "Content": "print('ok')\n"}),
            ("edit_file", {"Path": str(tmp_path / "app.py"), "Target": "ok", "Replacement": "yes"}),
            ("run_command", {"CommandLine": "rtk pytest tests/"}),
            ("run_command", {"CommandLine": "mvn test"}),
            ("run_command", {"CommandLine": "git commit -m 'feat: lean v2'"}),
        ]:
            res = _run_hook(
                enforce_mod,
                {
                    "conversationId": "primary-conv-1",
                    "transcriptPath": str(transcript),
                    "modelName": model_name,
                    "toolCall": {"name": tool_name, "args": args},
                },
            )
            assert res == {"decision": "allow"}, f"Unexpected denial for {model_name} / {tool_name}: {res}"


def test_ac_042_2_destructive_and_test_tampering_guards_with_attributed_telemetry(tmp_path, monkeypatch):
    ledger_mod, _ = _setup_isolated_env(tmp_path, monkeypatch)
    enforce_mod = _load_script_module("enforce_delegation_v2", "enforce-delegation.py")

    primary_transcript = tmp_path / "primary.jsonl"
    primary_transcript.write_text(
        json.dumps({"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "hi"}) + "\n",
        encoding="utf-8",
    )
    sub_token = str(uuid.uuid4())
    sub_transcript = _seed_subagent(ledger_mod, tmp_path, sub_token, conv_id="sub-destructive")

    destructive_cmds = [
        "git reset --hard",
        "git clean -fd",
        "git checkout .",
        "git restore .",
        "git push --force",
        "rm -rf /",
    ]
    tamper_snippets = [
        ("@pytest.mark.skip\ndef test_x(): pass\n", "tests/test_sample.py"),
        ("def test_x():\n    pytest.skip('later')\n", "tests/test_sample.py"),
        ("it.skip('works', () => {});\n", "tests/sample.test.ts"),
        ("func TestX(t *testing.T) { t.Skip() }\n", "pkg/sample_test.go"),
        ("def test_x():\n    assert True\n", "tests/test_sample.py"),
    ]

    for is_sub_case, conv_id, tr_path in [
        (False, "primary-destructive", primary_transcript),
        (True, "sub-destructive", sub_transcript),
    ]:
        for cmd in destructive_cmds:
            res = _run_hook(
                enforce_mod,
                {
                    "conversationId": conv_id,
                    "transcriptPath": str(tr_path),
                    "toolCall": {"name": "run_command", "args": {"CommandLine": cmd}},
                },
            )
            assert res["decision"] == "deny", f"Expected deny for {cmd} (is_sub={is_sub_case})"

        for content, target_file in tamper_snippets:
            res = _run_hook(
                enforce_mod,
                {
                    "conversationId": conv_id,
                    "transcriptPath": str(tr_path),
                    "toolCall": {
                        "name": "write_file",
                        "args": {"Path": str(tmp_path / target_file), "Content": content},
                    },
                },
            )
            assert res["decision"] == "deny", f"Expected deny for tamper {content!r} (is_sub={is_sub_case})"

    with ledger_mod.Ledger()._get_connection() as conn:
        rows = conn.execute("SELECT payload FROM events WHERE type = 'PRIMARY_TOOL_DENIED'").fetchall()
    assert len(rows) == 2 * (len(destructive_cmds) + len(tamper_snippets))
    payloads = [json.loads(r["payload"]) for r in rows]
    assert any(p["is_sub"] is False and p["tool"] == "run_command" and p["reason"] for p in payloads)
    assert any(p["is_sub"] is True and p["tool"] == "write_file" and p["reason"] for p in payloads)


def test_ac_043_1_and_ac_043_2_model_preservation_o1_header_scan_and_3mb_latency(tmp_path, monkeypatch):
    ledger_mod, common_mod = _setup_isolated_env(tmp_path, monkeypatch)
    inject_mod = _load_script_module("inject_rules_v2", "inject-rules.py")

    parent_tr = tmp_path / "parent.jsonl"
    parent_tr.write_text(
        json.dumps({"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Run task"}) + "\n",
        encoding="utf-8",
    )

    # 1. Model preservation ("inherit", "flash", omitted) + >12k offload
    res_inherit = _run_hook(
        inject_mod,
        {
            "conversationId": "parent-conv",
            "transcriptPath": str(parent_tr),
            "modelName": "Gemini 4 Carbon (High)",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "self", "Model": "inherit", "Prompt": "Small prompt"},
            },
        },
    )
    assert res_inherit["decision"] == "allow"
    assert res_inherit["overwrite"]["Model"] == "inherit"
    assert "[ANTIGRAVITY_TOKEN:" in res_inherit["overwrite"]["Prompt"]

    res_flash = _run_hook(
        inject_mod,
        {
            "conversationId": "parent-conv",
            "transcriptPath": str(parent_tr),
            "modelName": "Claude Opus 4.6",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "DeepCoder", "Model": "flash", "Prompt": "Coord prompt"},
            },
        },
    )
    assert res_flash["overwrite"]["Model"] == "flash"

    big_prompt = "X" * 13000
    res_omitted = _run_hook(
        inject_mod,
        {
            "conversationId": "parent-conv",
            "transcriptPath": str(parent_tr),
            "modelName": "Gemini 4 Argon (High)",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"TypeName": "self", "Prompt": big_prompt},
            },
        },
    )
    assert "Model" not in res_omitted["overwrite"]
    assert "# YOUR EVIDENCE" in res_omitted["overwrite"]["Prompt"]
    assert len(res_omitted["overwrite"]["Prompt"]) < 6000

    # Swarm untouched
    res_swarm = _run_hook(
        inject_mod,
        {
            "conversationId": "parent-conv",
            "transcriptPath": str(parent_tr),
            "toolCall": {
                "name": "swarm",
                "args": {"action": "add", "name": "worker1", "brief": "Do work"},
            },
        },
    )
    assert res_swarm == {"decision": "allow"}

    # 2. Subagent detection in USER_INPUT and SYSTEM_MESSAGE + SQLite claimed_by cache
    tok_user = str(uuid.uuid4())
    tr_user = _seed_subagent(ledger_mod, tmp_path, tok_user, conv_id="child-user", in_system_message=False)
    assert common_mod.is_subagent({"conversationId": "child-user", "transcriptPath": str(tr_user)}) == (
        True, False, 0, "parent-conv-1", "0"
    )
    # Cached hit even without transcript path lines beyond cache
    with ledger_mod.Ledger()._get_connection() as conn:
        row = conn.execute("SELECT claimed, claimed_by FROM tokens WHERE token_id = ?", (tok_user,)).fetchone()
        assert row["claimed"] == 1
        assert row["claimed_by"] == "child-user"

    tok_sys = str(uuid.uuid4())
    tr_sys = _seed_subagent(
        ledger_mod,
        tmp_path,
        tok_sys,
        conv_id="child-sys",
        may_delegate=True,
        remaining_depth=1,
        in_system_message=True,
    )
    assert common_mod.is_subagent({"conversationId": "child-sys", "transcriptPath": str(tr_sys)}) == (
        True, True, 1, "parent-conv-1", "0"
    )

    # 3. AC-043-2: Primary Agent own transcript with child token in PLANNER_RESPONSE -> is_sub False
    tok_child = str(uuid.uuid4())
    ledger_mod.Ledger().issue_token(tok_child, may_delegate=False, remaining_depth=0, parent_conv_id="primary-self")
    tr_self = tmp_path / "primary-self.jsonl"
    tr_self.write_text(
        "\n".join([
            json.dumps({"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "go"}),
            json.dumps({
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "content": "",
                "tool_calls": [{"name": "invoke_subagent", "args": {"Prompt": f"[ANTIGRAVITY_TOKEN:{tok_child}]\nTask"}}],
            }),
        ]) + "\n",
        encoding="utf-8",
    )
    res_self = common_mod.is_subagent({"conversationId": "primary-self", "transcriptPath": str(tr_self)})
    assert res_self[:4] == (False, False, 0, None)

    # 4. AC-043-1: O(1) < 5.0 ms in-process check + < 100.0 ms real subprocess check on 3.2 MB transcript
    big_tr = tmp_path / "big_primary.jsonl"
    filler = "A" * 2100
    with open(big_tr, "w", encoding="utf-8") as f:
        f.write(json.dumps({"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "start"}) + "\n")
        for i in range(1, 1501):
            f.write(json.dumps({"step_index": i, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": filler}) + "\n")
    assert big_tr.stat().st_size >= 3_100_000

    ledger_mod.Ledger()
    hook_dict = {
        "conversationId": "big-primary-conv",
        "transcriptPath": str(big_tr),
        "modelName": "Gemini 4 Carbon (High)",
        "toolCall": {"name": "write_file", "args": {"Path": str(tmp_path / "x.py"), "Content": "x = 1\n"}},
    }
    enforce_mod = _load_script_module("enforce_bench_v2", "enforce-delegation.py")
    t_inproc = time.perf_counter()
    assert _run_hook(enforce_mod, hook_dict) == {"decision": "allow"}
    inproc_ms = (time.perf_counter() - t_inproc) * 1000.0
    assert inproc_ms < 5.0, f"3.2MB in-process enforce-delegation took {inproc_ms:.2f} ms (>= 5.0 ms; O(N) regression!)"

    hook_payload = json.dumps(hook_dict)
    env = dict(os.environ)
    env["AGY_APP_DATA_DIR"] = str(tmp_path)
    env["AGY_DISABLE_METRICS_PUSH"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    samples_ms = []
    for _ in range(3):
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "enforce-delegation.py")],
            input=hook_payload,
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
        assert json.loads(proc.stdout.strip()) == {"decision": "allow"}
    elapsed_ms = sorted(samples_ms)[1]
    assert elapsed_ms < 100.0, f"3.2MB enforce-delegation median subprocess took {elapsed_ms:.1f} ms (>= 100 ms; samples={samples_ms})"


def test_ac_044_1_and_ac_044_2_subagent_recursion_doom_loop_and_send_message_fences(tmp_path, monkeypatch):
    ledger_mod, _ = _setup_isolated_env(tmp_path, monkeypatch)
    enforce_mod = _load_script_module("enforce_delegation_v2", "enforce-delegation.py")
    inject_mod = _load_script_module("inject_rules_v2", "inject-rules.py")

    # Executor send_message with plain Markdown and simple JSON (never executes verify_cmd)
    exec_tok = str(uuid.uuid4())
    exec_tr = _seed_subagent(ledger_mod, tmp_path, exec_tok, conv_id="exec-1", may_delegate=False, remaining_depth=0)

    for msg in [
        "Done: 10/10 passed.",
        json.dumps({"ok": True, "verify_cmd": "touch should_never_run"}),
    ]:
        res = _run_hook(
            enforce_mod,
            {
                "conversationId": "exec-1",
                "transcriptPath": str(exec_tr),
                "toolCall": {"name": "send_message", "args": {"Recipient": "parent-conv-1", "Message": msg}},
            },
        )
        assert res == {"decision": "allow"}
    assert not (tmp_path / "should_never_run").exists()

    # Coordinator (DeepCoder, remaining_depth=1) allowed invoke_subagent (leaf depth=0), denied run_workflow/swarm
    coord_tok = str(uuid.uuid4())
    coord_tr = _seed_subagent(ledger_mod, tmp_path, coord_tok, conv_id="coord-1", may_delegate=True, remaining_depth=1)
    assert _run_hook(
        enforce_mod,
        {
            "conversationId": "coord-1",
            "transcriptPath": str(coord_tr),
            "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "self", "Prompt": "leaf"}},
        },
    ) == {"decision": "allow"}

    coord_inject = _run_hook(
        inject_mod,
        {
            "conversationId": "coord-1",
            "transcriptPath": str(coord_tr),
            "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "DeepCoder", "Prompt": "leaf"}},
        },
    )
    assert coord_inject["decision"] == "allow"
    with ledger_mod.Ledger()._get_connection() as conn:
        newest = conn.execute("SELECT may_delegate, remaining_depth FROM tokens WHERE parent_conv_id = 'coord-1'").fetchone()
        assert newest["may_delegate"] == 0
        assert newest["remaining_depth"] == 0

    for forbidden in ["run_workflow", "swarm"]:
        res = _run_hook(
            enforce_mod,
            {
                "conversationId": "coord-1",
                "transcriptPath": str(coord_tr),
                "toolCall": {"name": forbidden, "args": {}},
            },
        )
        assert res["decision"] == "deny"

    # Executor denied invoke_subagent, manage_subagents, run_workflow, swarm
    for forbidden in ["invoke_subagent", "manage_subagents", "run_workflow", "swarm"]:
        res = _run_hook(
            enforce_mod,
            {
                "conversationId": "exec-1",
                "transcriptPath": str(exec_tr),
                "toolCall": {"name": forbidden, "args": {}},
            },
        )
        assert res["decision"] == "deny"

    # Doom-loop circuit breaker (3rd identical / POLL_PROC / POLL_FILE denied + BREAKER_STATE_CHANGE, reset on file edit)
    for poll_cmds in [
        ["pgrep -fl my_worker", "pgrep -f my_worker", "pgrep my_worker"],
        ["tail -n 10 /tmp/a.log", "tail -n 50 /tmp/a.log", "wc -l /tmp/a.log"],
    ]:
        for i, cmd in enumerate(poll_cmds):
            res = _run_hook(
                enforce_mod,
                {
                    "conversationId": "exec-1",
                    "transcriptPath": str(exec_tr),
                    "toolCall": {"name": "run_command", "args": {"CommandLine": cmd}},
                },
            )
            expected = "deny" if i == 2 else "allow"
            assert res["decision"] == expected, f"Expected {expected} at index {i} for {cmd}"
        # Reset via file edit
        assert _run_hook(
            enforce_mod,
            {
                "conversationId": "exec-1",
                "transcriptPath": str(exec_tr),
                "toolCall": {"name": "edit_file", "args": {"Path": str(tmp_path / "f.py"), "Target": "a", "Replacement": "b"}},
            },
        ) == {"decision": "allow"}

    with ledger_mod.Ledger()._get_connection() as conn:
        breaker_events = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'BREAKER_STATE_CHANGE'").fetchone()[0]
    assert breaker_events >= 2

    # Active background task fence on send_message
    bg_tok = str(uuid.uuid4())
    bg_tr = _seed_subagent(
        ledger_mod,
        tmp_path,
        bg_tok,
        conv_id="exec-bg",
        extra_steps=[
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "content": "",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "sleep 60", "IsDaemon": False}}],
            },
            {
                "step_index": 2,
                "source": "SYSTEM",
                "type": "GENERIC",
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: exec-bg/task-1\nTask Description: sleep 60",
            },
        ],
    )
    res_bg = _run_hook(
        enforce_mod,
        {
            "conversationId": "exec-bg",
            "transcriptPath": str(bg_tr),
            "toolCall": {"name": "send_message", "args": {"Recipient": "parent-conv-1", "Message": "Done."}},
        },
    )
    assert res_bg["decision"] == "deny"

    # Raw log dump guards (ANSI, >=4 traceback frames, >2000 char pytest dump)
    bad_messages = [
        "Build output:\n\x1b[31mFAILED\x1b[0m",
        "Traceback (most recent call last):\n"
        '  File "a.py", line 1, in <module>\n'
        '  File "b.py", line 2, in f\n'
        '  File "c.py", line 3, in g\n'
        '  File "d.py", line 4, in h\n'
        "ValueError: boom",
        "============================= test session starts ==============================\n" + ("F" * 2100),
    ]
    for bad in bad_messages:
        res_bad = _run_hook(
            enforce_mod,
            {
                "conversationId": "exec-1",
                "transcriptPath": str(exec_tr),
                "toolCall": {"name": "send_message", "args": {"Recipient": "parent-conv-1", "Message": bad}},
            },
        )
        assert res_bad["decision"] == "deny", f"Expected raw log dump deny for {bad[:40]!r}"


def test_ac_045_1_and_ac_045_2_sqlite_v3_migration_diagnostics_and_missing_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGY_DISABLE_METRICS_PUSH", "1")

    # 1. Missing DB clean exit (exit 0)
    env = dict(os.environ)
    env["AGY_APP_DATA_DIR"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    diag_missing = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "diagnostics.py"), "--metrics", "--json"],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert json.loads(diag_missing.stdout.strip()) == {
        "PRIMARY_TOOL_DENIED": 0,
        "primary_denials": 0,
        "subagent_denials": 0,
        "denials_by_tool": {},
    }
    sync_missing = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "sync_metrics.py"), "--dry-run"],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert sync_missing.returncode == 0

    # 2. Legacy SCHEMA_VERSION = 2 -> 3 migration preserving rows
    db_path = tmp_path / "attention_guard.db"
    now = time.time()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        f"""
        CREATE TABLE tokens (token_id TEXT PRIMARY KEY, claimed INTEGER DEFAULT 0, claimed_by TEXT, created_at REAL);
        CREATE TABLE events (event_id TEXT PRIMARY KEY, type TEXT, payload TEXT, created_at REAL);
        INSERT INTO tokens (token_id, claimed, claimed_by, created_at) VALUES ('tok-v2', 1, 'sub-v2', {now - 60.0});
        INSERT INTO events (event_id, type, payload, created_at) VALUES
            ('ev-p', 'PRIMARY_TOOL_DENIED', '{{"tool":"run_command","is_sub":false,"reason":"bad"}}', {now - 59.0}),
            ('ev-s', 'PRIMARY_TOOL_DENIED', '{{"tool":"write_file","is_sub":true,"reason":"skip"}}', {now - 58.0});
        PRAGMA user_version = 2;
        """
    )
    conn.close()

    import ledger
    importlib.reload(ledger)
    ledger._INITIALIZED_DBS.clear()
    db = ledger.Ledger()
    assert ledger.SCHEMA_VERSION == 3

    with db._get_connection() as check_conn:
        assert check_conn.execute("PRAGMA user_version").fetchone()[0] == 3
        cols = {r["name"] for r in check_conn.execute("PRAGMA table_info(tokens)").fetchall()}
        assert {"token_id", "claimed", "claimed_by", "may_delegate", "remaining_depth", "parent_conv_id", "created_at"} <= cols
        tok_row = check_conn.execute("SELECT token_id, claimed_by FROM tokens WHERE token_id = 'tok-v2'").fetchone()
        assert tok_row["claimed_by"] == "sub-v2"

    diag_ok = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "diagnostics.py"), "--metrics", "--json"],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    metrics = json.loads(diag_ok.stdout.strip())
    assert metrics == {
        "PRIMARY_TOOL_DENIED": 2,
        "primary_denials": 1,
        "subagent_denials": 1,
        "denials_by_tool": {"run_command": 1, "write_file": 1},
    }


def test_ac_046_1_and_ac_046_2_lean_surface_and_deploy_pruning(tmp_path, monkeypatch):
    _setup_isolated_env(tmp_path, monkeypatch)

    agents_text = (REPO_ROOT / "rules" / "AGENTS.md").read_text(encoding="utf-8")
    assert len(agents_text) <= 4000
    assert "diagnostics.py" in agents_text
    assert "--metrics --json" in agents_text
    assert "Zero Silent False-Cleans" in agents_text
    assert "attention-metrics" not in agents_text
    assert "git-worktree-sandbox" in agents_text
    for forbidden in ("payload_validator.py", "DurationSeconds=300", "/Users/thanghoang"):
        assert forbidden not in agents_text

    plugin_meta = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
    assert plugin_meta["version"] == "2.0.0"

    target_dir = tmp_path / "deployed-plugin"
    (target_dir / "scripts").mkdir(parents=True)
    (target_dir / "schemas").mkdir(parents=True)
    (target_dir / "scripts" / "attention-check.py").write_text("# stale\n", encoding="utf-8")
    (target_dir / "scripts" / "fsm.py").write_text("# stale\n", encoding="utf-8")
    (target_dir / "schemas" / "executor-payload.json").write_text("{}\n", encoding="utf-8")
    (target_dir / "skills" / "attention-metrics").mkdir(parents=True)
    (target_dir / "skills" / "attention-metrics" / "SKILL.md").write_text("# stale\n", encoding="utf-8")
    (target_dir / "skills" / "git-worktree-sandbox" / "tests").mkdir(parents=True)
    (target_dir / "skills" / "git-worktree-sandbox" / "tests" / "stale.py").write_text("# stale\n", encoding="utf-8")

    deploy_mod = _load_script_module("deploy_plugin_v2", "deploy_plugin.py")
    assert deploy_mod.deploy(str(REPO_ROOT), str(target_dir)) is True
    assert not (target_dir / "scripts" / "attention-check.py").exists()
    assert not (target_dir / "scripts" / "fsm.py").exists()
    assert not (target_dir / "schemas").exists()
    assert not (target_dir / "skills" / "attention-metrics").exists()
    assert not (target_dir / "skills" / "git-worktree-sandbox" / "tests").exists()
    assert (target_dir / "README.md").is_file()

    # Verify verify_source_bundle checks plugin.json logo and CANONICAL_SOURCE extras
    pjson = json.loads((target_dir / "plugin.json").read_text(encoding="utf-8"))
    orig_logo = pjson["logo"]
    pjson["logo"] = "assets/missing.svg"
    (target_dir / "plugin.json").write_text(json.dumps(pjson), encoding="utf-8")
    valid_logo, missing_logo = deploy_mod.verify_source_bundle(str(target_dir))
    assert valid_logo is False
    assert any("assets/missing.svg" in m for m in missing_logo)

    pjson["logo"] = orig_logo
    (target_dir / "plugin.json").write_text(json.dumps(pjson), encoding="utf-8")
    monkeypatch.setattr(deploy_mod, "CANONICAL_SOURCE", str(target_dir.resolve()))
    (target_dir / "LICENSE").unlink()
    valid_extra, missing_extra = deploy_mod.verify_source_bundle(str(target_dir))
    assert valid_extra is False
    assert "LICENSE" in missing_extra


def test_scan_transcript_header_boundaries_and_lean_parse_transcript(tmp_path, monkeypatch):
    _, common_mod = _setup_isolated_env(tmp_path, monkeypatch)

    # 1. Exact max_lines cutoff (line 2 included, line 3 excluded) + turn_id strictly from USER_INPUT
    tr_cutoff = tmp_path / "cutoff.jsonl"
    tok_line2 = str(uuid.uuid4())
    tok_line3 = str(uuid.uuid4())
    tr_cutoff.write_text(
        "\n".join([
            json.dumps({"step_index": 7, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "first"}),
            json.dumps({"step_index": 99, "source": "USER_EXPLICIT", "type": "PLANNER_RESPONSE", "content": f"[ANTIGRAVITY_TOKEN:{tok_line2}]"}),
            json.dumps({"step_index": 12, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": f"[ANTIGRAVITY_TOKEN:{tok_line3}]"}),
        ]) + "\n",
        encoding="utf-8",
    )
    hdr = common_mod.scan_transcript_header(str(tr_cutoff), max_lines=2)
    assert hdr["lines_scanned"] == 2
    assert hdr["turn_id"] == 7
    assert hdr["tokens"] == []

    # 2. >64KB truncated line fallback: line 1 captures sender, line 2 does NOT overwrite first_system_sender
    sender_1 = str(uuid.uuid4())
    sender_2 = str(uuid.uuid4())
    tok_big = str(uuid.uuid4())
    tr_big_line1 = tmp_path / "big_line1.jsonl"
    raw_l1 = f'{{"source":"SYSTEM","type":"SYSTEM_MESSAGE","content":"sender={sender_1} [ANTIGRAVITY_TOKEN:{tok_big}] ' + ("X" * 70000) + '"}\n'
    raw_l2 = f'{{"source":"SYSTEM","type":"SYSTEM_MESSAGE","content":"sender={sender_2} ' + ("Y" * 70000) + '"}\n'
    tr_big_line1.write_text(raw_l1 + raw_l2, encoding="utf-8")
    hdr_big1 = common_mod.scan_transcript_header(str(tr_big_line1), max_lines=2)
    assert hdr_big1["first_system_sender"] == sender_1
    assert hdr_big1["tokens"] == [tok_big]

    tr_big_line2 = tmp_path / "big_line2.jsonl"
    tr_big_line2.write_text(
        json.dumps({"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "hi"}) + "\n" + raw_l2,
        encoding="utf-8",
    )
    hdr_big2 = common_mod.scan_transcript_header(str(tr_big_line2), max_lines=2)
    assert hdr_big2["first_system_sender"] is None

    # 3. Lean parse_transcript omits retired v1 Stop/PreInvocation timer keys
    parsed = common_mod.parse_transcript(str(tr_cutoff))
    assert "active_timers_since_wakeup" not in parsed
    assert "has_delegation_in_turn" not in parsed

    # 4. system_audit._extract_script_paths_from_command ignores inline `/bin/sh -c '...'` scripts
    audit_mod = _load_script_module("system_audit_v2", "system_audit.py")
    inline_hooks = tmp_path / "inline_hooks.json"
    inline_hooks.write_text(
        json.dumps({
            "orca-status": {
                "PreInvocation": [
                    {
                        "type": "command",
                        "command": "/bin/sh -c 'if [ -f /nonexistent/opt.sh ]; then /bin/sh /nonexistent/opt.sh; else cat >/dev/null 2>&1; fi'",
                    }
                ]
            }
        }),
        encoding="utf-8",
    )
    ok_hooks, hook_errs, _ = audit_mod.audit_hooks_config(inline_hooks)
    assert ok_hooks is True, f"Inline /bin/sh -c hook should not be treated as missing script path: {hook_errs}"


