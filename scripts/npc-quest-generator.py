#!/usr/bin/env python3
"""Generate one reviewed-template NPC/quest draft, never install native content."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game_agents.npc_quest_generator import NpcQuestQueue,request,export_candidate


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',type=int,required=True)
    p.add_argument('--queue',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['fixture','deepagents'],default='fixture')
    p.add_argument('--model',default='none')
    args=p.parse_args()
    req=request(args.seed,mode=args.mode,model=args.model)
    key=None
    if args.mode=='deepagents':
        key=os.environ.get('OPENROUTER_API_KEY')
        if not key:p.error('deepagents mode requires explicit external OPENROUTER_API_KEY')
    queue=NpcQuestQueue(args.queue)
    try:
        queue.plan(req)
        result=queue.run(key=key)
        print(json.dumps(export_candidate(result,args.output),indent=2))
    except Exception:
        raise SystemExit('Generation refused or failed. Retain the queue; inspect its bounded status and reconcile unknown external outcomes. No native content was installed.') from None
    finally:queue.close()


if __name__=='__main__':main()
