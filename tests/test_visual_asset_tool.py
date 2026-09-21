"""Public visual candidates with offline fixtures and a mocked fixed image API."""
import base64
from copy import deepcopy
import fcntl
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import struct
import zlib
from unittest.mock import patch

from pydantic import TypeAdapter

from genetics.primers import canonical, digest
from genetics.roster import decode_png, gba_asset
from game_agents import visual_asset_tool as visual


BRIEF = ["An original blue watering pot with a wide handle."]


class VisualAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = visual.VisualAssetRuntime(self.root / "cache")

    def result(self, runtime=None, asset_type="sprite", prompts=None):
        result = (runtime or self.runtime).generate(asset_type, BRIEF if prompts is None else prompts)
        TypeAdapter(visual.VisualAssetResult).validate_python(result)
        return result

    def live(self, provider):
        return visual.VisualAssetRuntime(self.root / "live", config=visual.VisualAssetConfig(
            mode="openai", model=visual.MODEL), provider=provider)

    def test_both_fixture_types_are_concrete_validated_assets_and_no_network(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            for asset_type, dimensions in visual.DIMENSIONS.items():
                result = self.result(asset_type=asset_type)
                self.assertEqual(result["status"], "ready")
                self.assertTrue(result["fixture"])
                self.assertFalse(result["cache_hit"])
                self.assertEqual(result["scope"], "validated_asset_only")
                self.assertEqual(result["native_admission"], "none")
                self.assertEqual(result["visual_review"], "not_performed")
                directory = self.root / "cache" / result["request_id"]
                native = (directory / "asset.png").read_bytes()
                tiles, palette = gba_asset(native, width=dimensions[0], height=dimensions[1])
                self.assertEqual(tiles, (directory / "asset.4bpp").read_bytes())
                self.assertEqual(palette, (directory / "palette.gbapal").read_bytes())
                self.assertEqual(len(tiles), dimensions[0] * dimensions[1] // 2)
                self.assertEqual(len(palette), 32)
                self.assertEqual(decode_png(native)[:4], (*dimensions, 4, 3))

    def test_restart_replay_retains_exact_objects_and_does_not_regenerate(self):
        first = self.result()
        directory = self.root / "cache" / first["request_id"]
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir() if p.name != ".lock"}
        restarted = visual.VisualAssetRuntime(self.root / "cache")
        with patch.object(visual, "_fixture", side_effect=AssertionError("regeneration forbidden")):
            second = self.result(restarted)
        self.assertTrue(second["cache_hit"])
        self.assertEqual({**first, "cache_hit": True}, second)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir() if p.name != ".lock"})

    def test_full_contract_changes_are_distinct(self):
        request = visual.AssetRequest(asset_type="sprite", prompts=BRIEF)
        original = self.runtime._contract(request)
        for changed in (visual.AssetRequest(asset_type="item_icon", prompts=BRIEF),
                        visual.AssetRequest(asset_type="sprite", prompts=["A red watering pot."])):
            self.assertNotEqual(digest(original), digest(self.runtime._contract(changed)))
        pt = visual.VisualAssetRuntime(self.root / "pt", config=visual.VisualAssetConfig(locale="pt-BR"))
        self.assertNotEqual(digest(original), digest(pt._contract(request)))
        self.assertNotEqual(digest(original), digest(self.live(lambda _: b"")._contract(request)))
        read_bytes = Path.read_bytes
        for relative in original["dependencies"]:
            def drift(path):
                raw = read_bytes(path)
                return raw + b"\n" if path == visual.ROOT / relative else raw
            with patch.object(Path, "read_bytes", drift):
                self.assertNotEqual(digest(original), digest(self.runtime._contract(request)))

    def test_invalid_types_private_identifiers_paths_and_hidden_lore_do_not_create_jobs(self):
        invalid = [("map", BRIEF), ("sprite", []), ("sprite", ["a"] * 5),
                   ("sprite", ["a" * 401]), ("sprite", [" leading"]),
                   ("sprite", ["Use https://example.test/image.png"]),
                   ("sprite", ["Read /synthetic/private/photo.png"]),
                   ("sprite", ["trainer_id 12"]), ("sprite", ["ab" * 32]),
                   ("sprite", ["someone@example.test"]), ("sprite", ["Veilwarden"]),
                   ("sprite", ["The fixture secret is amber."]), ("sprite", ["O segredo de teste e ambar."])]
        for kind, prompts in invalid:
            with self.subTest(kind=kind, prompt_length=len(str(prompts))):
                result = self.result(asset_type=kind, prompts=prompts)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["code"], "invalid_request")
                self.assertNotIn(str(prompts), json.dumps(result))
        self.assertEqual(list((self.root / "cache").iterdir()), [])

    def test_input_schema_rejects_profiles_paths_models_and_code_channels(self):
        for extra in ("profile", "individual_id", "output_path", "model", "execute", "image_url"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                visual.AssetRequest.model_validate({"asset_type": "sprite", "prompts": BRIEF, extra: "private"})
        with self.assertRaises(ValueError):
            visual.VisualAssetConfig(mode="openai")
        with self.assertRaises(ValueError):
            visual.VisualAssetRuntime(self.root / "wrong", provider=lambda _: b"")

    def test_cached_bytes_and_self_forged_manifest_are_revalidated(self):
        result = self.result()
        directory = self.root / "cache" / result["request_id"]
        for forged_binding in (False, True):
            original = (directory / "asset.4bpp").read_bytes()
            manifest_raw = (directory / "manifest.json").read_bytes()
            tampered = bytes([original[0] ^ 1]) + original[1:]
            (directory / "asset.4bpp").write_bytes(tampered)
            if forged_binding:
                manifest = json.loads(manifest_raw)
                manifest["files"]["asset.4bpp"] = sha256(tampered).hexdigest()
                manifest["asset_id"] = digest({"request_id": result["request_id"], "files": manifest["files"]})
                (directory / "manifest.json").write_bytes(canonical(manifest))
            with patch.object(visual, "_fixture", side_effect=AssertionError("regeneration forbidden")):
                self.assertEqual(self.result()["code"], "cache_invalid")
            self.assertEqual((directory / "asset.4bpp").read_bytes(), tampered)
            (directory / "asset.4bpp").write_bytes(original)
            (directory / "manifest.json").write_bytes(manifest_raw)

    def test_symlink_cache_object_is_refused_without_touching_target(self):
        result = self.result()
        target = self.root / "outside"
        target.write_bytes(b"private sentinel")
        path = self.root / "cache" / result["request_id"] / "asset.png"
        path.unlink()
        path.symlink_to(target)
        self.assertEqual(self.result()["code"], "cache_invalid")
        self.assertEqual(target.read_bytes(), b"private sentinel")

    def test_fifo_cache_object_is_refused_without_blocking_or_regeneration(self):
        result = self.result()
        path = self.root / "cache" / result["request_id"] / "source.png"
        path.unlink()
        os.mkfifo(path)
        code = """
import json,sys
from unittest.mock import patch
from game_agents.visual_asset_tool import VisualAssetRuntime
with patch('game_agents.visual_asset_tool._fixture', side_effect=AssertionError('regeneration forbidden')):
    result = VisualAssetRuntime(sys.argv[1]).generate('sprite', json.loads(sys.argv[2]))
assert result['status'] == 'rejected' and result['code'] == 'cache_invalid', result
"""
        child = subprocess.run([sys.executable, "-c", code, str(self.root / "cache"), json.dumps(BRIEF)],
                               capture_output=True, timeout=5)
        self.assertEqual(child.returncode, 0, child.stderr.decode())

    def test_one_live_call_then_identical_cache_reuse(self):
        calls = []
        def provider(contract):
            calls.append(deepcopy(contract))
            return visual._fixture(contract)
        runtime = self.live(provider)
        first = self.result(runtime)
        second = self.result(runtime)
        self.assertEqual(first["status"], "ready")
        self.assertFalse(first["fixture"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn(str(self.root), json.dumps(calls))

    def test_unknown_external_outcome_is_durable_and_never_retried(self):
        calls = []
        def provider(contract):
            calls.append(contract)
            raise visual.ImageOutcomeUnknown("PRIVATE PROVIDER ERROR")
        runtime = self.live(provider)
        first = self.result(runtime)
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["code"], "outcome_unknown")
        restarted = self.live(lambda _: self.fail("provider retried"))
        self.assertEqual(self.result(restarted), first)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("PRIVATE", json.dumps(first))

    def test_active_lock_returns_pending_without_invoking_provider(self):
        request = visual.AssetRequest(asset_type="sprite", prompts=BRIEF)
        request_id = digest(self.runtime._contract(request))
        directory = self.root / "cache" / request_id
        directory.mkdir()
        with (directory / ".lock").open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            with patch.object(visual, "_fixture", side_effect=AssertionError("invocation forbidden")):
                self.assertEqual(self.result()["code"], "processing")

    def test_invalid_images_are_terminal_rejections_not_ready_or_second_calls(self):
        opaque = visual._png(8, 8, [b"\x40\x80\xc0\xff" * 8] * 8)
        empty = visual._png(8, 8, [b"\0" * 32] * 8)
        corrupt = bytearray(visual._fixture({})); corrupt[-1] ^= 1
        for index, raw in enumerate((b"not PNG", opaque, empty, bytes(corrupt), b"x" * (visual.MAX_PNG + 1))):
            calls = []
            def provider(_):
                calls.append(True)
                return raw
            runtime = visual.VisualAssetRuntime(self.root / f"bad-{index}",
                config=visual.VisualAssetConfig(mode="openai", model=visual.MODEL), provider=provider)
            first = self.result(runtime)
            self.assertEqual(first["code"], "invalid_image")
            self.assertEqual(self.result(runtime), first)
            self.assertEqual(len(calls), 1)

    def test_source_metadata_is_stripped_before_public_asset_cache(self):
        source = visual._fixture({})
        source = source[:-12] + visual._chunk(b"tEXt", b"comment\0PRIVATE_METADATA") + source[-12:]
        runtime = self.live(lambda _: source)
        result = self.result(runtime)
        self.assertEqual(result["status"], "ready")
        directory = self.root / "live" / result["request_id"]
        for name in result["files"]:
            self.assertNotIn(b"PRIVATE_METADATA", (directory / name).read_bytes())

    def test_inflated_excess_trailing_stream_and_invalid_preflight_are_rejected(self):
        for compressed in (zlib.compress(b"\0" * 100000),
                           zlib.compress(b"\0" * (8 * 4 + 1) * 8) + zlib.compress(b"private")):
            raw = (b"\x89PNG\r\n\x1a\n"
                   + visual._chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 6, 0, 0, 0))
                   + visual._chunk(b"IDAT", compressed) + visual._chunk(b"IEND", b""))
            with self.assertRaises(ValueError):
                visual._convert(raw, "sprite")
        raw = visual._fixture({})
        for header in (struct.pack(">IIBBBBB", 4096, 4096, 8, 6, 0, 0, 0),
                       struct.pack(">IIBBBBB", 64, 64, 16, 6, 0, 0, 0)):
            changed = raw[:8] + visual._chunk(b"IHDR", header) + raw[33:]
            with patch.object(visual, "decode_png", side_effect=AssertionError("decode forbidden")), \
                    self.assertRaises(ValueError):
                visual._convert(changed, "sprite")

    def test_started_contract_cannot_be_substituted_or_retried(self):
        runtime = self.live(lambda _: (_ for _ in ()).throw(visual.ImageOutcomeUnknown()))
        first = self.result(runtime)
        directory = self.root / "live" / first["request_id"]
        (directory / "started.json").write_text("{}")
        restarted = self.live(lambda _: self.fail("provider retried"))
        self.assertEqual(self.result(restarted)["code"], "cache_invalid")

    def test_real_structured_tool_exposes_only_two_arguments(self):
        tool = visual.build_visual_asset_tool(self.runtime)
        self.assertEqual(tool.name, "generate_visual_asset")
        self.assertEqual(set(tool.args), {"asset_type", "prompts"})
        self.assertEqual(tool.invoke({"asset_type": "item_icon", "prompts": BRIEF})["status"], "ready")
        invalid = [{"asset_type": "sprite", "prompts": BRIEF, "output_path": "/private"},
                   {"asset_type": "sprite", "prompts": ["Veilwarden"]},
                   {"asset_type": "map", "prompts": BRIEF},
                   {"asset_type": "sprite", "prompts": ["Read /synthetic/private/photo.png"]}]
        for value in invalid:
            result = tool.invoke(value)
            self.assertEqual(json.loads(result), visual.Rejected(code="invalid_request").model_dump())
            self.assertNotIn("Veilwarden", result)
            self.assertNotIn("/private", result)


class OpenAIImageProviderTests(unittest.TestCase):
    def contract(self):
        return {"image_request": {"model": visual.MODEL, "prompt": "One public fixture object.", "n": 1,
            "size": "1024x1024", "quality": "high", "background": "transparent", "output_format": "png"}}

    def test_exact_bounded_api_shape_with_base64_not_urls(self):
        raw = visual._fixture({})
        response = io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(raw).decode()}]}).encode())
        with patch.object(visual, "build_opener") as opener:
            opener.return_value.open.return_value = response
            provider = visual.OpenAIImageProvider("SYNTHETIC_KEY", timeout=12)
            self.assertEqual(provider(self.contract()), raw)
        opener.return_value.open.assert_called_once()
        call = opener.return_value.open.call_args
        request = call.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/images/generations")
        self.assertEqual(json.loads(request.data), self.contract()["image_request"])
        self.assertNotIn("response_format", json.loads(request.data))
        self.assertNotIn("SYNTHETIC_KEY", request.data.decode())
        self.assertNotIn("SYNTHETIC_KEY", repr(provider))
        self.assertEqual(call.kwargs["timeout"], 12)
        self.assertIsNone(visual._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test"))

    def test_network_error_is_generic_unknown_and_one_call(self):
        with patch.object(visual, "build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError("PRIVATE_BODY")
            with self.assertRaises(visual.ImageOutcomeUnknown) as caught:
                visual.OpenAIImageProvider("SYNTHETIC_KEY")(self.contract())
        opener.return_value.open.assert_called_once()
        self.assertNotIn("PRIVATE_BODY", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_direct_provider_cannot_expand_request_or_change_endpoint_parameters(self):
        for key, value in (("n", 2), ("n", True), ("model", "another-model"),
                           ("size", "4096x4096"), ("prompt", "x" * 2401),
                           ("image_url", "https://example.test/private.png")):
            contract = self.contract()
            contract["image_request"][key] = value
            with patch.object(visual, "build_opener") as opener, self.assertRaises(ValueError):
                visual.OpenAIImageProvider("SYNTHETIC_KEY")(contract)
            opener.assert_not_called()

    def test_rejects_url_fallback_multiple_images_invalid_base64_and_oversize(self):
        values = [{"data": [{"url": "https://example.test/art.png"}]}, {"data": []},
                  {"data": [{"b64_json": "AA=="}, {"b64_json": "AA=="}]},
                  {"data": [{"b64_json": "%%%"}]}, {"error": "PRIVATE_BODY"}]
        for value in values:
            with patch.object(visual, "build_opener") as opener:
                opener.return_value.open.return_value = io.BytesIO(json.dumps(value).encode())
                with self.assertRaises(ValueError) as caught:
                    visual.OpenAIImageProvider("SYNTHETIC_KEY")(self.contract())
                self.assertNotIn("PRIVATE_BODY", str(caught.exception))
                opener.return_value.open.assert_called_once()
        with patch.object(visual, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b"x" * (visual.MAX_RESPONSE + 1))
            with self.assertRaises(ValueError):
                visual.OpenAIImageProvider("SYNTHETIC_KEY")(self.contract())


if __name__ == "__main__":
    unittest.main()
