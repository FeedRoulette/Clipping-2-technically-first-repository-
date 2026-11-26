import json,sys,os
sys.path.insert(0,os.path.dirname(__file__))
import editor as M, edl2
s=json.load(open(sys.argv[1])); w=json.load(open(s["words"]))
edl,k=edl2.build3(w,s["segments"],30,s.get("drop_at",[]),env=M._energy(),log=lambda x:None,trust_aligner=s.get("trust_aligner",False))
print(json.dumps([[round(a,2),round(b,2)] for a,b in edl]))
for x in w:
    if s["segments"][0][0]-1<x["s"]<s["segments"][-1][1]+1: print(round(x["s"],2),round(x.get("s_ws",0),2),x["w"])
