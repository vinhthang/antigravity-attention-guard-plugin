#!/usr/bin/env python3
"""Tests for Antigravity 2.0 orchestration, Gemini 4 detection, and native worker governance (REQ-038..REQ-041)."""
import importlib
import importlib.util
import io
import json
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_script(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(mod_name, str(SCRIPTS_DIR / filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


import common
import ledger as ledger_mod

inject_rules = _load_script("inject_rules_v2", "inject-rules.py")
enforce_delegation = _load_script("enforce_delegation_v2", "enforce-delegation.py")
attention_refresh = _load_script("attention_refresh_v2", "attention-refresh.py")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AGY_PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_MODEL", raising=False)
    monkeypatch.delenv("ATTENTION_GUARD_THINKING_MODELS", raising=False)
    monkeypatch.delenv("AGY_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("AGY_CHECKPOINT_THRESHOLD", raising=False)
    monkeypatch.delenv("AGY_ATTENTION_GUARD_KILL_SWITCH", raising=False)
    monkeypatch.delenv("AGY_ATTENTION_GUARD_OBSERVATION_MODE", raising=False)
    importlib.reload(ledger_mod)
    importlib.reload(common)
    common.clear_transcript_cache()
    yield


def _run_inject(payload: dict) -> dict:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    inject_rules.main(argv=["inject-rules.py"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())


def _run_enforce(payload: dict) -> dict:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    enforce_delegation.main(argv=["enforce-delegation.py"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())


def _run_refresh(payload: dict) -> dict:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    attention_refresh.main(argv=["attention-refresh.py"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())


def _seed_subagent(tmp_path: Path, token: str, may_delegate: bool = False, remaining_depth: int = 0) -> Path:
    l = ledger_mod.Ledger()
    with l._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
        conn.commit()
    payload_data = {
        "token": token,
        "may_delegate": may_delegate,
        "remaining_depth": remaining_depth,
        "parent_conv_id": "root-parent",
        "parent_turn_id": "1",
    }
    l.insert_event("root-parent", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload_data))
    t_file = tmp_path / f"subagent_{token}.jsonl"
    t_file.write_text(
        json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": f"Task\n[ANTIGRAVITY_TOKEN:{token}]"}) + "\n",
        encoding="utf-8",
    )
    return t_file


# ---------------------------------------------------------------------------
# REQ-038 / AC-038-1 & AC-038-2
# ---------------------------------------------------------------------------

class TestReq038Gemini4AndContextBudget:
    def test_ac_038_1_thinking_model_detection_codenames(self):
        for model in [
            "Gemini 4 Argon (High)",
            "Gemini 4 Carbon (High)",
            "gemini-4-argon",
            "carbon-thinking",
            "Claude Opus 4.6",
        ]:
            assert common.is_thinking_model(model) is True, f"Expected thinking model: {model}"

        for model in ["Gemini 3 Flash", "flash", "flash_lite", ""]:
            assert common.is_thinking_model(model) is False, f"Expected non-thinking model: {model}"

    def test_ac_038_2_thinking_models_env_override(self, monkeypatch):
        monkeypatch.setenv("ATTENTION_GUARD_THINKING_MODELS", "custom-thinker")
        assert common.is_thinking_model("custom-thinker-v1") is True
        assert common.is_thinking_model("Gemini 4 Argon (High)") is False

    def test_ac_038_1_resolve_context_budget_by_model_family(self):
        assert common.resolve_context_budget("Gemini 4 Argon (High)") == (1_000_000, 400_000)
        assert common.resolve_context_budget("Gemini 4 Carbon (High)") == (1_000_000, 400_000)
        assert common.resolve_context_budget("Gemini 3 Flash") == (1_000_000, 400_000)
        assert common.resolve_context_budget("argon") == (1_000_000, 400_000)
        assert common.resolve_context_budget("carbon") == (1_000_000, 400_000)
        assert common.resolve_context_budget("Claude Opus 4.6") == (200_000, 140_000)
        assert common.resolve_context_budget("Claude Sonnet 4") == (200_000, 140_000)
        assert common.resolve_context_budget("") == (128_000, 80_000)
        assert common.resolve_context_budget("unknown-local-llm") == (128_000, 80_000)

    def test_ac_038_2_resolve_context_budget_env_overrides_and_malformed_fallback(self, monkeypatch):
        monkeypatch.setenv("AGY_TOKEN_BUDGET", "500000")
        monkeypatch.setenv("AGY_CHECKPOINT_THRESHOLD", "250000")
        assert common.resolve_context_budget("Gemini 4 Carbon (High)") == (500_000, 250_000)

        for bad in ["abc", "0", "-50"]:
            monkeypatch.setenv("AGY_TOKEN_BUDGET", bad)
            monkeypatch.setenv("AGY_CHECKPOINT_THRESHOLD", bad)
            assert common.resolve_context_budget("Gemini 4 Carbon (High)") == (1_000_000, 400_000)
            assert common.resolve_context_budget("") == (128_000, 80_000)

    def test_ac_038_1_attention_refresh_gemini4_1000k_and_default_128k(self, tmp_path):
        l = ledger_mod.Ledger()

        # 50,000 tokens = 200,000 chars -> under 400k checkpoint for Gemini 4 Carbon
        l.record_tool_chars("g4-low", 50_000 * 4)
        art_low = tmp_path / "art_g4_low"
        res_low = _run_refresh({
            "sessionId": "g4-low",
            "conversationId": "g4-low",
            "modelName": "Gemini 4 Carbon (High)",
            "invocationNum": 25,
            "artifactDirectoryPath": str(art_low),
        })
        msg_low = res_low["injectSteps"][0]["ephemeralMessage"]
        assert "1000k budget" in msg_low
        assert not (art_low / "session_checkpoint.md").exists()

        # 410,000 tokens = 1,640,000 chars -> crosses 400k checkpoint for Gemini 4 Carbon
        l.record_tool_chars("g4-high", 410_000 * 4)
        art_high = tmp_path / "art_g4_high"
        res_high = _run_refresh({
            "sessionId": "g4-high",
            "conversationId": "g4-high",
            "modelName": "Gemini 4 Carbon (High)",
            "invocationNum": 25,
            "artifactDirectoryPath": str(art_high),
        })
        msg_high = res_high["injectSteps"][0]["ephemeralMessage"]
        assert "1000k budget" in msg_high
        assert (art_high / "session_checkpoint.md").is_file()

        # Omitted modelName keeps 128k budget / 80,000 checkpoint
        l.record_tool_chars("default-model", 85_000 * 4)
        art_def = tmp_path / "art_default"
        res_def = _run_refresh({
            "sessionId": "default-model",
            "conversationId": "default-model",
            "invocationNum": 25,
            "artifactDirectoryPath": str(art_def),
        })
        msg_def = res_def["injectSteps"][0]["ephemeralMessage"]
        assert "128k budget" in msg_def
        assert (art_def / "session_checkpoint.md").is_file()

    def test_ac_038_1_parse_transcript_resets_on_context_summary(self, tmp_path):
        summary_content = "<CONTEXT_SUMMARY>Compacted prior 500k tokens into summary.</CONTEXT_SUMMARY>"
        followup_content = "Continue implementing step 2"
        t_file = tmp_path / "transcript_context_summary.jsonl"
        steps = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "A" * 5000},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "step_index": 2, "content": "B" * 5000},
            {"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "step_index": 3, "content": summary_content},
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 4, "content": followup_content},
        ]
        t_file.write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")

        parsed = common.parse_transcript(str(t_file))
        expected = len(summary_content) + len(followup_content)
        assert parsed["active_context_chars"] == expected

        # Also verify USER_INPUT carrying <CONTEXT_SUMMARY>
        t_file_user = tmp_path / "transcript_context_summary_user.jsonl"
        steps_user = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Z" * 4000},
            {"source": "USER", "type": "USER_INPUT", "step_index": 2, "content": summary_content},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "step_index": 3, "content": followup_content},
        ]
        t_file_user.write_text("\n".join(json.dumps(s) for s in steps_user) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        parsed_user = common.parse_transcript(str(t_file_user))
        assert parsed_user["active_context_chars"] == expected


# ---------------------------------------------------------------------------
# REQ-039 / AC-039-1 & AC-039-2
# ---------------------------------------------------------------------------

class TestReq039NativeSwarmAndWorkflowWorkers:
    def test_ac_039_1_inject_rules_tags_swarm_add_brief_without_ledger_rows(self):
        l = ledger_mod.Ledger()
        res = _run_inject({
            "conversationId": "coord-1",
            "toolCall": {
                "name": "swarm",
                "args": {
                    "action": "add",
                    "name": "parser",
                    "workspace": "share",
                    "brief": "Own src/parser.py",
                },
            },
        })
        assert res["decision"] == "allow"
        assert res["overwrite"]["brief"].endswith("\n[AGY_SWARM_WORKER]")
        assert res["overwrite"]["name"] == "parser"
        assert res["overwrite"]["workspace"] == "share"

        with l._get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 0

        # Idempotent if tag already present
        res_idem = _run_inject({
            "conversationId": "coord-1",
            "toolCall": {
                "name": "default_api:swarm",
                "args": {
                    "action": "add",
                    "name": "parser",
                    "brief": "Own src/parser.py\n[AGY_SWARM_WORKER]",
                },
            },
        })
        assert res_idem["decision"] == "allow"
        assert "overwrite" not in res_idem

        # Excluded roles and non-add actions remain untouched without overwrite
        for untouched in [
            {"action": "add", "name": "narrator", "brief": "Narrate progress"},
            {"action": "add", "name": "monitor", "brief": "Check stalls"},
            {"action": "add", "name": "monitor-2", "brief": "Check stalls"},
            {"action": "status"},
        ]:
            out = _run_inject({
                "conversationId": "coord-1",
                "toolCall": {"name": "swarm", "args": untouched},
            })
            assert out == {"decision": "allow"}

    def test_ac_039_1_is_native_worker_positive_signals(self, tmp_path):
        for meta in [
            {"swarmMember": "parser"},
            {"isSwarmWorker": True},
            {"workflowId": "wf-1"},
            {"isWorkflowAgent": True},
        ]:
            assert common.is_native_worker(meta) is True

        worker_contents = [
            "Mission:\n[AGY_SWARM_WORKER]",
            "Mission:\n<swarm_worker>\nDo work\n</swarm_worker>",
            "[AGY_WORKFLOW_WORKER]\nMission",
        ]
        for idx, body in enumerate(worker_contents):
            for stype in ["USER_INPUT", "SYSTEM_MESSAGE"]:
                t_file = tmp_path / f"worker_{idx}_{stype}.jsonl"
                t_file.write_text(
                    json.dumps({"source": "USER", "type": stype, "step_index": 1, "content": body}) + "\n",
                    encoding="utf-8",
                )
                assert common.is_native_worker({"transcriptPath": str(t_file)}) is True

    def test_ac_039_2_is_native_worker_rejects_coordinator_and_post_title_calls(self, tmp_path):
        # Coordinator transcript has [AGY_SWARM_WORKER] inside PLANNER_RESPONSE swarm(add) tool_calls and GENERIC read_board
        t_coord = tmp_path / "coordinator.jsonl"
        t_coord.write_text(
            "\n".join([
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run a swarm"}),
                json.dumps({
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "step_index": 2,
                    "content": "Spawning parser",
                    "tool_calls": [{
                        "name": "swarm",
                        "args": {"action": "add", "name": "parser", "brief": "Own src/parser.py\n[AGY_SWARM_WORKER]"},
                    }],
                }),
                json.dumps({
                    "source": "SYSTEM",
                    "type": "GENERIC",
                    "step_index": 3,
                    "content": "Board #1 @parser Own src/parser.py\n[AGY_SWARM_WORKER]",
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_coord)}) is False

        # Transcript where marker appeared in USER_INPUT, followed later by coordinator-only swarm(action="title")
        t_promoted = tmp_path / "coord_after_title.jsonl"
        t_promoted.write_text(
            "\n".join([
                json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "Own foo\n[AGY_SWARM_WORKER]"}),
                json.dumps({
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "step_index": 2,
                    "content": "Naming swarm",
                    "tool_calls": [{"name": "swarm", "args": {"action": "title", "title": "My Swarm"}}],
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_promoted)}) is False

    def test_ac_039_1_and_ac_039_2_enforce_delegation_native_worker_vs_coordinator_and_safety(self, tmp_path):
        t_worker = tmp_path / "native_worker.jsonl"
        t_worker.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "Own src/foo.py\n[AGY_SWARM_WORKER]"}) + "\n",
            encoding="utf-8",
        )

        # Native worker under Gemini 4 Carbon (High) can write code and run pytest
        res_write = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {"name": "write_file", "args": {"Path": "/tmp/foo.py", "Content": "x = 1\n"}},
        })
        assert res_write["decision"] == "allow"

        res_test = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "rtk pytest tests/"}},
        })
        assert res_test["decision"] == "allow"

        # Coordinator under Gemini 4 Carbon (High) is still denied direct code edits and pytest
        t_coord = tmp_path / "coord.jsonl"
        t_coord.write_text(
            "\n".join([
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Coordinate swarm"}),
                json.dumps({
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "step_index": 2,
                    "tool_calls": [{"name": "swarm", "args": {"action": "add", "name": "parser", "brief": "Own foo\n[AGY_SWARM_WORKER]"}}],
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        res_coord_write = _run_enforce({
            "conversationId": "coord-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_coord),
            "toolCall": {"name": "write_file", "args": {"Path": "/tmp/foo.py", "Content": "x = 1\n"}},
        })
        assert res_coord_write["decision"] == "deny"

        res_coord_test = _run_enforce({
            "conversationId": "coord-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_coord),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "rtk pytest tests/"}},
        })
        assert res_coord_test["decision"] == "deny"

        # Native worker still denied on destructive command
        res_destr = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git reset --hard"}},
        })
        assert res_destr["decision"] == "deny"

        # Native worker still denied on test tampering
        res_tamper = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {"name": "write_file", "args": {"Path": "/tmp/test_foo.py", "Content": "def test_x():\n    assert True\n"}},
        })
        assert res_tamper["decision"] == "deny"

        # Native worker still denied on 3x identical run_command doom loop
        for i in range(2):
            r = _run_enforce({
                "conversationId": "worker-doom",
                "modelName": "Gemini 4 Carbon (High)",
                "transcriptPath": str(t_worker),
                "toolCall": {"name": "run_command", "args": {"CommandLine": "tail -n 10 /tmp/build.log"}},
            })
            assert r["decision"] == "allow", f"Call {i+1} should be allowed"

        r3 = _run_enforce({
            "conversationId": "worker-doom",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "tail -n 10 /tmp/build.log"}},
        })
        assert r3["decision"] == "deny"

    def test_ac_039_1_attention_refresh_suppressed_in_native_worker(self, tmp_path):
        l = ledger_mod.Ledger()
        l.record_tool_chars("native-worker-refresh", 100_000 * 4)
        t_worker = tmp_path / "worker_refresh.jsonl"
        t_worker.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "[AGY_WORKFLOW_WORKER]\nWork"}) + "\n",
            encoding="utf-8",
        )
        res = _run_refresh({
            "sessionId": "native-worker-refresh",
            "conversationId": "native-worker-refresh",
            "transcriptPath": str(t_worker),
            "invocationNum": 25,
        })
        assert res == {}

    def test_ac_039_2_enforce_delegation_test_tampering_boundaries(self):
        # TS backtick template literal stripped cleanly in .ts test file
        assert enforce_delegation.check_test_tampering(
            "tests/foo.test.ts",
            {"Content": "const s = `it.skip('not real')`;\nexpect(1).toBe(1);\n"},
        ) is None

        # Python # comment stripped cleanly in .py test file
        assert enforce_delegation.check_test_tampering(
            "tests/test_sample.py",
            {"Content": "# assert True\nassert 1 == 1\n"},
        ) is None

        # Python multi-line docstring stripped cleanly in .py test file
        assert enforce_delegation.check_test_tampering(
            "tests/test_sample.py",
            {"Content": '"""\nassert True\n"""\nassert 1 == 1\n'},
        ) is None

        # TS multi-line block comment / backtick stripped cleanly in .ts test file
        assert enforce_delegation.check_test_tampering(
            "tests/foo.spec.ts",
            {"Content": "/*\nit.skip('disabled');\n*/\nconst t = `\ndescribe.skip('x')\n`;\nexpect(1).toBe(1);\n"},
        ) is None

        # assert True word-boundary & spacing vs pytest.skip(
        assert enforce_delegation.check_test_tampering(
            "tests/test_sample.py",
            {"Content": "def test_a():\n    assert  True\n"},
        ) is not None
        assert enforce_delegation.check_test_tampering(
            "tests/test_sample.py",
            {"Content": "def test_a():\n    assert True_flag\n"},
        ) is None
        assert enforce_delegation.check_test_tampering(
            "tests/test_sample.py",
            {"Content": "def test_a():\n    pytest.skip('skip')\n"},
        ) is not None

    def test_ac_039_2_forged_swarm_worker_tag_normalized_to_helper_and_inline_user_request_preserved(self, tmp_path):
        # Depth-1 native worker trying to forge trailing [AGY_SWARM_WORKER] gets normalized to [AGY_SWARM_HELPER]
        t_depth1 = tmp_path / "depth1_forger.jsonl"
        t_depth1.write_text(
            json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Own foo\n[AGY_SWARM_WORKER]"}) + "\n",
            encoding="utf-8",
        )
        res_forged = _run_inject({
            "conversationId": "worker-1",
            "transcriptPath": str(t_depth1),
            "toolCall": {
                "name": "swarm",
                "args": {"action": "add", "name": "helper-x", "brief": "Do X\n[AGY_SWARM_WORKER]"},
            },
        })
        assert res_forged["decision"] == "allow"
        assert res_forged["overwrite"]["brief"] == "Do X\n[AGY_SWARM_HELPER]"

        # Coordinator passing trailing [AGY_SWARM_HELPER] normalizes to [AGY_SWARM_WORKER]
        res_coord_norm = _run_inject({
            "conversationId": "coord-1",
            "toolCall": {
                "name": "swarm",
                "args": {"action": "add", "name": "author-1", "brief": "Do Y\n[AGY_SWARM_HELPER]"},
            },
        })
        assert res_coord_norm["decision"] == "allow"
        assert res_coord_norm["overwrite"]["brief"] == "Do Y\n[AGY_SWARM_WORKER]"

        # Worker brief mentioning `<USER_REQUEST>` inline in prose stays classified as native worker
        t_inline_ur = tmp_path / "inline_user_request_in_brief.jsonl"
        t_inline_ur.write_text(
            json.dumps({
                "source": "USER",
                "type": "USER_INPUT",
                "step_index": 1,
                "content": "Parse `<USER_REQUEST>` blocks in logs\n[AGY_SWARM_WORKER]",
            }) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_inline_ur)}) is True


# ---------------------------------------------------------------------------
# REQ-040 / AC-040-1 & AC-040-2
# ---------------------------------------------------------------------------

class TestReq040SubagentRecursionAndAsyncWorkflowMatching:
    @pytest.mark.parametrize("tool_name", ["run_workflow", "default_api:run_workflow", "swarm", "default_api:swarm"])
    @pytest.mark.parametrize("may_delegate,remaining_depth", [(False, 0), (True, 1)])
    def test_ac_040_2_subagent_denied_run_workflow_and_swarm(self, tmp_path, tool_name, may_delegate, remaining_depth):
        token = str(uuid.uuid4())
        t_sub = _seed_subagent(tmp_path, token, may_delegate=may_delegate, remaining_depth=remaining_depth)
        res = _run_enforce({
            "conversationId": f"child-{token}",
            "transcriptPath": str(t_sub),
            "toolCall": {"name": tool_name, "args": {}},
        })
        assert res["decision"] == "deny"

    def test_ac_040_1_parse_transcript_run_workflow_vs_daemon_run_command(self, tmp_path):
        t_file = tmp_path / "brain" / "conv" / ".system_generated" / "logs" / "transcript.jsonl"
        t_file.parent.mkdir(parents=True, exist_ok=True)
        steps = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Audit specs and start server"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "content": "Launching workflow and daemon",
                "tool_calls": [
                    {"name": "run_workflow", "args": {"Description": "Audit specs", "Script": "print(1)"}},
                    {"name": "run_command", "args": {"CommandLine": "npm run dev", "toolSummary": "Start dev server", "IsDaemon": True}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-1\nTask Description: Audit specs\nTask logs are available at: /tmp/1.log",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-2\nTask Description: Start dev server\nTask logs are available at: /tmp/2.log",
            },
        ]
        t_file.write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")

        parsed = common.parse_transcript(str(t_file))
        assert parsed["has_delegation_in_turn"] is True
        assert parsed["active_bg_tasks"] == ["conv/task-1"]

        # Also test when daemon run_command appears first and GENERIC steps arrive in reverse order
        t_file2 = tmp_path / "brain" / "conv" / ".system_generated" / "logs" / "transcript_reverse.jsonl"
        steps2 = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run daemon and workflow"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "content": "Launching both",
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": "npm run dev", "toolSummary": "Start dev server", "IsDaemon": True}},
                    {"name": "default_api:run_workflow", "args": {"Description": "Audit specs", "Script": "print(1)"}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-10\nTask Description: Audit specs\nTask logs are available at: /tmp/10.log",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-11\nTask Description: Start dev server\nTask logs are available at: /tmp/11.log",
            },
        ]
        t_file2.write_text("\n".join(json.dumps(s) for s in steps2) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        parsed2 = common.parse_transcript(str(t_file2))
        assert parsed2["has_delegation_in_turn"] is True
        assert parsed2["active_bg_tasks"] == ["conv/task-10"]

    def test_ac_039_2_is_native_worker_immune_to_human_user_request_markers(self, tmp_path):
        # Human typing marker strings inside <USER_REQUEST> must never classify Primary Agent as native worker
        t_human = tmp_path / "human_mentioning_markers.jsonl"
        t_human.write_text(
            json.dumps({
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "step_index": 1,
                "content": "<USER_REQUEST>\nDocument [AGY_SWARM_WORKER] and <swarm_worker> in README\n</USER_REQUEST>",
            }) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_human)}) is False

        # Earlier worker wakeup marker followed by human <USER_REQUEST> resets worker_active to False
        t_reset = tmp_path / "human_after_marker.jsonl"
        t_reset.write_text(
            "\n".join([
                json.dumps({"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "step_index": 1, "content": "[AGY_SWARM_WORKER]\nAssigned"}),
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 2, "content": "<USER_REQUEST>\nTake over as Primary\n</USER_REQUEST>"}),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_reset)}) is False

    def test_ac_039_2_is_native_worker_inner_quoted_swarm_title_action(self, tmp_path):
        t_quoted = tmp_path / "quoted_title_action.jsonl"
        t_quoted.write_text(
            "\n".join([
                json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "Own foo\n[AGY_SWARM_WORKER]"}),
                json.dumps({
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "step_index": 2,
                    "tool_calls": [{"name": "swarm", "args": {"action": '"title"', "title": '"My Swarm"'}}],
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_quoted)}) is False

    def test_ac_040_1_parse_transcript_call_order_fallback_and_sync_workflow_completion(self, tmp_path):
        # 1. Call-order fallback: earlier no-Description run_workflow is popped before later run_command(IsDaemon=True)
        t_order = tmp_path / "brain" / "conv" / ".system_generated" / "logs" / "transcript_order.jsonl"
        t_order.parent.mkdir(parents=True, exist_ok=True)
        steps_order = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run workflow and daemon"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_workflow", "args": {"Script": "print(1)"}},
                    {"name": "run_command", "args": {"CommandLine": "npm run dev", "toolSummary": "Start dev server", "IsDaemon": True}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-21\nTask Description: Unmatched workflow job\nTask logs are available at: /tmp/a.log",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-22\nTask Description: Start dev server\nTask logs are available at: /tmp/b.log",
            },
        ]
        t_order.write_text("\n".join(json.dumps(s) for s in steps_order) + "\n", encoding="utf-8")
        parsed_order = common.parse_transcript(str(t_order))
        assert parsed_order["active_bg_tasks"] == ["conv/task-21"]

        # 2. Synchronous WaitMsBeforeAsync run_workflow completion ("Completed At:") pops run_workflow cleanly
        t_sync = tmp_path / "brain" / "conv" / ".system_generated" / "logs" / "transcript_sync_wf.jsonl"
        steps_sync = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run sync workflow then daemon"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_workflow", "args": {"Script": "print(1)", "WaitMsBeforeAsync": 5000}},
                    {"name": "run_command", "args": {"CommandLine": "npm run dev", "IsDaemon": True}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "DONE",
                "content": "Completed At: 2026-11-18T00:00:00Z\nWorkflow finished cleanly.",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-23\nTask Description: Unmatched daemon summary\nTask logs are available at: /tmp/c.log",
            },
        ]
        t_sync.write_text("\n".join(json.dumps(s) for s in steps_sync) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        parsed_sync = common.parse_transcript(str(t_sync))
        assert parsed_sync["active_bg_tasks"] == []

    def test_ac_040_1_unlabeled_command_does_not_steal_labeled_workflow_and_cmd_exit_restricts(self, tmp_path):
        # 1. Labeled run_workflow(Description="Audit specs") followed by unlabeled run_command(IsDaemon=True):
        #    unmatched daemon task must pop the unlabeled run_command, NOT steal labeled run_workflow!
        t_unlabeled = tmp_path / "brain" / "conv" / ".system_generated" / "logs" / "transcript_unlabeled_steal.jsonl"
        t_unlabeled.parent.mkdir(parents=True, exist_ok=True)
        steps_unlabeled = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run labeled workflow and unlabeled daemon"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_workflow", "args": {"Description": "Audit specs", "Script": "print(1)"}},
                    {"name": "run_command", "args": {"CommandLine": "npm run dev", "IsDaemon": True}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-31\nTask Description: Dev server running\nTask logs are available at: /tmp/31.log",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-32\nTask Description: Audit specs\nTask logs are available at: /tmp/32.log",
            },
        ]
        t_unlabeled.write_text("\n".join(json.dumps(s) for s in steps_unlabeled) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        parsed_unlabeled = common.parse_transcript(str(t_unlabeled))
        assert parsed_unlabeled["active_bg_tasks"] == ["conv/task-32"]

        # 2. Command exit ("Command exited with code 0\nCommand output: ...") only pops run_command, never run_workflow
        t_cmd_exit = tmp_path / "brain" / "conv" / ".system_generated" / "logs" / "transcript_cmd_exit.jsonl"
        steps_exit = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run workflow and command"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_workflow", "args": {"Script": "print(1)"}},
                    {"name": "run_command", "args": {"CommandLine": "echo hi", "IsDaemon": True}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "DONE",
                "content": "Completed At: 2026-11-18T00:00:00Z\nCommand exited with code 0.\nCommand output:\nhi",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-33\nTask Description: Background workflow\nTask logs are available at: /tmp/33.log",
            },
        ]
        t_cmd_exit.write_text("\n".join(json.dumps(s) for s in steps_exit) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        parsed_exit = common.parse_transcript(str(t_cmd_exit))
        assert parsed_exit["active_bg_tasks"] == ["conv/task-33"]

    def test_ac_039_2_is_native_worker_ignores_wakeup_envelopes_prose_and_resets_on_delegation(self, tmp_path):
        # 1. Inter-agent / task wakeup SYSTEM_MESSAGE envelopes ignored even with worker tags
        t_wakeup = tmp_path / "wakeup_envelope.jsonl"
        t_wakeup.write_text(
            "\n".join([
                json.dumps({
                    "source": "SYSTEM",
                    "type": "SYSTEM_MESSAGE",
                    "step_index": 1,
                    "content": "[Message] timestamp=2026-11-18T00:00:00Z sender=worker-1 content=[AGY_SWARM_WORKER]",
                }),
                json.dumps({
                    "source": "SYSTEM",
                    "type": "SYSTEM_MESSAGE",
                    "step_index": 2,
                    "content": "sender=task-1 completed with <swarm_worker> output",
                }),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_wakeup)}) is False

        # 2. Arbitrary prose substrings in USER_INPUT / SYSTEM_MESSAGE do not trigger
        t_prose = tmp_path / "prose_mentions.jsonl"
        t_prose.write_text(
            json.dumps({
                "source": "USER",
                "type": "USER_INPUT",
                "step_index": 1,
                "content": "Please document [AGY_WORKFLOW_WORKER] and [AGY_SWARM_WORKER] in the middle of a sentence.",
            }) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_prose)}) is False

        # 3. Reset worker_active = False when PLANNER_RESPONSE calls invoke_subagent or run_workflow
        for tool in ["invoke_subagent", "default_api:invoke_subagent", "run_workflow", "default_api:run_workflow"]:
            t_reset = tmp_path / f"reset_{tool.replace(':', '_')}.jsonl"
            t_reset.write_text(
                "\n".join([
                    json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "[AGY_WORKFLOW_WORKER]\nWork"}),
                    json.dumps({
                        "source": "MODEL",
                        "type": "PLANNER_RESPONSE",
                        "step_index": 2,
                        "tool_calls": [{"name": tool, "args": {}}],
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            assert common.is_native_worker({"transcriptPath": str(t_reset)}) is False

    def test_ac_039_2_native_worker_still_enforces_send_message_and_denies_manage_subagents(self, tmp_path):
        t_worker = tmp_path / "native_worker_send_msg.jsonl"
        t_worker.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "Own foo\n[AGY_SWARM_WORKER]"}) + "\n",
            encoding="utf-8",
        )
        res_bad_msg = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {
                "name": "send_message",
                "args": {"Recipient": "peer-1", "Message": "plain text not json"},
            },
        })
        assert res_bad_msg["decision"] == "deny"
        assert "Handoff MUST be valid JSON" in res_bad_msg["reason"]

        res_good_msg = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {
                "name": "send_message",
                "args": {"Recipient": "peer-1", "Message": json.dumps({"status": "ok"})},
            },
        })
        assert res_good_msg["decision"] == "allow"

        # Native worker send_message allows test verify_cmd under Gemini 4 without creating work_items rows,
        # while still blocking destructive verify_cmd.
        res_verify_test = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {
                "name": "send_message",
                "args": {"Recipient": "sub-existing", "Message": json.dumps({"status": "ok", "verify_cmd": "python3 -m pytest --version"})},
            },
        })
        assert res_verify_test["decision"] == "allow"
        l = ledger_mod.Ledger()
        with l._get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0

        res_verify_destr = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {
                "name": "send_message",
                "args": {"Recipient": "peer-1", "Message": json.dumps({"status": "ok", "verify_cmd": "git reset --hard"})},
            },
        })
        assert res_verify_destr["decision"] == "deny"

        # Native worker calling manage_subagents is DENIED before manage_subagents kill handler runs,
        # whereas non-worker Primary Agent calling manage_subagents still terminates work_items.
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id, claimed, claimed_by, created_at) VALUES (?, 1, ?, 1.0)", ("tok-m1", "sub-m1"))
            conn.execute(
                "INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx) VALUES (?, 'ACTIVE', 1.0, 1.0, 'primary-conv', '1', '1')",
                ("tok-m1",),
            )
            conn.commit()
        res_worker_kill = _run_enforce({
            "conversationId": "worker-conv",
            "transcriptPath": str(t_worker),
            "toolCall": {"name": "manage_subagents", "args": {"Action": "kill", "ConversationIds": ["sub-m1"]}},
        })
        assert res_worker_kill["decision"] == "deny"
        with l._get_connection() as conn:
            assert conn.execute("SELECT status FROM work_items WHERE work_id = 'tok-m1'").fetchone()[0] == "ACTIVE"

        t_primary = tmp_path / "primary_manage.jsonl"
        t_primary.write_text(
            json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "<USER_REQUEST>\nManage\n</USER_REQUEST>"}) + "\n",
            encoding="utf-8",
        )
        res_primary_kill = _run_enforce({
            "conversationId": "primary-conv",
            "transcriptPath": str(t_primary),
            "toolCall": {"name": "manage_subagents", "args": {"Action": "kill", "ConversationIds": ["sub-m1"]}},
        })
        assert res_primary_kill["decision"] == "allow"
        with l._get_connection() as conn:
            assert conn.execute("SELECT status FROM work_items WHERE work_id = 'tok-m1'").fetchone()[0] == "TERMINATED"

    @pytest.mark.parametrize(
        "tool_name",
        [
            "invoke_subagent", "default_api:invoke_subagent",
            "manage_subagents", "default_api:manage_subagents",
            "run_workflow", "default_api:run_workflow",
        ],
    )
    def test_ac_040_2_native_worker_recursion_fence_denies_nested_orchestration(self, tmp_path, tool_name):
        t_worker = tmp_path / "native_worker_fence.jsonl"
        t_worker.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "Own foo\n[AGY_SWARM_WORKER]"}) + "\n",
            encoding="utf-8",
        )
        res = _run_enforce({
            "conversationId": "worker-conv",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_worker),
            "toolCall": {"name": tool_name, "args": {}},
        })
        assert res["decision"] == "deny"
        assert "Native swarm/workflow workers are forbidden" in res["reason"]

    def test_ac_039_1_native_worker_allows_swarm_helpers(self, tmp_path):
        t_worker = tmp_path / "native_worker_swarm_ok.jsonl"
        t_worker.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "Own foo\n[AGY_SWARM_WORKER]"}) + "\n",
            encoding="utf-8",
        )
        for tname in ["swarm", "default_api:swarm"]:
            res = _run_enforce({
                "conversationId": "worker-conv",
                "modelName": "Gemini 4 Carbon (High)",
                "transcriptPath": str(t_worker),
                "toolCall": {"name": tname, "args": {"action": "add", "name": "helper", "brief": "Help"}},
            })
            assert res["decision"] == "allow"

    def test_ac_039_2_is_native_worker_anchored_tag_and_sticky_coordinator(self, tmp_path):
        # 1. Inline prose <swarm_worker> must NOT match
        t_inline = tmp_path / "inline_swarm_tag.jsonl"
        t_inline.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "see <swarm_worker> tag in docs"}) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_inline)}) is False

        # 2. Sticky saw_coordinator_or_human blocks subsequent <swarm_worker> or [AGY_WORKFLOW_WORKER]
        t_sticky = tmp_path / "sticky_coord.jsonl"
        t_sticky.write_text(
            "\n".join([
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "<USER_REQUEST>\nHello\n</USER_REQUEST>"}),
                json.dumps({"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "step_index": 2, "content": "<swarm_worker>\nQuoted file"}),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_sticky)}) is False

        t_sticky_wf = tmp_path / "sticky_wf.jsonl"
        t_sticky_wf.write_text(
            "\n".join([
                json.dumps({
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "step_index": 1,
                    "tool_calls": [{"name": "invoke_subagent", "args": {}}],
                }),
                json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 2, "content": "[AGY_WORKFLOW_WORKER]\nPrompt"}),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_sticky_wf)}) is False

        # 3. fork:'coordinator' with end-anchored \n[AGY_SWARM_WORKER] in non-USER_EXPLICIT, non-sender= USER_INPUT works
        t_fork = tmp_path / "fork_coordinator.jsonl"
        t_fork.write_text(
            "\n".join([
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "<USER_REQUEST>\nStart\n</USER_REQUEST>"}),
                json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "step_index": 2, "tool_calls": [{"name": "swarm", "args": {"action": "title", "title": "S"}}]}),
                json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 3, "content": "@parser Own parser\n[AGY_SWARM_WORKER]"}),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_fork)}) is True

    def test_ac_039_1_inject_rules_swarm_normalized_action_and_anchored_tag(self):
        # Normalized quoted action + mid-text mention still appends anchored suffix
        res_mid = _run_inject({
            "conversationId": "coord-1",
            "toolCall": {
                "name": "swarm",
                "args": {
                    "action": '"ADD"',
                    "name": "parser",
                    "brief": "Note: mentions [AGY_SWARM_WORKER] mid-text only",
                },
            },
        })
        assert res_mid["decision"] == "allow"
        assert res_mid["overwrite"]["brief"].endswith("\n[AGY_SWARM_WORKER]")

        # Already end-anchored (even with trailing spaces) is idempotent
        res_end = _run_inject({
            "conversationId": "coord-1",
            "toolCall": {
                "name": "swarm",
                "args": {
                    "action": '"add"',
                    "name": "parser",
                    "brief": "Own parser\n[AGY_SWARM_WORKER]   ",
                },
            },
        })
        assert res_end == {"decision": "allow"}

    def test_ac_040_1_pop_matching_planner_call_prefers_run_command_in_pass3(self, tmp_path):
        t_file = tmp_path / "brain" / "conv" / ".system_generated" / "logs" / "transcript_pass3.jsonl"
        t_file.parent.mkdir(parents=True, exist_ok=True)
        steps = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run workflow and daemon"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_workflow", "args": {"Description": "Audit specs", "Script": "print(1)"}},
                    {"name": "run_command", "args": {"CommandLine": "npm run dev", "toolSummary": "Start dev server", "IsDaemon": True}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-41\nTask Description: Localhost server started\nTask logs are available at: /tmp/41.log",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-42\nTask Description: Audit specs\nTask logs are available at: /tmp/42.log",
            },
        ]
        t_file.write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        parsed = common.parse_transcript(str(t_file))
        assert parsed["active_bg_tasks"] == ["conv/task-42"]

    def test_ac_040_1_unlabeled_daemon_and_unlabeled_sync_workflow_do_not_cross_pop(self, tmp_path):
        log_dir = tmp_path / "brain" / "conv" / ".system_generated" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # Case 1: sync workflow Completed At first, background unlabeled daemon second -> active_bg_tasks == []
        t1 = log_dir / "transcript_sync_then_bg.jsonl"
        steps1 = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run daemon and workflow"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": "python3 server.py", "IsDaemon": True}},
                    {"name": "run_workflow", "args": {"Script": "print(1)"}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "DONE",
                "content": "Completed At: 2026-11-18T00:00:01Z\nWorkflow result: ok",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-9\nTask logs are available at: /tmp/task-9.log",
            },
        ]
        t1.write_text("\n".join(json.dumps(s) for s in steps1) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        assert common.parse_transcript(str(t1))["active_bg_tasks"] == []

        # Case 2: reverse order (background daemon conv/task-9 first, sync workflow Completed At second) -> active_bg_tasks == []
        t2 = log_dir / "transcript_bg_then_sync.jsonl"
        steps2 = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run daemon and workflow"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": "python3 server.py", "IsDaemon": True}},
                    {"name": "run_workflow", "args": {"Script": "print(1)"}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-9\nTask logs are available at: /tmp/task-9.log",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "DONE",
                "content": "Completed At: 2026-11-18T00:00:01Z\nWorkflow result: ok",
            },
        ]
        t2.write_text("\n".join(json.dumps(s) for s in steps2) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        assert common.parse_transcript(str(t2))["active_bg_tasks"] == []

        # Case 3: sync non-daemon run_command (Command exited with code 0) + background unlabeled run_workflow (conv/task-10) -> ["conv/task-10"]
        t3 = log_dir / "transcript_sync_cmd_bg_wf.jsonl"
        steps3 = [
            {"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Run cmd and workflow"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "step_index": 2,
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": "echo ok"}},
                    {"name": "run_workflow", "args": {"Script": "print(1)"}},
                ],
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 3,
                "status": "DONE",
                "content": "Completed At: 2026-11-18T00:00:01Z\nCommand exited with code 0",
            },
            {
                "source": "SYSTEM",
                "type": "GENERIC",
                "step_index": 4,
                "status": "RUNNING",
                "content": "Tool is running as a background task with task id: conv/task-10\nTask logs are available at: /tmp/task-10.log",
            },
        ]
        t3.write_text("\n".join(json.dumps(s) for s in steps3) + "\n", encoding="utf-8")
        common.clear_transcript_cache()
        assert common.parse_transcript(str(t3))["active_bg_tasks"] == ["conv/task-10"]

    def test_ac_039_1_and_ac_039_2_user_explicit_worker_briefs_vs_human_prompts(self, tmp_path):
        # Worker briefs delivered as source == "USER_EXPLICIT" without <USER_REQUEST> must return True
        for idx, body in enumerate([
            "Own src/foo.py\n[AGY_SWARM_WORKER]",
            "Own src/foo.py\n[AGY_SWARM_HELPER]",
            "[AGY_WORKFLOW_WORKER]\nAudit module",
        ]):
            t_w = tmp_path / f"user_explicit_worker_{idx}.jsonl"
            t_w.write_text(
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": body}) + "\n",
                encoding="utf-8",
            )
            assert common.is_native_worker({"transcriptPath": str(t_w)}) is True

        # <USER_REQUEST> wrapped prompt containing marker returns False
        t_req = tmp_path / "user_request_wrapped.jsonl"
        t_req.write_text(
            json.dumps({
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "step_index": 1,
                "content": "<USER_REQUEST>\nExplain\n[AGY_SWARM_WORKER]\n</USER_REQUEST>",
            }) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_req)}) is False

        # Unmarked USER_EXPLICIT followed by SYSTEM_MESSAGE with marker -> False
        t_sys = tmp_path / "user_explicit_then_system.jsonl"
        t_sys.write_text(
            "\n".join([
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Hello"}),
                json.dumps({"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "step_index": 2, "content": "Reminder\n[AGY_SWARM_WORKER]"}),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_sys)}) is False

        # Unmarked USER_EXPLICIT followed by second USER_EXPLICIT with marker -> False
        t_second = tmp_path / "user_explicit_then_second_explicit.jsonl"
        t_second.write_text(
            "\n".join([
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Hello"}),
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 2, "content": "Explain\n[AGY_SWARM_WORKER]"}),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_second)}) is False

        # fork:"coordinator": <USER_REQUEST> + swarm(title) + non-USER_EXPLICIT USER_INPUT ending in [AGY_SWARM_WORKER] -> True
        t_fork = tmp_path / "fork_coordinator_user_input.jsonl"
        t_fork.write_text(
            "\n".join([
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "<USER_REQUEST>\nRun swarm\n</USER_REQUEST>"}),
                json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "step_index": 2, "tool_calls": [{"name": "swarm", "args": {"action": "title", "title": "S"}}]}),
                json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 3, "content": "@parser Own parser\n[AGY_SWARM_WORKER]"}),
            ]) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_fork)}) is True

    def test_ac_039_2_and_ac_040_2_bounded_native_swarm_helper_depth(self, tmp_path):
        # 1. inject-rules.py tags depth-1 worker's swarm(add) brief with \n[AGY_SWARM_HELPER]
        t_depth1 = tmp_path / "depth1_worker.jsonl"
        t_depth1.write_text(
            json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Own parser\n[AGY_SWARM_WORKER]"}) + "\n",
            encoding="utf-8",
        )
        res_inj = _run_inject({
            "conversationId": "worker-1",
            "transcriptPath": str(t_depth1),
            "toolCall": {
                "name": "swarm",
                "args": {"action": "add", "name": "helper-1", "brief": "Write unit tests"},
            },
        })
        assert res_inj["decision"] == "allow"
        assert res_inj["overwrite"]["brief"] == "Write unit tests\n[AGY_SWARM_HELPER]"

        # Idempotent when [AGY_SWARM_HELPER] already anchored at end
        res_inj_idem = _run_inject({
            "conversationId": "worker-1",
            "transcriptPath": str(t_depth1),
            "toolCall": {
                "name": "swarm",
                "args": {"action": "add", "name": "helper-1", "brief": "Write unit tests\n[AGY_SWARM_HELPER]"},
            },
        })
        assert res_inj_idem == {"decision": "allow"}

        # 2. Classification: is_native_worker vs is_leaf_native_worker across metadata and transcripts
        assert common.is_native_worker({"workflowId": "wf-1"}) is True
        assert common.is_leaf_native_worker({"workflowId": "wf-1"}) is True
        assert common.is_native_worker({"isWorkflowAgent": True}) is True
        assert common.is_leaf_native_worker({"isWorkflowAgent": True}) is True
        assert common.is_native_worker({"swarmMember": "parser"}) is True
        assert common.is_leaf_native_worker({"swarmMember": "parser"}) is False
        assert common.is_native_worker({"isSwarmWorker": True}) is True
        assert common.is_leaf_native_worker({"isSwarmWorker": True}) is False

        t_helper = tmp_path / "leaf_helper.jsonl"
        t_helper.write_text(
            json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "Write unit tests\n[AGY_SWARM_HELPER]"}) + "\n",
            encoding="utf-8",
        )
        t_wf = tmp_path / "leaf_wf.jsonl"
        t_wf.write_text(
            json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1, "content": "[AGY_WORKFLOW_WORKER]\nAudit module"}) + "\n",
            encoding="utf-8",
        )
        t_tag = tmp_path / "depth1_xml_tag.jsonl"
        t_tag.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "<swarm_worker>\nOwn module"}) + "\n",
            encoding="utf-8",
        )
        assert common.is_native_worker({"transcriptPath": str(t_depth1)}) is True
        assert common.is_leaf_native_worker({"transcriptPath": str(t_depth1)}) is False
        assert common.is_native_worker({"transcriptPath": str(t_tag)}) is True
        assert common.is_leaf_native_worker({"transcriptPath": str(t_tag)}) is False
        assert common.is_native_worker({"transcriptPath": str(t_helper)}) is True
        assert common.is_leaf_native_worker({"transcriptPath": str(t_helper)}) is True
        assert common.is_native_worker({"transcriptPath": str(t_wf)}) is True
        assert common.is_leaf_native_worker({"transcriptPath": str(t_wf)}) is True

        # 3. enforce-delegation.py: depth-1 allows swarm(add), denies swarm(title), allows swarm(status);
        #    leaf helper/workflow denies swarm(add) and swarm(title), allows swarm(status).
        assert _run_enforce({
            "conversationId": "worker-1",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_depth1),
            "toolCall": {"name": "swarm", "args": {"action": "add", "name": "helper-1", "brief": "Help"}},
        })["decision"] == "allow"

        assert _run_enforce({
            "conversationId": "worker-1",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_depth1),
            "toolCall": {"name": "swarm", "args": {"action": '"title"', "title": "Hijack"}},
        })["decision"] == "deny"

        assert _run_enforce({
            "conversationId": "worker-1",
            "modelName": "Gemini 4 Carbon (High)",
            "transcriptPath": str(t_depth1),
            "toolCall": {"name": "swarm", "args": {"action": "status"}},
        })["decision"] == "allow"

        for leaf_t in (t_helper, t_wf):
            for tname in ("swarm", "default_api:swarm"):
                assert _run_enforce({
                    "conversationId": "leaf-1",
                    "modelName": "Gemini 4 Carbon (High)",
                    "transcriptPath": str(leaf_t),
                    "toolCall": {"name": tname, "args": {"action": "add", "name": "sub-helper", "brief": "Loop"}},
                })["decision"] == "deny"
                assert _run_enforce({
                    "conversationId": "leaf-1",
                    "modelName": "Gemini 4 Carbon (High)",
                    "transcriptPath": str(leaf_t),
                    "toolCall": {"name": tname, "args": {"action": "title", "title": "Hijack"}},
                })["decision"] == "deny"
                assert _run_enforce({
                    "conversationId": "leaf-1",
                    "modelName": "Gemini 4 Carbon (High)",
                    "transcriptPath": str(leaf_t),
                    "toolCall": {"name": tname, "args": {"action": "status"}},
                })["decision"] == "allow"

    def test_ac_038_2_resolve_context_budget_scaling_and_clamping(self, monkeypatch):
        monkeypatch.setenv("AGY_TOKEN_BUDGET", "100000")
        monkeypatch.delenv("AGY_CHECKPOINT_THRESHOLD", raising=False)
        assert common.resolve_context_budget("Gemini 4 Carbon (High)") == (100_000, 62_500)

        monkeypatch.setenv("AGY_TOKEN_BUDGET", "2000000")
        monkeypatch.delenv("AGY_CHECKPOINT_THRESHOLD", raising=False)
        assert common.resolve_context_budget("Gemini 4 Carbon (High)") == (2_000_000, 1_250_000)

        monkeypatch.setenv("AGY_TOKEN_BUDGET", "50000")
        monkeypatch.setenv("AGY_CHECKPOINT_THRESHOLD", "80000")
        assert common.resolve_context_budget("Gemini 4 Carbon (High)") == (50_000, 50_000)


# ---------------------------------------------------------------------------
# REQ-041 / AC-041-1 & AC-041-2
# ---------------------------------------------------------------------------

class TestReq041Antigravity2DocsAndCleanliness:
    def test_ac_041_1_no_legacy_subagents_list_or_spec_gate_claims(self):
        checked_files = [
            REPO_ROOT / "rules" / "AGENTS.md",
            REPO_ROOT / "README.md",
            *sorted((REPO_ROOT / "templates").glob("*.md")),
            *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
        ]
        for path in checked_files:
            assert path.is_file(), f"Missing file: {path}"
            txt = path.read_text(encoding="utf-8")
            assert "Subagents=[" not in txt, f"Legacy Subagents=[ found in {path}"
            assert "spec-gate.py" not in txt, f"Retired spec-gate.py reference found in {path}"


class TestCommandClassificationBoundaries:
    def test_common_is_build_command_boundaries(self):
        assert common.is_build_command("python -mpip install foo") is True
        assert common.is_build_command("python -mvenv env") is False
        assert common.is_build_command("go build ./...") is True
        assert common.is_build_command("python3") is False
        assert common.is_build_command("python3 -m") is False
