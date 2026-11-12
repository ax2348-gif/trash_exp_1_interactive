#!/bin/sh
# leg.sh '<goal json>' : post a nav goal, wait, print result + any reflex/robot events, check gripper, look
D=$(dirname "$0")
G=$($D/mm nav POST goal "$1" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['resp'].get('goal_id'), d['status'], d['resp'].get('warnings'))")
echo "goal $G"; ID=${G%% *}
$D/mm nav GET "goals/$ID/wait?timeout=90" | python3 -c "import json,sys;d=json.load(sys.stdin);print(json.dumps(d['resp']['result']))"
python3 - <<P
import sys,os,json; sys.path.insert(0,'/Users/aves/Documents/code/robot_utils/tools/agent_mm'); import mm
st,r=mm.call('nav','GET','log?since=0',log=False)
for e in r['turns'][-4:]:
    if e['actor']=='robot': print('EVENT', e['reply'].get('message'))
P
$D/mm tcp | python3 -c "import json,sys;d=json.load(sys.stdin);print('tcp',d['pos'],d['gripper'])"
$D/mm nav POST look '{"grid":true,"comment":"look after leg"}' | grep '"snapshot"'
