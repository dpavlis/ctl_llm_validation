import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import self_distill as sd


FIX_USER = (
    "Fix the following CTL2 REFORMAT transform so that it compiles and does what the "
    "specification says.\n\n```ctl\n//#CTL2\nfunction integer transform() {\n"
    "    $out.0.x = $in.0.x\n    return ALL;\n}\n```"
)
FIX_REF = "PROBLEMS FIXED:\n  1. missing semicolon\n\n```ctl\n//#CTL2\nfunction integer transform() {\n    $out.0.x = $in.0.x;\n    return ALL;\n}\n```"
VALIDATE_REF = "ISSUES:\n  [ERROR] `x` is wrong\n  [WARNING] `y` may be null\n\nSUGGESTIONS:\n  - Use `nvl(y, 0)`.\nVERDICT: FAIL"
GEN_USER = "Write a Rollup grouped by member_id that counts loans."
GEN_REF = "```ctl\n//#CTL2\nfunction void initGroup(Acc acc) {\n    acc.n = 0;\n}\n```"


class TestClassification(unittest.TestCase):
    def test_validate(self):
        self.assertEqual(sd.classify_task("Validate this Rollup CTL2.", VALIDATE_REF, []), "validate")

    def test_fix(self):
        self.assertEqual(sd.classify_task(FIX_USER, FIX_REF, []), "fix")

    def test_fix_by_tag_without_verb(self):
        user = "Review this.\n\n```ctl\n//#CTL2\nfunction integer transform() { return ALL; }\n```"
        self.assertEqual(sd.classify_task(user, FIX_REF.replace("PROBLEMS FIXED:", ""), ["fix_code"]), "fix")

    def test_code_in_without_fix_signal_is_other(self):
        user = "Is all of this necessary?\n\n```ctl\n//#CTL2\nfunction integer transform() { return ALL; }\n```"
        ref = "Most of it.\n\n```ctl\n//#CTL2\nfunction integer transform() { return ALL; }\n```"
        self.assertEqual(sd.classify_task(user, ref, []), "other")

    def test_generate(self):
        self.assertEqual(sd.classify_task(GEN_USER, GEN_REF, []), "generate")

    def test_signature_in_backticks_is_not_code_in(self):
        user = "Component: DENORMALIZER. Show `function integer appendOnError(string m, string s)` usage."
        self.assertEqual(sd.classify_task(user, GEN_REF, []), "generate")

    def test_explanation_is_other(self):
        self.assertEqual(sd.classify_task("What does isnull do?", "It tests one value for null.", []), "other")

    def test_real_fix_to_spec_records(self):
        recs = json.loads((sd.TRAIN_DIR / "CTL_LoRAT_fix_to_spec.json").read_text())
        for rec in recs:
            user, ref = sd._split_record(rec)
            # All 28 are fix tasks, including the four fixthiscc4_* review-and-correct records.
            self.assertEqual(sd.classify_task(user, ref, rec.get("tags") or []), "fix", rec["id"])


class TestComponent(unittest.TestCase):
    def test_field_wins_and_normalises(self):
        self.assertEqual(sd.resolve_component({"component": "HASH_JOIN"}, "a rollup"), ("JOIN", "field"))

    def test_prompt(self):
        self.assertEqual(sd.resolve_component({}, "Write a Rollup grouped by x")[0], "ROLLUP")

    def test_map_wording(self):
        self.assertEqual(sd.resolve_component({}, "In a Map I want to assign a level")[0], "REFORMAT")

    def test_uppercase_component_id(self):
        self.assertEqual(sd.resolve_component({}, "Validate this CTL2 for a DATA_GENERATOR with ports")[0],
                         "DATA_GENERATOR")

    def test_unnamed(self):
        self.assertEqual(sd.resolve_component({}, "Write a CTL2 transform() function that looks up a shop"),
                         ("", ""))

    def test_compile_bucket_prefers_distinctive_code(self):
        code = "//#CTL2\nfunction integer getOutputPort() { return 0; }"
        self.assertEqual(sd.compile_bucket_for("FILTER", code), "PARTITION")
        plain = "//#CTL2\nfunction integer transform() { return ALL; }"
        self.assertEqual(sd.compile_bucket_for("FILTER", plain), "FILTER")

    def test_http_connector_is_not_compiled_as_a_join(self):
        code = "//#CTL2\nfunction integer transform() {\n  $out.0.s = $in.1.statusCode;\n  return ALL;\n}"
        self.assertEqual(sd.compile_bucket_for("HTTP_CONNECTOR", code), "HTTP_CONNECTOR")
        prompt = {"component": "HTTP_CONNECTOR", "compile_bucket": "HTTP_CONNECTOR", "user": ""}
        result = sd.compile_check(prompt, "```ctl\n" + code + "\n```", sd.MCP_DEFAULTS)
        self.assertEqual(result["status"], "skipped_unsupported_component")


class TestNormalisationAndSelection(unittest.TestCase):
    def test_norm_ws(self):
        self.assertEqual(sd.norm_ws("  a\n\tb   c "), "a b c")
        self.assertEqual(sd.make_prompt_id("a  b"), sd.make_prompt_id("a\nb"))

    def _pool(self):
        pool = []
        for i in range(40):
            pool.append({"prompt_id": f"f{i}", "task_type": "fix", "component": "REFORMAT",
                         "fix_to_spec": i < 5, "fix_score": i % 3,
                         "source_origin": "think" if i < 30 else "fix_topup"})
        for i in range(60):
            pool.append({"prompt_id": f"v{i}", "task_type": "validate", "component": "ROLLUP",
                         "ref_verdict": "PASS" if i < 10 else "FAIL", "ref_findings": 0 if i < 10 else i % 4})
        for i in range(50):
            pool.append({"prompt_id": f"g{i}", "task_type": "generate",
                         "component": "ROLLUP" if i < 20 else "REFORMAT"})
        for p in pool:
            p["source_file"] = "synthetic.json"
        return pool

    PLAN = (
        ("fix", "fix_tier0", None),
        ("fix", "fix_tier2", 3),
        ("validate", "validate_pass_clean", 4),
        ("validate", "validate_1", 5),
        ("generate", "generate_lifecycle", 7),
        ("generate", "generate_other", 3),
    )

    def test_plan_deterministic_and_followed(self):
        a, sa = sd.select_prompts(self._pool(), seed=7, plan=self.PLAN)
        b, _ = sd.select_prompts(self._pool(), seed=7, plan=self.PLAN)
        self.assertEqual([p["prompt_id"] for p in a], [p["prompt_id"] for p in b])
        self.assertEqual(sa["by_group"], {"fix_tier0": 5, "fix_tier2": 3, "validate_pass_clean": 4,
                                          "validate_1": 5, "generate_lifecycle": 7, "generate_other": 3})
        # A capped fix group keeps its most semantic records.
        tier2 = [p for p in a if p["selection_group"] == "fix_tier2"]
        self.assertTrue(all(p["fix_score"] == 2 for p in tier2))
        self.assertTrue(all(p["ref_findings"] == 1 for p in a if p["selection_group"] == "validate_1"))
        self.assertFalse([p for p in a if p["task_type"] == "validate" and p["ref_findings"] >= 3])

    def test_shortfall_reported(self):
        _, s = sd.select_prompts(self._pool(), seed=0, plan=(("validate", "validate_pass_clean", 50),))
        self.assertEqual(s["shortfall"], {"validate_pass_clean": 40})

    def test_real_full_plan(self):
        excluded, _ = sd.load_exclusion_set()
        pool, _ = sd.build_pool(excluded)
        chosen, summary = sd.select_prompts(pool, seed=0)
        self.assertEqual(summary["shortfall"], {})
        self.assertEqual(summary["selected"], {"fix": 124, "validate": 150, "generate": 100})
        groups = {p["selection_group"] for p in chosen}
        self.assertFalse(groups & set(sd.FULL_EXCLUDED_GROUPS))
        self.assertEqual(summary["by_group"]["fix_tier2"], 20)
        self.assertEqual(summary["by_group"]["validate_pass_warn"], 30)
        self.assertFalse({p["record_id"] for p in pool} & sd.KNOWN_WRONG_REFERENCES)

    def test_real_selection_excludes_eval_prompts(self):
        excluded, _ = sd.load_exclusion_set()
        pool, _ = sd.build_pool(excluded)
        self.assertTrue(pool)
        self.assertFalse([p for p in pool if sd.norm_ws(p["user_original"]) in excluded])
        self.assertEqual(len({sd.norm_ws(p["user_original"]) for p in pool}), len(pool))

    def test_real_validate_prompts_all_specify_the_format(self):
        excluded, _ = sd.load_exclusion_set()
        pool, _ = sd.build_pool(excluded)
        val = [p for p in pool if p["task_type"] == "validate"]
        self.assertTrue(all(sd.has_output_format_spec(p["user"]) for p in val))
        self.assertTrue(any(p["format_instruction_added"] for p in val))
        self.assertTrue(any(not p["format_instruction_added"] for p in val))
        # Identity stays on the record's own prompt.
        self.assertTrue(all(p["prompt_id"] == sd.make_prompt_id(p["user_original"]) for p in val))
        self.assertFalse(any(p["format_instruction_added"] for p in pool if p["task_type"] != "validate"))

    def test_real_pilot_is_stratified(self):
        excluded, _ = sd.load_exclusion_set()
        pool, _ = sd.build_pool(excluded)
        chosen, summary = sd.select_pilot(pool, seed=0)
        self.assertEqual(summary["shortfall"], {})
        want = {g: n for _t, g, n in sd.PILOT_PLAN}
        self.assertEqual(summary["by_group"], want)
        again, _ = sd.select_pilot(pool, seed=0)
        self.assertEqual([p["prompt_id"] for p in chosen], [p["prompt_id"] for p in again])
        # Spread: every fix tier and several source files per task type.
        for task in sd.TASK_TYPES:
            files = {p["source_file"] for p in chosen if p["task_type"] == task}
            self.assertGreaterEqual(len(files), 3, task)


class TestValidateFormatInstruction(unittest.TestCase):
    def test_added_when_missing(self):
        user, added = sd.with_validate_format("Validate this Rollup CTL2.\n```ctl\n//#CTL2\n```\n")
        self.assertTrue(added)
        self.assertTrue(user.endswith(sd.VALIDATE_FORMAT_INSTRUCTION))
        self.assertTrue(sd.has_output_format_spec(user))

    def test_kept_when_present(self):
        prompt = "Validate this. Report findings using ISSUES, SUGGESTIONS, and VERDICT."
        self.assertEqual(sd.with_validate_format(prompt), (prompt, False))

    def test_instruction_matches_the_checker(self):
        # The layout the instruction shows must pass format_check as an answer.
        example = ("ISSUES:\n  [ERROR] `x` — wrong\n\nSUGGESTIONS:\n  - fix x\n\nVERDICT: FAIL")
        self.assertIsNone(sd.format_check({"task_type": "validate", "reference": "", "user": ""}, example))
        clean = "ISSUES:\n  [INFO] No issues found.\n\nVERDICT: PASS"
        self.assertIsNone(sd.format_check({"task_type": "validate", "reference": "", "user": ""}, clean))


class TestFormatAndLibrary(unittest.TestCase):
    fix_prompt = {"task_type": "fix", "reference": FIX_REF, "user": FIX_USER}
    val_prompt = {"task_type": "validate", "reference": VALIDATE_REF,
                  "user": "Validate:\n```ctl\n//#CTL2\n$out.0.a = fooBar($in.0.a);\n```"}

    def test_code_answer(self):
        self.assertIsNone(sd.format_check(self.fix_prompt, FIX_REF))
        self.assertEqual(sd.format_check(self.fix_prompt, "no code"), "no_ctl_block")
        no_header = "```ctl\nfunction integer transform() { return ALL; }\n```"
        self.assertEqual(sd.format_check(self.fix_prompt, no_header), "missing_ctl2_header")

    def test_validate_answer(self):
        self.assertIsNone(sd.format_check(self.val_prompt, VALIDATE_REF))
        self.assertIsNone(sd.format_check(self.val_prompt, "ISSUES: none\nVERDICT: PASS"))
        self.assertEqual(sd.format_check(self.val_prompt, "ISSUES:\nVERDICT: FAIL"),
                         "validate_fail_without_findings")  # checked before the consistency rule
        self.assertEqual(sd.format_check(self.val_prompt, "Looks fine."), "validate_format_missing")
        self.assertEqual(sd.format_check(self.val_prompt, "ISSUES:\n  [WARNING] `x` — odd\nVERDICT: FAIL"),
                         "validate_verdict_inconsistent")
        self.assertEqual(sd.format_check(self.val_prompt, "ISSUES:\n  [ERROR] `x` — broken\nVERDICT: PASS"),
                         "validate_verdict_inconsistent")

    def test_validate_parse_keeps_retracted_issue(self):
        parsed = sd.parse_validate_answer(
            "ISSUES:\n  [ERROR] `a` fails — actually no, this is fine.\nVERDICT: PASS")
        self.assertEqual(parsed["errors"], 1)

    def test_called_functions_ignores_strings_comments_and_local_defs(self):
        code = ('//#CTL2\n// notAFunction(x)\nfunction string[] helper(integer n) { return []; }\n'
                'function integer transform() {\n  string s = "fake(1)";\n  helper(1);\n'
                '  $out.0.a = upperCase(s).trim();\n  lookup(L).get(1);\n  return ALL;\n}')
        self.assertEqual(sd.called_functions(code), {"upperCase", "trim", "get"})

    def test_unknown_function_rejected(self):
        answer = "```ctl\n//#CTL2\nfunction integer transform() {\n  $out.0.a = getFieldValue($in.0, 1);\n  return ALL;\n}\n```"
        reason, unknown = sd.library_check(self.fix_prompt, answer)
        self.assertEqual((reason, unknown), ("unknown_function", ["getFieldValue"]))
        self.assertEqual(sd.library_check(self.fix_prompt, FIX_REF), (None, []))

    def test_validate_suggestion_may_name_the_tasks_own_call(self):
        answer = "ISSUES:\n  [ERROR] `fooBar` does not exist\nSUGGESTIONS:\n  - Replace `fooBar(a)` with `upperCase(a)`.\nVERDICT: FAIL"
        self.assertEqual(sd.library_check(self.val_prompt, answer), (None, []))
        bad = answer.replace("upperCase(a)", "toUpperCaseX(a)")
        self.assertEqual(sd.library_check(self.val_prompt, bad)[1], ["toUpperCaseX"])


class TestJudgeDecision(unittest.TestCase):
    clean = {"accept": True, "verdict_match": True, **{k: [] for k in sd.REJECT_LISTS}}

    def test_accept(self):
        self.assertTrue(sd.decide_accept("validate", self.clean))
        self.assertTrue(sd.decide_accept("fix", {**self.clean, "verdict_match": None}))

    def test_any_nonempty_list_rejects(self):
        for key in sd.REJECT_LISTS:
            self.assertFalse(sd.decide_accept("generate", {**self.clean, key: ["x"]}), key)

    def test_extra_real_findings_do_not_reject(self):
        self.assertTrue(sd.decide_accept("validate", {**self.clean, "extra_real_findings": ["proved"]}))

    def test_validate_needs_verdict_match_and_judge_flag(self):
        self.assertFalse(sd.decide_accept("validate", {**self.clean, "verdict_match": None}))
        self.assertFalse(sd.decide_accept("fix", {**self.clean, "accept": False}))
        self.assertFalse(sd.decide_accept("fix", {**self.clean, "accept": "true"}))

    def test_prompts_build(self):
        prompt = {"task_type": "validate", "component": "ROLLUP", "user": "U", "reference": "R"}
        system = sd.build_judge_system("validate", function_lookup=True)
        self.assertIn("Rubric — validate", system)
        self.assertIn("ctl_function_info", system)
        user = sd.build_judge_user(prompt, "C")
        self.assertLess(user.index("<reference>"), user.index("<candidate>"))
        swapped = sd.build_judge_user(prompt, "C", reference_first=False)
        self.assertLess(swapped.index("<candidate>"), swapped.index("<reference>"))


class TestMetadataFromLlm(unittest.TestCase):
    task = ("Input ReceiptLine (port 0) has warehouse_id (string, non-null) and units (integer, nullable). "
            "Port 1 RateCard has warehouse_id (string) and rate (decimal). Output WarehouseSummary has "
            "warehouse_id (string) and total (decimal). Accumulator ReceiptAcc has tags (string list).")

    def _data(self, **over):
        data = {"complete": True, "records": [
            {"role": "input", "port": 0, "record_name": "ReceiptLine", "fields": [
                {"name": "warehouse_id", "type": "string", "container": None, "nullable": False},
                {"name": "units", "type": "integer", "container": None, "nullable": True}]},
            {"role": "input", "port": 1, "record_name": "RateCard", "fields": [
                {"name": "warehouse_id", "type": "string", "container": None, "nullable": None},
                {"name": "rate", "type": "decimal", "container": None, "nullable": None}]},
            {"role": "output", "port": 0, "record_name": "WarehouseSummary", "fields": [
                {"name": "warehouse_id", "type": "string", "container": None, "nullable": None},
                {"name": "total", "type": "decimal", "container": None, "nullable": None}]},
            {"role": "accumulator", "port": None, "record_name": "ReceiptAcc", "fields": [
                {"name": "tags", "type": "string", "container": "list", "nullable": None}]},
        ]}
        data.update(over)
        return data

    def test_ok_round_trips_through_the_tools_port_extraction(self):
        from dpo_forge.ctl_validate_mcp import extract_ports_metadata
        status, compile_prompt, problems = sd.metadata_from_llm(self._data(), self.task)
        self.assertEqual((status, problems), ("ok", []))
        inputs, outputs, acc = extract_ports_metadata(compile_prompt)
        self.assertEqual([('name="ReceiptLine"' in x, 'name="RateCard"' in x) for x in inputs],
                         [(True, False), (False, True)])  # port order preserved
        self.assertEqual(len(outputs), 1)
        self.assertIn('name="WarehouseSummary"', outputs[0])
        self.assertIn('<Field name="tags" type="string" containerType="list"/>', acc)
        self.assertIn('<Field name="warehouse_id" type="string" nullable="false"/>', inputs[0])

    def test_invented_field_is_rejected(self):
        data = self._data()
        data["records"][2]["fields"].append({"name": "average_value", "type": "decimal"})
        status, _, problems = sd.metadata_from_llm(data, self.task)
        self.assertEqual(status, "invalid")
        self.assertIn("field 'average_value' is not in the task", problems)

    def test_unknown_type_and_port_gap_are_rejected(self):
        data = self._data()
        data["records"][0]["fields"][0]["type"] = "varchar"
        data["records"][1]["port"] = 2
        status, _, problems = sd.metadata_from_llm(data, self.task)
        self.assertEqual(status, "invalid")
        self.assertTrue(any("unknown type 'varchar'" in p for p in problems))
        self.assertTrue(any("input ports" in p for p in problems))

    def test_incomplete_is_not_used(self):
        self.assertEqual(sd.metadata_from_llm(self._data(complete=False), self.task)[0], "incomplete")

    def test_compile_label(self):
        self.assertEqual(sd.compile_label({"status": "pass", "metadata_source": "synthesized"}), "pass/synth")
        self.assertEqual(sd.compile_label({"status": "pass", "metadata_source": "prompt"}), "pass")


class TestClaimsCheck(unittest.TestCase):
    def test_decision(self):
        clean = {"clean": True, "answer_false_claims": [], "uncorrected_trace_false_claims": [],
                 "corrected_trace_false_claims": [{"claim": "x", "corrected_by": "y"}]}
        self.assertTrue(sd.decide_claims_clean(clean))  # self-corrected claims are allowed
        self.assertFalse(sd.decide_claims_clean({**clean, "answer_false_claims": [{"claim": "a"}]}))
        self.assertFalse(sd.decide_claims_clean({**clean, "uncorrected_trace_false_claims": [{"claim": "t"}]}))
        self.assertFalse(sd.decide_claims_clean({**clean, "clean": False}))

    def test_prompt_contains_trace_and_answer(self):
        prompt = {"task_type": "fix", "component": "ROLLUP", "user": "U"}
        user = sd.build_claims_user(prompt, "THE TRACE", "THE ANSWER")
        self.assertIn("<trace>\nTHE TRACE\n</trace>", user)
        self.assertIn("<answer>\nTHE ANSWER\n</answer>", user)
        self.assertIn("ctl_function_info", sd.build_claims_system(function_lookup=True))

    def test_claims_purpose_gets_function_lookup(self):
        cfg = sd.judge_config({"judge": {"function_lookup": {"purposes": ["review"]}}})
        self.assertIn("selfdistill_claims", cfg["function_lookup"]["purposes"])


class TestAssembleHelpers(unittest.TestCase):
    def test_random_choice_not_shortest_biased(self):
        accepted = [{"sample_idx": i, "thinking": "w " * (10 * (i + 1))} for i in range(4)]
        picks = {sd.pick_accepted(accepted, random.Random(s))["sample_idx"] for s in range(200)}
        self.assertEqual(picks, {0, 1, 2, 3})

    def test_split_label(self):
        self.assertEqual(sd.split_label(0, 4), "0/k")
        self.assertEqual(sd.split_label(2, 4), "1..k-1/k")
        self.assertEqual(sd.split_label(4, 4), "k/k")

    def test_trace_stats(self):
        s = sd.trace_stats(["Wait, let me check this.", "plain words only"])
        self.assertEqual((s["wait_rate"], s["let_me_rate"], s["check_verify_rate"]), (0.5, 0.5, 0.5))

    def test_jsonl_tolerates_torn_line_and_last_write_wins(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            path = out / "samples.shard0.jsonl"
            sd.append_jsonl(path, [{"prompt_id": "p", "sample_idx": 0, "v": 1}])
            with path.open("a") as fh:
                fh.write('{"prompt_id": "p", "sample')
                fh.write("\n")
            sd.append_jsonl(path, [{"prompt_id": "p", "sample_idx": 0, "v": 2}])
            self.assertEqual(sd.load_samples(out)[("p", 0)]["v"], 2)

    def test_convert_think_round_trip(self):
        import convert_think
        rec = {"messages": [{"role": "user", "content": "u"},
                            {"role": "assistant", "content": "answer", "reasoning_content": "  trace  "}]}
        tagged, n = convert_think.transform_records([rec], only_reasoning=True)
        self.assertEqual(n, 1)
        self.assertEqual(tagged[0]["messages"][1]["content"], "<think>\ntrace\n</think>\n\nanswer")
        self.assertNotIn("reasoning_content", tagged[0]["messages"][1])


class TestGeneratedLength(unittest.TestCase):
    def test_first_stop_ends_sequence_and_padding_is_ignored(self):
        self.assertEqual(sd.generated_length([5, 6, 2, 2, 2], {2}), (3, False))

    def test_no_stop_means_cap(self):
        self.assertEqual(sd.generated_length([5, 6, 7], {2, 9}), (3, True))


class TestPlanOption(unittest.TestCase):
    def test_parse_plan(self):
        self.assertEqual(sd.parse_plan("validate_pass_warn:15, fix_tier1:2"),
                         (("validate", "validate_pass_warn", 15), ("fix", "fix_tier1", 2)))
        with self.assertRaises(SystemExit):
            sd.parse_plan("pass_warn:15")


class TestSampleReuse(unittest.TestCase):
    MUT = {"model_path": "/models/teacher", "max_new_tokens": 16384, "reasoning_effort": "medium",
           "chat_template_name": "qwen3_8",
           "validate": {"system_prompt": "SYS", "temperature": 0.4, "top_p": 0.95, "top_k": 20},
           "generate": {"system_prompt": "SYS", "temperature": 0.4, "top_p": 0.95, "top_k": 20}}

    def _row(self, pid, j, **over):
        row = {"prompt_id": pid, "sample_idx": j, "task_type": "generate", "thinking": "t", "answer": "a",
               "system_prompt": "SYS", "teacher_model": "/models/teacher",
               "seed": 0 + int(pid[:8], 16) % 1_000_000,
               "sampling": {"temperature": 0.4, "top_p": 0.95, "top_k": 20, "repetition_penalty": 1.0,
                            "max_new_tokens": 16384, "reasoning_effort": "medium", "chat_template_name": "qwen3_8"}}
        row.update(over)
        return row

    def _run(self, root, name, prompts, rows):
        d = root / name
        d.mkdir()
        (d / "prompts.jsonl").write_text("".join(json.dumps(p) + "\n" for p in prompts))
        (d / "samples.shard0.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_only_exact_matches_are_reused(self):
        good, text, param, seed = "a" * 16, "b" * 16, "c" * 16, "d" * 16
        pool = [{"prompt_id": pid, "task_type": "generate", "user": "U " + pid} for pid in (good, text, param, seed)]
        src_prompts = [{"prompt_id": good, "user": "U " + good}, {"prompt_id": text, "user": "older wording"},
                       {"prompt_id": param, "user": "U " + param}, {"prompt_id": seed, "user": "U " + seed}]
        rows = [self._row(good, j) for j in range(4)] + [self._row(text, j) for j in range(4)]
        rows += [self._row(param, j, sampling={**self._row(param, j)["sampling"], "max_new_tokens": 2048}) for j in range(4)]
        rows += [self._row(seed, j, seed=7) for j in range(4)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._run(root, "old", src_prompts, rows)
            found = sd.find_reusable_samples(["old"], pool, self.MUT, seed=0, k=4, runs_dir=root)
            self.assertEqual(set(found), {good})
            (root / "new").mkdir()
            report = sd.import_samples(root / "new", [{"prompt_id": good}], found, root, ["old"])
            self.assertEqual(report["prompts"], 1)
            copied = sd.load_samples(root / "new")
            self.assertEqual(sorted(copied), [(good, j) for j in range(4)])
            self.assertTrue(all(r["reused_from"] == "old" for r in copied.values()))

    def test_selection_prefers_reusable_prompts(self):
        pool = [{"prompt_id": f"g{i}", "task_type": "generate", "component": "REFORMAT", "source_file": "x"}
                for i in range(20)]
        plan = (("generate", "generate_other", 3),)
        chosen, _ = sd.select_prompts(pool, seed=1, plan=plan, prefer=frozenset({"g5", "g9"}))
        self.assertTrue({"g5", "g9"} <= {p["prompt_id"] for p in chosen})

    def test_output_names(self):
        records, train = sd.output_paths(Path("/r"), "full1")
        self.assertEqual((records.name, train.name), ("selfdistill_full1_records.json", "selfdistill_full1_train.json"))


class TestKnownFalseBeliefs(unittest.TestCase):
    def test_hits(self):
        self.assertEqual(sd.belief_hits("5. `dateAdd($in.0.day, 1L, day)` mutates the date."),
                         ["dateAdd mutates its argument"])
        self.assertEqual(sd.belief_hits("`byte2hex` accepts exactly one `byte` argument."),
                         ["byte2hex takes one argument"])
        self.assertEqual(sd.belief_hits("Use getWeek($in.0.d) for the week."), ["getWeek() is a function"])
        for code in ('if ($in.0.status in ["BACKORDER", "PARTIAL"]) {', "if ($in.0.code in allowedCodes) {",
                     'boolean hit = code in ["X", "Y"];', 'if ($in.0.cur !in ["SEK", "NOK"]) {'):
            self.assertEqual(sd.belief_hits(code), ["infix `in` operator"], code)

    def test_declared_null_default(self):
        name = "declared variables start null"
        for text in ("A module-level `string[]` defaults to `null` in CTL2.",
                     "**`lastOrderDate` not initialised** – A module-level `date` defaults to `null`.",
                     "`skills` is declared without an initializer, so it starts as `null`.",
                     "CTL2 date variables default to null.",
                     "`statuses` has no initializer → defaults to `null`.",
                     "The list is null by default (`string[] folderSegments;`)."):
            self.assertIn(name, sd.belief_hits(text), text)
        for text in ("Declared variables start at their type defaults, not null.",
                     "A declared list is not null by default; it is empty.",
                     "An accumulator field not assigned in initGroup starts as null.",
                     "A declared `variant` defaults to null.",
                     "`order_amount` is nullable, so a null amount throws in the sum."):
            self.assertNotIn(name, sd.belief_hits(text), text)

    def test_infix_in_ignores_valid_calls_and_prose(self):
        for text in ('if (in($in.0.status, ["BACKORDER", "PARTIAL"])) {', "$in.0.status.in(codes)",
                     "abv_percent must be non-null and in [0, 96].", "The rules are evaluated in order):",
                     "Capture $in.0.sensor_id in append? Or in transform?", 'if (!in($in.0.cur, ["SEK"])) {'):
            self.assertEqual(sd.belief_hits(text), [], text)

    def test_negated_and_true_statements_pass(self):
        for text in ("`=` makes a deep copy; it does not alias the list.",
                     "dateAdd never mutates the date; it returns a new one.",
                     "`isNull(record, string)` exists; `isnull(any)` tests one value.",
                     "Writing $out.1 on an unconnected port does not compile."):
            self.assertEqual(sd.belief_hits(text), [], text)


class TestAssemblePostFilterRejects(unittest.TestCase):
    def test_audit_reject_and_belief_scan_repick(self):
        import argparse
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r"
            out.mkdir()
            prompt = {"prompt_id": "p" * 16, "task_type": "fix", "component": "REFORMAT", "user": "U",
                      "reference": "R", "source_file": "f.json", "source_index": 0, "source_id": "x",
                      "record_id": "x"}
            (out / "prompts.jsonl").write_text(json.dumps(prompt) + "\n")
            answers = ["plain answer 0", "`dateAdd(d, 1L, day)` mutates the date.", "plain answer 2"]
            rows = [{"prompt_id": prompt["prompt_id"], "sample_idx": j, "task_type": "fix", "thinking": f"trace {j}",
                     "answer": a, "prompt_tokens": 10, "new_tokens": 10, "system_prompt": "S", "teacher_model": "t",
                     "sampling": {}, "seed": 0} for j, a in enumerate(answers)]
            (out / "samples.shard0.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            (out / "judged.jsonl").write_text("".join(json.dumps(
                {"prompt_id": prompt["prompt_id"], "sample_idx": j, "task_type": "fix", "accepted": True,
                 "rejected_at": None, "reason": None}) + "\n" for j in range(3)))
            (out / "audit_rejects.json").write_text(json.dumps(
                [{"prompt_id": prompt["prompt_id"], "sample_idx": 0, "reason": "false claim"}]))
            args = argparse.Namespace(run="r", runs_dir=d, seed=0, cutoff=8192, allow_incomplete=False)
            self.assertEqual(sd.cmd_assemble(args), 0)
            kept = json.loads((out / "selfdistill_r_records.json").read_text())
            self.assertEqual([r["sample_idx"] for r in kept], [2])   # 0 audited out, 1 states a false belief
            self.assertEqual(kept[0]["accepted_of_k"], "1/3")
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(set(report["post_filter_rejects"]), {prompt["prompt_id"] + "#0", prompt["prompt_id"] + "#1"})


class TestShard(unittest.TestCase):
    def test_parse_shard(self):
        self.assertEqual(sd.parse_shard("1/2"), (1, 2))
        with self.assertRaises(SystemExit):
            sd.parse_shard("2/2")


if __name__ == "__main__":
    unittest.main()
