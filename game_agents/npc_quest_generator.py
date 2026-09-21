"""Joint NPC/quest candidate generation over one reviewed native template.

Candidates are data, never game facts or installation authority. Fixture is the
zero-provider default. The optional Deep Agents adapter has one approved-context
tool and cannot mutate the game, accepted content, saves or private canon.
"""
from __future__ import annotations

from hashlib import sha256
from functools import lru_cache
import json
from pathlib import Path
import re
import time
import textwrap
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from game_agents.expansion_contract import validate_expansion, require
from game_agents.public_lore import validate_public_value
from genetics.batches import BatchQueue
from genetics.adventure_package import publish
from genetics.primers import canonical, digest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT/'examples/expansions/helix-quiet-garden-v1.json'
GENERATOR_VERSION = 'helix-npc-quest-generator-v3'
LEGACY_GENERATOR_VERSION = 'helix-npc-quest-generator-v2'
MAX_OUTPUT_BYTES = 32768
CONTEXT_CONSTRAINTS = (
    'Draft only; no past player actions.', 'Keep facts conditional on their evidence action.',
    'Only caretaker, observer and guide roles; no rewards or births.',
    'NAUTIL uses accepted paddle feet; FERRO uses accepted long legs.',
    'No invented powers, genes, art, personal data or private canon.',
    'Costs of both screens must remain explicit.',
)

def _native_widths():
    # Public numerical fixture from the pinned upstream, not a game checkout.
    return _parse_native_widths((ROOT / 'examples/native-text-metrics.json').read_bytes())


@lru_cache(maxsize=4)
def _parse_native_widths(raw):
    # Cache by the bytes actually checked, so a long-running worker cannot bind
    # a new metrics digest while continuing to validate using an older table.
    data = json.loads(raw)
    require(data.get('schema_version') == 1 and data.get('revision') ==
            '36f5cf6271c382d4dc161ba040dd1dd3bc8b2a7f', 'unsupported text metrics')
    widths = data.get('widths')
    require(isinstance(widths, dict) and widths and
            all(isinstance(char, str) and len(char) == 1 and 32 <= ord(char) <= 126
                and type(width) is int and 0 <= width <= 16 for char, width in widths.items()),
            'invalid text metrics')
    return widths


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, hide_input_in_errors=True,
                              revalidate_instances='always')

    @model_validator(mode='before')
    @classmethod
    def public_content(cls, value):
        validate_public_value(value.model_dump() if isinstance(value, BaseModel) else value)
        return value

class Copy(Strict):
    en: str = Field(min_length=1, max_length=95)
    pt: str = Field(min_length=1, max_length=95)

    @model_validator(mode='after')
    def bounded_native_copy(self):
        for text in (self.en,self.pt):
            require(all(c == '\n' or 32 <= ord(c) < 127 for c in text), 'plain native Latin copy only')
            require(not any(c in text for c in '{}$\\'), 'text may not contain native controls or code')
            lines=text.split('\n')
            require(len(lines)<=3 and all(1<=len(line)<=32 for line in lines), 'native line/page budget')
            widths=_native_widths()
            require(all(all(c in widths for c in line) and sum(widths[c] for c in line)<=200 for line in lines), 'native font-width budget')
        return self

class Npc(Strict):
    role: Literal['guide','caretaker','observer']
    name: str = Field(pattern=r'^[A-Z][A-Z ]{1,9}$')
    motivation: Copy
    concern: Copy
    greeting: Copy
    after_bed_screen: Copy
    after_mouth_screen: Copy

class Statement(Strict):
    id: Literal['wet_leaves','channel_shape','wind_guess','water_guess','flow_test']
    kind: Literal['clue','hypothesis','confirmed_fact']
    evidence: Literal['inspect_bed','inspect_mouth','never_confirmed','observe']
    text: Copy

class DraftNarrative(Strict):
    title: Copy
    npcs: list[Npc] = Field(min_length=3,max_length=3)
    statements: list[Statement] = Field(min_length=5,max_length=5)
    bed_tradeoff: Copy
    mouth_tradeoff: Copy

    @model_validator(mode='after')
    def references(self):
        require({n.role for n in self.npcs} == {'guide','caretaker','observer'}, 'one NPC per reviewed role')
        require(len({n.name for n in self.npcs}) == 3, 'NPC names must differ')
        expected={'wet_leaves':('clue','inspect_bed'),'channel_shape':('clue','inspect_mouth'),
                  'wind_guess':('hypothesis','never_confirmed'),'water_guess':('hypothesis','never_confirmed'),
                  'flow_test':('confirmed_fact','observe')}
        require({s.id:(s.kind,s.evidence) for s in self.statements}==expected, 'clue/hypothesis/fact evidence mismatch')
        return self


class NpcVoice(Strict):
    role: Literal['guide','caretaker','observer']
    name: str = Field(pattern=r'^[A-Z][A-Z ]{1,9}$')
    motivation: Copy
    greeting: Copy

class JointProposal(Strict):
    """Small live result fits the adapter's per-response token budget."""
    title: Copy
    npcs: list[NpcVoice] = Field(min_length=3,max_length=3)

    @model_validator(mode='after')
    def unique_roles(self):
        require({npc.role for npc in self.npcs}=={'guide','caretaker','observer'},'one NPC per role')
        require(len({npc.name for npc in self.npcs})==3,'different NPC names required')
        return self


def _request_base(seed, mode, model, generator):
    require(type(seed) is int and 0<=seed<2**32, 'seed must be an unsigned 32-bit integer')
    require(mode in {'fixture','deepagents'}, 'unsupported generator mode')
    require((mode=='fixture' and model=='none') or (mode=='deepagents' and isinstance(model,str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}',model) and model!='none'), 'explicit live model required')
    template=json.loads(TEMPLATE.read_text());validate_expansion(template)
    return {'schema_version':1,'generator':generator,'seed':seed,'mode':mode,'model':model,
            'template_sha256':digest(template),'template':'helix-quiet-garden-v1',
            'runtime_action':'none','private_context':'none',
            'max_agent_invocations':0 if mode=='fixture' else 1,
            'max_provider_invocations':0 if mode=='fixture' else 4,
            'max_output_tokens_per_call':0 if mode=='fixture' else 1200}


def _producer_fingerprint(seed, template_sha256):
    # Custom validators are not represented by JSON Schema. Bind their actual
    # source as well; only this digest, never local policy text, leaves the host.
    dependencies = ('game_agents/npc_quest_generator.py', 'game_agents/public_lore.py',
                    'companion/openrouter_policy.py',
                    'game_agents/expansion_contract.py', 'game_agents/deepagents_adapter.py',
                    'examples/native-text-metrics.json')
    return digest({'system_prompt': SYSTEM_PROMPT,
                   'proposal_schema': JointProposal.model_json_schema(),
                   'narrative_schema': DraftNarrative.model_json_schema(),
                   'context_constraints': list(CONTEXT_CONSTRAINTS),
                   'fixture_example': fixture_narrative(seed),
                   'template_sha256': template_sha256, 'max_output_bytes': MAX_OUTPUT_BYTES,
                   'dependencies': {name: sha256((ROOT/name).read_bytes()).hexdigest()
                                    for name in dependencies}})


def request(seed:int, *, mode='fixture', model='none'):
    """New work binds the complete local producer; legacy v2 is read-only."""
    value = _request_base(seed, mode, model, GENERATOR_VERSION)
    value['producer_sha256'] = _producer_fingerprint(seed, value['template_sha256'])
    return value


def _validate_request(req, *, allow_legacy=False):
    require(isinstance(req, dict), 'request must be an object')
    legacy = req.get('generator') == LEGACY_GENERATOR_VERSION
    require(not legacy or allow_legacy, 'legacy v2 requests are read-only; create a new v3 queue')
    require({'seed', 'mode', 'model'} <= req.keys(), 'incomplete request')
    expected = (_request_base(req['seed'], req['mode'], req['model'], LEGACY_GENERATOR_VERSION)
                if legacy else request(req['seed'], mode=req['mode'], model=req['model']))
    require(req == expected, 'request input drift')
    return legacy


def copy(en,pt):
    def wrap(text):return '\n'.join('\n'.join(textwrap.wrap(line,width=32)) for line in text.split('\n'))
    return {'en':wrap(en),'pt':wrap(pt)}


def fixture_narrative(seed):
    """Deterministic authored combinations, without pretending they are inference."""
    names=[('LIA','TOM','IVO'),('NINA','RUI','ANA'),('INES','CAIO','EVA'),('BIA','LEO','ADA')][seed%4]
    caretakers=[copy('Keep the seedlings safe.','Cuidar das mudas.'),copy('Keep the bed easy to reach.','Manter facil chegar ao canteiro.')]
    observers=[copy('Watch the water carry leaves.','Ver a agua levar folhas.'),copy('Keep a clear view of the bed.','Manter a vista do canteiro.')]
    npcs=[
        dict(role='caretaker',name=names[0],motivation=caretakers[(seed//4)%2],concern=copy('Leaves pile up by the roots.','Folhas se juntam nas raizes.'),greeting=copy('Wet leaves reach this bed.\nCan we compare both edges?','Folhas molhadas chegam aqui.\nVamos comparar as duas beiras?'),after_bed_screen=copy('The access stays simple.\nThe screen hides the water.','O acesso continua simples.\nA tela cobre a vista da agua.'),after_mouth_screen=copy('The bed stays in view.\nWe walk around the screen.','O canteiro continua a vista.\nContornamos a tela.')),
        dict(role='observer',name=names[1],motivation=observers[(seed//8)%2],concern=copy('A screen can hide drifting leaves.','Uma tela pode esconder folhas.'),greeting=copy('I want to compare the water.\nFirst inspect both edges.','Quero comparar a agua.\nVeja primeiro as duas beiras.'),after_bed_screen=copy('Visitors reach the bed easily.\nMy clear water view is gone.','E facil chegar ao canteiro.\nPerdi a vista da agua.'),after_mouth_screen=copy('I can still watch the bed.\nThe mouth takes a detour.','Ainda posso ver o canteiro.\nA entrada pede um desvio.')),
        dict(role='guide',name=names[2],motivation=copy('Keep a safe way home.','Manter um caminho de volta.'),concern=copy('Visitors need a clear return.','Visitantes precisam voltar.'),greeting=copy('Explore when you wish.\nI can guide you back.','Explore quando quiser.\nPosso guiar sua volta.'),after_bed_screen=copy('The return path stays open.','O caminho de volta fica livre.'),after_mouth_screen=copy('Go around the support.\nThe return path stays open.','Contorne o suporte.\nO caminho de volta fica livre.')),
    ]
    statements=[
        dict(id='wet_leaves',kind='clue',evidence='inspect_bed',text=copy('Wet leaves line the bed.\nTheir cause is still unknown.','Folhas molhadas na borda.\nA causa ainda e desconhecida.')),
        dict(id='channel_shape',kind='clue',evidence='inspect_mouth',text=copy('The channel reaches the bed.\nIts shape alone proves no flow.','O canal chega ao canteiro.\nSo a forma nao prova corrente.')),
        dict(id='wind_guess',kind='hypothesis',evidence='never_confirmed',text=copy('Maybe wind brought the leaves.','Talvez o vento trouxe as folhas.')),
        dict(id='water_guess',kind='hypothesis',evidence='never_confirmed',text=copy('Maybe water brought the leaves.','Talvez a agua trouxe as folhas.')),
        dict(id='flow_test',kind='confirmed_fact',evidence='observe',text=copy('This test leaf follows water.\nIt does not explain older leaves.','A folha do teste segue a agua.\nNao explica as folhas antigas.')),
    ]
    titles=[copy('The leaf and the channel','A folha e o canal'),copy('Two views of one garden','Duas vistas do jardim')]
    return DraftNarrative.model_validate(dict(title=titles[(seed//16)%2],npcs=npcs,statements=statements,
        bed_tradeoff=copy('Easy access; hidden water view.','Acesso facil; agua fora de vista.'),
        mouth_tradeoff=copy('Clear view; walk around a screen.','Vista livre; contorne a tela.'))).model_dump()


def approved_context(req):
    _validate_request(req)
    return {'request':req,'template':json.loads(TEMPLATE.read_text()),'example':fixture_narrative(req['seed']),
            'constraints':list(CONTEXT_CONSTRAINTS)}

SYSTEM_PROMPT = ('Generate one joint NPC and quest narrative draft for the supplied reviewed garden template. '
                 'Use only approved context. Output the exact structured schema. NPC interests must differ. '
                 'Keep clues, unconfirmed hypotheses and test-confirmed facts separate. Never claim a player acted. '
                 'The two tradeoffs and effects are fixed by the template. No new abilities, rewards, births, '
                 'quests, native code or map mutations. EN/PT plain ASCII, at most 32 characters per line, '
                 'three lines per message. This is an uninstalled candidate requiring narrative and native review.')


def assemble(req,narrative):
    _validate_request(req)
    narrative=DraftNarrative.model_validate(narrative).model_dump()
    template=json.loads(TEMPLATE.read_text())
    candidate={'schema_version':1,'kind':'helix-npc-quest-candidate','status':'draft','runtime_action':'none',
               'candidate_id':digest(req)[:24],'request':req,'narrative':narrative,
               'npc_bindings':{'guide':'return_target','caretaker':'lia','observer':'tom'},
               'quest_nodes':template['nodes'],'map_contract':template,
               'budget':{'maps':1,'npcs':3,'quest_nodes':7,'resolutions':2,'provider_invocations':req['max_provider_invocations'],
                         'agent_invocations':req['max_agent_invocations'],'max_output_tokens_per_call':req['max_output_tokens_per_call'],
                         'max_output_bytes':MAX_OUTPUT_BYTES},
               'review_required':['narrative_semantics','native_encoding','explicit_content_version','compiled_rom_mgba']}
    validate_candidate(candidate)
    return candidate


def validate_candidate(candidate):
    require(set(candidate)=={'schema_version','kind','status','runtime_action','candidate_id','request','narrative','npc_bindings','quest_nodes','map_contract','budget','review_required'}, 'unknown candidate fields')
    require(candidate['schema_version']==1 and candidate['kind']=='helix-npc-quest-candidate' and candidate['status']=='draft' and candidate['runtime_action']=='none', 'candidate has no release authority')
    req=candidate['request']
    _validate_request(req, allow_legacy=True)
    require(candidate['candidate_id']==digest(req)[:24], 'candidate/request identity mismatch')
    DraftNarrative.model_validate(candidate['narrative'])
    template=json.loads(TEMPLATE.read_text())
    require(candidate['map_contract']==template and candidate['quest_nodes']==template['nodes'], 'unreviewed native map/quest topology or effects')
    validate_expansion(candidate['map_contract'])
    require(candidate['npc_bindings']=={'guide':'return_target','caretaker':'lia','observer':'tom'}, 'NPC connection mismatch')
    require(candidate['budget']=={'maps':1,'npcs':3,'quest_nodes':7,'resolutions':2,'provider_invocations':req['max_provider_invocations'],
                                  'agent_invocations':req['max_agent_invocations'],'max_output_tokens_per_call':req['max_output_tokens_per_call'],
                                  'max_output_bytes':MAX_OUTPUT_BYTES}, 'budget changed')
    require(candidate['review_required']==['narrative_semantics','native_encoding','explicit_content_version','compiled_rom_mgba'], 'review gates changed')
    require(len(canonical(candidate))<=MAX_OUTPUT_BYTES,'candidate byte budget exceeded')
    return digest(candidate)


def _publish(path,blob):
    # Same durable writer as accepted package staging: complete temp+fsync,
    # atomic no-replace link, fsync directory. Crash never exposes partial JSON.
    publish(path,blob)


class NpcQuestQueue(BatchQueue):
    """One joint job per directory; BatchQueue owns fenced leases and unknowns."""
    def __init__(self,path):super().__init__(path,max_workers=1)

    def plan(self,req):
        if _validate_request(req, allow_legacy=True):
            rows=self.db.execute('SELECT * FROM jobs').fetchall()
            require(len(rows)==1 and rows[0]['status']=='complete'
                    and rows[0]['id']==digest(req) and json.loads(rows[0]['payload'])==req,
                    'legacy v2 requests are read-only; create a new v3 queue')
            self._verify_result(rows[0], rows[0]['result_sha256'])
            return rows[0]['id']
        approved_context(req)
        identity=digest(req)
        with self.transaction():
            rows=self.db.execute('SELECT id,payload FROM jobs').fetchall()
            require(not rows or (len(rows)==1 and rows[0]['id']==identity and json.loads(rows[0]['payload'])==req),'new request needs a new queue')
            self.db.execute('INSERT OR IGNORE INTO jobs(id,adventure_id,owner_id,stage,payload,payload_sha256) VALUES(?,?,?,?,?,?)',(identity,identity,identity,'npc-quest',canonical(req).decode(),identity))
        return identity

    def claim(self,worker,*,stage=None,lease_seconds=900,now=None):
        # Refuse stale/legacy pending work before BatchQueue changes leases or
        # attempts, including callers which use the queue API directly.
        for row in self.db.execute("SELECT payload FROM jobs WHERE status!='complete'"):
            _validate_request(json.loads(row['payload']))
        return super().claim(worker,stage=stage,lease_seconds=lease_seconds,now=now)

    def begin_external(self,identity,token,request_sha256,*,now=None):
        now=self._time(now)
        with self.transaction():
            row=self._owned(identity,token,now)
            req=json.loads(row['payload'])
            require(req['mode']=='deepagents','fixture has zero provider budget')
            require(request_sha256==digest(approved_context(req)),'external approved-context digest mismatch')
            if row['status']=='running':return {'should_invoke':False,'status':'outcome_unknown'}
            spent=self.db.execute("SELECT COUNT(*) FROM events WHERE kind='external_started'").fetchone()[0]
            require(spent==0,'external invocation budget exhausted; no automatic retry')
            self.db.execute("UPDATE jobs SET status='running',request_sha256=? WHERE id=?",(request_sha256,identity))
            self._event(identity,'external_started',{'request_sha256':request_sha256},now)
            return {'should_invoke':True,'status':'outcome_unknown'}

    def _verify_result(self,row,result_sha256):
        req=json.loads(row['payload'])
        require(digest(req)==row['payload_sha256']==row['id'], 'frozen request checksum mismatch')
        legacy=_validate_request(req,allow_legacy=True)
        require(not legacy or row['status']=='complete', 'legacy v2 requests are read-only; create a new v3 queue')
        blob=(self.path/'results'/(result_sha256+'.json')).read_bytes()
        data=json.loads(blob)
        require(sha256(blob).hexdigest()==result_sha256 and validate_candidate(data)==result_sha256,'candidate checksum mismatch')
        require(data['request']==json.loads(row['payload']),'candidate belongs to another request')
        return data

    def run(self,*,key=None):
        rows=self.db.execute('SELECT * FROM jobs').fetchall()
        require(len(rows)==1,'plan one joint NPC/quest request first')
        row=rows[0]
        if row['status']=='complete':
            return self._verify_result(row,row['result_sha256'])
        initial_req=json.loads(row['payload'])
        _validate_request(initial_req)
        if initial_req['mode']=='fixture':require(key is None,'fixture does not accept a credential')
        else:require(isinstance(key,str) and bool(key),'explicit provider credential required')
        claim=self.claim('npc-quest-worker',lease_seconds=180)
        require(claim is not None,'job active or external outcome unknown; explicit reconciliation required')
        req=claim['payload']
        if req['mode']=='fixture':
            require(key is None,'fixture does not accept a credential')
            narrative=fixture_narrative(req['seed'])
        else:
            require(isinstance(key,str) and bool(key),'explicit provider credential required')
            from game_agents.deepagents_adapter import invoke_candidate
            context=approved_context(req)
            grant=self.begin_external(claim['job_id'],claim['token'],digest(context))
            require(grant['should_invoke'],'external outcome is unknown')
            proposal=JointProposal.model_validate(invoke_candidate(context=context,schema=JointProposal,system_prompt=SYSTEM_PROMPT,model=req['model'],key=key)).model_dump()
            narrative=fixture_narrative(req['seed'])
            narrative['title']=proposal['title']
            for voice in proposal['npcs']:
                npc=next(npc for npc in narrative['npcs'] if npc['role']==voice['role'])
                npc.update(voice)
            narrative=DraftNarrative.model_validate(narrative).model_dump()
        candidate=assemble(req,narrative)
        checksum=validate_candidate(candidate)
        _publish(self.path/'results'/(checksum+'.json'),canonical(candidate))
        self.complete(claim['job_id'],claim['token'],checksum)
        return candidate


def export_candidate(candidate,directory):
    checksum=validate_candidate(candidate)
    directory=Path(directory)
    manifest={'schema_version':1,'status':'draft','runtime_action':'none','candidate_sha256':checksum,'candidate_id':candidate['candidate_id'],'generator':candidate['request']['generator']}
    if (directory/'manifest.json').exists():
        require(json.loads((directory/'manifest.json').read_bytes())==manifest,'immutable manifest conflict')
    _publish(directory/'candidate.json',canonical(candidate))
    _publish(directory/'manifest.json',canonical(manifest))
    return manifest
