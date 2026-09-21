"""Joint generator tests; fixture data and mocked provider tests are not live proof."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_agents.npc_quest_generator import (DraftNarrative,JointProposal,NpcQuestQueue,
    request,fixture_narrative,assemble,validate_candidate,approved_context,export_candidate)
from genetics.primers import digest

class NpcQuestGeneratorTests(unittest.TestCase):
    def test_fixture_default_is_deterministic_varied_and_uninstalled(self):
        texts=set()
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            for seed in range(32):
                req=request(seed);a=assemble(req,fixture_narrative(seed));b=assemble(req,fixture_narrative(seed))
                self.assertEqual(a,b);validate_candidate(a)
                self.assertEqual(a['status'],'draft');self.assertEqual(a['runtime_action'],'none')
                self.assertEqual(a['budget']['provider_invocations'],0)
                self.assertEqual(len(a['quest_nodes']),7)
                texts.add(json.dumps(a['narrative'],sort_keys=True))
        self.assertEqual(len(texts),32)

    def test_unknown_actions_rewards_topology_and_release_are_refused(self):
        original=assemble(request(1),fixture_narrative(1))
        for mutate in [lambda x:x.update(runtime_action='install'),lambda x:x['quest_nodes'][0].update(effects=['grant_pokemon']),lambda x:x['map_contract']['map']['return_destination'].update(map='UNKNOWN'),lambda x:x['budget'].update(provider_invocations=100),lambda x:x.update(private_canon={})]:
            bad=deepcopy(original);mutate(bad)
            with self.assertRaises(ValueError):validate_candidate(bad)

    def test_clues_hypotheses_facts_roles_and_text_budgets_are_checked(self):
        original=fixture_narrative(1)
        for mutate in [lambda x:x['statements'][2].update(kind='confirmed_fact'),lambda x:x['statements'][4].update(evidence='never_confirmed'),lambda x:x['npcs'][1].update(role='caretaker'),lambda x:x['npcs'][0]['greeting'].update(en='{CALL}'),lambda x:x['npcs'][0]['greeting'].update(pt='A'*33),lambda x:x['npcs'][0]['greeting'].update(pt='='*32)]:
            bad=deepcopy(original);mutate(bad)
            with self.assertRaises(ValueError):DraftNarrative.model_validate(bad)

    def test_invalid_seed_or_implicit_live_model_is_refused(self):
        for seed in [-1,2**32,True,'2']:
            with self.assertRaises(ValueError):request(seed)
        with self.assertRaises(ValueError):request(1,mode='deepagents')
        with self.assertRaises(ValueError):request(1,model='vendor/model')

    def test_budget_counts_model_calls_separately_from_one_agent_attempt(self):
        req=request(5,mode='deepagents',model='selected/model')
        candidate=assemble(req,fixture_narrative(5))
        self.assertEqual(req['generator'],'helix-npc-quest-generator-v3')
        self.assertEqual(candidate['budget']['agent_invocations'],1)
        self.assertEqual(candidate['budget']['provider_invocations'],4)
        self.assertEqual(candidate['budget']['max_output_tokens_per_call'],1200)

    def test_queue_restart_and_immutable_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);q=NpcQuestQueue(root/'queue');q.plan(request(19));first=q.run();q.close()
            q=NpcQuestQueue(root/'queue');q.plan(request(19));self.assertEqual(first,q.run())
            with self.assertRaises(ValueError):q.plan(request(20))
            q.close()
            a=export_candidate(first,root/'export');self.assertEqual(a,export_candidate(first,root/'export'))
            (root/'export/candidate.json').write_text('{}')
            with self.assertRaises(ValueError):export_candidate(first,root/'export')
            self.assertEqual((root/'export/candidate.json').read_text(),'{}')

    def test_fixture_cannot_cross_external_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            q=NpcQuestQueue(temp);req=request(3);q.plan(req)
            claim=q.claim('worker',now=100,lease_seconds=10)
            with self.assertRaisesRegex(ValueError,'zero provider'):
                q.begin_external(claim['job_id'],claim['token'],digest(approved_context(req)),now=101)
            q.close()

    def test_stale_claim_and_unknown_external_result_never_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            q=NpcQuestQueue(temp);req=request(3,mode='deepagents',model='example/model');q.plan(req)
            old=q.claim('worker',now=100,lease_seconds=10)
            current=q.claim('replacement',now=111,lease_seconds=10)
            with self.assertRaisesRegex(ValueError,'stale'):
                q.begin_external(old['job_id'],old['token'],digest(approved_context(req)),now=112)
            grant=q.begin_external(current['job_id'],current['token'],digest(approved_context(req)),now=112)
            self.assertTrue(grant['should_invoke'])
            self.assertFalse(q.begin_external(current['job_id'],current['token'],digest(approved_context(req)),now=113)['should_invoke'])
            self.assertIsNone(q.claim('later',now=123,lease_seconds=10))
            self.assertEqual(q.summary()['counts'],{'unknown':1})
            q.reconcile(current['job_id'],outcome='no_result',note='Explicit test reconciliation',now=124)
            retry=q.claim('explicit',now=125,lease_seconds=10)
            with self.assertRaisesRegex(ValueError,'budget exhausted'):
                q.begin_external(retry['job_id'],retry['token'],digest(approved_context(req)),now=126)
            q.close()

    def test_optional_adapter_is_called_with_public_bounded_context(self):
        fixture=fixture_narrative(2)
        proposal=JointProposal.model_validate({'title':fixture['title'],'npcs':[{key:npc[key]for key in ('role','name','motivation','greeting')}for npc in fixture['npcs']]}).model_dump()
        with tempfile.TemporaryDirectory() as temp:
            q=NpcQuestQueue(temp);req=request(2,mode='deepagents',model='example/model');q.plan(req)
            with patch('game_agents.deepagents_adapter.invoke_candidate',return_value=proposal) as provider:
                candidate=q.run(key='test-only-not-a-real-key')
                self.assertEqual(provider.call_count,1)
                context=provider.call_args.kwargs['context']
                self.assertEqual(context['request']['private_context'],'none')
                self.assertEqual(provider.call_args.kwargs['schema'],JointProposal)
                self.assertEqual(candidate['narrative'],fixture)
                self.assertEqual(q.run(key='test-only-not-a-real-key'),candidate)
                self.assertEqual(provider.call_count,1)
            q.close()

    def test_corrupt_retained_result_does_not_regenerate(self):
        with tempfile.TemporaryDirectory() as temp:
            q=NpcQuestQueue(temp);q.plan(request(1));q.run()
            file=next((Path(temp)/'results').glob('*.json'));file.write_text('{}')
            with self.assertRaises(ValueError):q.run()
            self.assertEqual(q.summary()['counts'],{'complete':1});q.close()

    def test_interrupted_publication_never_exposes_partial_candidate(self):
        candidate=assemble(request(5),fixture_narrative(5))
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'export'
            with patch('genetics.adventure_package.os.link',side_effect=OSError('interrupted before publish')):
                with self.assertRaises(OSError):export_candidate(candidate,target)
            self.assertFalse((target/'candidate.json').exists())
            self.assertFalse((target/'manifest.json').exists())
            manifest=export_candidate(candidate,target)
            self.assertEqual(manifest['candidate_sha256'],digest(candidate))

    def test_interrupted_manifest_can_resume_complete_candidate_without_overwrite(self):
        candidate=assemble(request(5),fixture_narrative(5))
        original_link=os.link
        calls=[]
        def interrupted(source,target):
            calls.append(str(target))
            if len(calls)==2:raise OSError('interrupted manifest publication')
            return original_link(source,target)
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'export'
            with patch('genetics.adventure_package.os.link',side_effect=interrupted):
                with self.assertRaises(OSError):export_candidate(candidate,target)
            before=(target/'candidate.json').read_bytes()
            self.assertEqual(json.loads(before),candidate)
            self.assertFalse((target/'manifest.json').exists())
            export_candidate(candidate,target)
            self.assertEqual((target/'candidate.json').read_bytes(),before)
            self.assertEqual(json.loads((target/'manifest.json').read_bytes())['candidate_sha256'],digest(candidate))
