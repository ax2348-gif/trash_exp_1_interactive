#!/bin/sh
# check.sh X Y THETA : plan/check a local goal; print warnings, nearest obstacle point in the local frame, BEV path
D=$(dirname "$0")
$D/mm nav POST plan/check "{\"frame\":\"local\",\"x\":$1,\"y\":$2,\"theta\":$3,\"comment\":\"check before re-issuing the approach leg\"}" > /tmp/.chk_$$ 2>&1
python3 - /tmp/.chk_$$ <<'P'
import json,sys,subprocess
d=json.load(open(sys.argv[1])); c=d['resp']['check']; print(c['warnings']); print('bev',d['saved'])
n=c.get('nearest_in_path_world') or []
if n: print(subprocess.run(['python3',sys.argv[0].rsplit('/',1)[0] if False else 'tools/w2l.py',str(n[0][0]),str(n[0][1])],capture_output=True,text=True).stdout)
P
rm -f /tmp/.chk_$$
