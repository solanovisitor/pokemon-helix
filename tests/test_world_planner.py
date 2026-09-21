from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from pydantic import ValidationError

from game_agents.world_planner import (
    BASELINE, ROLES, WorldObservations, WorldPlan, WorldPlannerStore,
)

ROOT = Path(__file__).resolve().parents[1]
DAY = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


class WorldPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "state.sqlite3"
        self.store = WorldPlannerStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_daily_claim_restart_and_no_catchup(self):
        first = self.store.tick(now=DAY)
        self.assertEqual(first["status"], "accepted")
        self.assertEqual(first["latest_plan"]["revision"], 1)
        restarted = WorldPlannerStore(self.path)
        called = []
        same = restarted.tick(now=DAY + timedelta(hours=4),
                              provider=lambda request: called.append(request))
        self.assertEqual(same, first)
        self.assertEqual(called, [])
        later = restarted.tick(now=DAY + timedelta(days=400))
        self.assertEqual(later["latest_plan"]["revision"], 2)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM world_cycles").fetchone()[0], 2)
            rows = db.execute("SELECT id,previous_plan_id FROM world_plans ORDER BY id").fetchall()
            self.assertEqual(rows[1][1], rows[0][0])
        self.assertEqual(self.store.tick(now=DAY - timedelta(days=1))["status"], "outdated")

    def test_day_bucket_uses_utc_not_local_clock(self):
        self.store.tick(now=DAY)
        local = datetime(2026, 9, 20, 22, tzinfo=timezone(timedelta(hours=-3)))
        self.assertEqual(self.store.tick(now=local)["cycle"], "2026-09-21")
        with self.assertRaises(ValueError):
            self.store.tick(now=datetime(2026, 9, 20))

    def test_concurrent_ticks_invoke_exactly_once(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def provider(request):
            calls.append(request)
            entered.set()
            self.assertTrue(release.wait(5))
            return BASELINE.model_dump()

        with ThreadPoolExecutor(max_workers=9) as pool:
            first = pool.submit(self.store.tick, now=DAY, provider=provider)
            self.assertTrue(entered.wait(5))
            others = [pool.submit(WorldPlannerStore(self.path).tick, now=DAY, provider=provider)
                      for _ in range(8)]
            self.assertEqual([future.result()["status"] for future in others], ["running"] * 8)
            release.set()
            self.assertEqual(first.result()["status"], "accepted")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.latest_plan()["revision"], 1)

    def test_unknown_provider_never_retried_and_last_good_remains(self):
        original = self.store.tick(now=DAY)["latest_plan"]
        calls = []

        def fail(request):
            calls.append(request)
            raise TimeoutError("private-canary-provider-text")

        failed = self.store.tick(now=DAY + timedelta(days=1), provider=fail)
        self.assertEqual(failed["status"], "unknown")
        self.assertEqual(failed["latest_plan"], original)
        again = WorldPlannerStore(self.path).tick(now=DAY + timedelta(days=1), provider=fail)
        self.assertEqual(again, failed)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("canary", json.dumps(self.store.status()))
        self.assertEqual(self.store.tick(now=DAY + timedelta(days=2))["latest_plan"]["revision"], 2)

    def test_retained_cycle_does_not_require_missing_private_config(self):
        accepted = self.store.tick(now=DAY)
        replay = self.store.tick(now=DAY, private_canon_path=self.root / ".local/missing.json",
                                 observations={"unexpected_private_text": "canary"})
        self.assertEqual(replay, accepted)

    def test_database_created_with_owner_only_permissions(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_crash_claim_becomes_unknown_without_reissuing(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""INSERT INTO world_cycles(world,cycle,status,claimed_at,claim_token,
                       mode,input_digest) VALUES(?,?,'running',?,'stopped','live','digest')""",
                       ("local-world", "2026-09-20", DAY.isoformat()))
        self.assertEqual(self.store.tick(now=DAY)["status"], "running")
        self.assertEqual(self.store.mark_stale_unknown(now=DAY + timedelta(minutes=6)), 1)
        self.assertEqual(self.store.tick(now=DAY + timedelta(minutes=7))["status"], "unknown")
        self.assertIsNone(self.store.latest_plan())

    def test_recovered_claim_cannot_late_commit(self):
        def callback(request):
            self.store.mark_stale_unknown(now=DAY + timedelta(minutes=10))
            return BASELINE.model_dump()
        self.assertEqual(self.store.tick(now=DAY, provider=callback)["status"], "unknown")
        self.assertIsNone(self.store.latest_plan())

    def test_out_of_order_completion_cannot_rewrite_lineage(self):
        def older(request):
            self.store.tick(now=DAY + timedelta(days=1))
            return BASELINE.model_dump()
        result = self.store.tick(now=DAY, provider=older)
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(result["latest_plan"]["cycle"], "2026-09-21")

    def test_active_adventure_pin_survives_reload_and_future_plans(self):
        self.store.tick(now=DAY)
        before = {role: self.store.project_context(role, adventure_id="accepted-adventure")
                  for role in ROLES}
        for day in range(1, 12):
            self.store.tick(now=DAY + timedelta(days=day))
        restarted = WorldPlannerStore(self.path)
        after = {role: restarted.project_context(role, adventure_id="accepted-adventure")
                 for role in ROLES}
        self.assertEqual(before, after)
        fresh = restarted.project_context("world", adventure_id="new-adventure")
        self.assertEqual(fresh["plan_revision"], 12)
        self.assertEqual(restarted.status()["pinned_adventures"], 2)

    def test_preexisting_offline_adventure_can_pin_baseline(self):
        baseline = self.store.project_context("scene", adventure_id="offline-save")
        self.assertEqual(baseline["plan_revision"], 0)
        self.store.tick(now=DAY)
        self.assertEqual(self.store.project_context("scene", adventure_id="offline-save"), baseline)

    def test_pin_digest_detects_valid_enum_data_corruption(self):
        self.store.project_context("scene", adventure_id="offline-save")
        changed = {**BASELINE.model_dump(), "pace": "steady"}
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE world_adventure_pins SET plan_json=?", (json.dumps(changed),))
        with self.assertRaisesRegex(ValueError, "stored plan integrity check failed"):
            self.store.project_context("scene", adventure_id="offline-save")

    def test_corrupted_previous_plan_is_not_passed_to_provider(self):
        self.store.tick(now=DAY, provider=lambda _: BASELINE.model_dump())
        changed = {**BASELINE.model_dump(), "pace": "steady"}
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE world_plans SET plan_json=?", (json.dumps(changed),))
        called = []
        with self.assertRaisesRegex(ValueError, "stored plan integrity check failed"):
            self.store.tick(now=DAY + timedelta(days=1), provider=lambda request: called.append(request))
        self.assertEqual(called, [])

    def test_strict_plan_and_smooth_change_validation(self):
        for mutation in ({"rationale": "private-canary"}, {"story_focus": "erase_saves"},
                         {"schema_version": True}, {"pace": "steady; execute"}):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                WorldPlan.model_validate({**BASELINE.model_dump(), **mutation})
        self.store.tick(now=DAY, provider=lambda _: BASELINE.model_dump())
        too_many = {**BASELINE.model_dump(), "story_focus": "exploration",
                    "ecology": "reed_growth", "pace": "steady"}
        result = self.store.tick(now=DAY + timedelta(days=1), provider=lambda _: too_many)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["latest_plan"]["revision"], 1)
        self.assertEqual(self.store.tick(now=DAY + timedelta(days=1))["status"], "rejected")

    def test_forged_model_instance_is_revalidated(self):
        forged = WorldPlan.model_construct(**{**BASELINE.model_dump(), "pace": "private-canary"})
        result = self.store.tick(now=DAY, provider=lambda _: forged)
        self.assertEqual(result["status"], "rejected")

    def test_private_canon_only_reaches_master_callback(self):
        local = self.root / ".local"
        local.mkdir()
        canon = local / "canon.json"
        canary = "private-canary-9284-unknown-to-characters"
        canon.write_text(json.dumps({"concealed_author_notes": canary}))
        requests = []

        def provider(request):
            requests.append(request)
            return BASELINE.model_dump()

        self.store.tick(now=DAY, provider=provider, private_canon_path=canon,
                        observations={"births": 17})
        self.assertEqual(requests[0]["private_canon"]["concealed_author_notes"], canary)
        self.assertEqual(requests[0]["observations"]["births"], 17)
        for role in ROLES:
            context = self.store.project_context(role, adventure_id=canary)
            self.assertNotIn(canary, json.dumps(context))
            self.assertEqual(context["runtime_action"], "none")
            self.assertEqual(context["status"], "draft")
        self.assertNotIn(canary, json.dumps(self.store.status()))
        for path in self.root.glob("state.sqlite3*"):
            self.assertNotIn(canary.encode(), path.read_bytes())

    def test_rejected_private_output_never_retained(self):
        canary = "private-canary-9284"
        result = self.store.tick(now=DAY, provider=lambda _: {**BASELINE.model_dump(), "secret": canary})
        self.assertEqual(result["status"], "rejected")
        for path in self.root.glob("state.sqlite3*"):
            self.assertNotIn(canary.encode(), path.read_bytes())

    def test_untrusted_observations_and_public_scopes_are_rejected(self):
        for observation in ({"births": True}, {"births": -1}, {"births": "1"},
                            {"births": 1_000_000_001}, {"dialogue": "private"}):
            with self.subTest(observation=observation), self.assertRaises(ValidationError):
                self.store.tick(now=DAY, observations=observation)
        for args in (("private",), ("npc", "unregistered")):
            with self.assertRaises(ValueError):
                self.store.project_context(*args)
        self.assertIsNone(self.store.status()["latest_cycle"])

    def test_private_canon_must_be_local_bounded_unique_json(self):
        bad = self.root / "public.json"
        bad.write_text('{}')
        with self.assertRaises(ValueError):
            self.store.tick(now=DAY, private_canon_path=bad)
        local = self.root / ".local"
        local.mkdir()
        path = local / "canon.json"
        for raw in ('{"key":1,"key":2}', '[]', '{"key":NaN}', '{"key":"' + 'x'*8192 + '"}'):
            path.write_text(raw)
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                self.store.tick(now=DAY, private_canon_path=path)
        self.assertIsNone(self.store.status()["latest_cycle"])

    def test_worlds_have_separate_lineage_and_pins(self):
        other = WorldPlannerStore(self.path, "other-world")
        self.store.tick(now=DAY)
        other.project_context("world", adventure_id="same-adventure-id")
        self.store.project_context("world", adventure_id="same-adventure-id")
        self.assertIsNone(other.latest_plan())
        self.assertEqual(other.project_context("world", adventure_id="same-adventure-id")["plan_revision"], 0)
        self.assertEqual(self.store.project_context("world", adventure_id="same-adventure-id")["plan_revision"], 1)

    def test_cli_scheduler_restarts_without_duplicate_generation(self):
        command = [sys.executable, str(ROOT / "scripts/world-planner.py"), "serve",
                   "--state", str(self.path), "--poll-seconds", "1", "--max-ticks", "2"]
        first = subprocess.run(command, check=True, capture_output=True, text=True)
        second = subprocess.run(command, check=True, capture_output=True, text=True)
        self.assertEqual(len(first.stdout.splitlines()), 1)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(json.loads(first.stdout)["latest_plan"]["revision"], 1)
        self.assertEqual(self.store.latest_plan()["revision"], 1)

    def test_cli_scheduler_recovers_from_repaired_observations(self):
        observations = self.root / "counts.json"
        observations.write_text('{"births":"private-canary-invalid"}')
        command = [sys.executable, str(ROOT / "scripts/world-planner.py"), "serve",
                   "--state", str(self.path), "--poll-seconds", "1", "--max-ticks", "3",
                   "--observations", str(observations)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            first = process.stdout.readline()
            self.assertEqual(json.loads(first), {"status": "error", "error_code": "invalid_configuration_or_state"})
            self.assertIsNone(self.store.latest_plan())
            observations.write_text('{"births":7}')
            stdout, stderr = process.communicate(timeout=6)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(len(stdout.splitlines()), 1)
            self.assertEqual(json.loads(stdout)["status"], "accepted")
            self.assertNotIn("private-canary", first + stdout + stderr)
            self.assertEqual(self.store.latest_plan()["revision"], 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
