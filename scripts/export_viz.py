"""data/blocks.json + facts.json + build_xlsx.py의 코딩 규칙 -> data/viz_data.json, data.js (뷰어 데이터)."""
import json,re,os,sys
sys.exit("export_viz.py 는 v3 용이다. 뷰어 데이터는 이제 `python3 nodus.py build` 가 만든다(이 스크립트를 돌리면 data.js 가 옛 형식으로 덮인다).")
BASE=os.path.dirname(os.path.abspath(__file__))+'/..'
B=json.load(open(BASE+'/data/blocks.json')); F=json.load(open(BASE+'/data/facts.json'))
src=open(BASE+'/scripts/build_xlsx.py').read()
lines=src.split('\n')
a=next(i for i,l in enumerate(lines) if l.startswith('def sec_T1'))
b=next(i for i,l in enumerate(lines) if l.startswith("F='Arial'"))
ns={}
exec("import re\n"+"\n".join(lines[a:b]),ns)
SEC=ns['SEC'];Q=ns['Q'];FPQ=ns['FPQ'];GARB=ns['GARB'];MAN=ns['MAN']
TOTAL={'T1':6416,'T2':5019}   # 회의 길이(초): 새 회의면 여기와 build_xlsx.py의 구간 경계를 바꾼다
m=re.search(r"CORR=\[(.*?\))\]\n",src,re.S)
CORR=eval("["+m.group(1)+"]")
out={}
for t in ('T1','T2'):
    bl=B[t]; blocks=[]
    for i,x in enumerate(bl):
        key=(t,x['ts']); codes=[]
        for k in 'CPHA':
            if MAN[k].get(key): codes.append('C?' if (k=='C' and MAN[k][key]=='추정') else k)
        if (Q.search(x['text']) and key not in FPQ) or key in {('T2','1:22:35'),('T2','1:21:32'),('T2','1:17:08'),('T2','1:17:38')}: codes.append('Q')
        if any(g in x['text'] for g in GARB): codes.append('E')
        end=bl[i+1]['sec'] if i<len(bl)-1 else TOTAL[t]
        blocks.append({'i':i,'ts':x['ts'],'sec':x['sec'],'dur':end-x['sec'],'sec_name':SEC[t](x['sec']),'codes':codes,'text':x['text']})
    secs=[]
    for bk in blocks:
        if secs and secs[-1]['name']==bk['sec_name']: secs[-1]['end']=bk['sec']+bk['dur']
        else: secs.append({'name':bk['sec_name'],'start':bk['sec'],'end':bk['sec']+bk['dur']})
    secs[0]['start']=0
    out[t]={'total':TOTAL[t],'sections':secs,'blocks':blocks}
def find(t,ts,q):
    for bk in out[t]['blocks']:
        if bk['ts']==ts and q in bk['text']: return bk['i']
    for bk in out[t]['blocks']:
        if q in bk['text']: return bk['i']
items=[]
for d in F['DEC']:
    items.append({'kind':'결정','id':d[0],'t':d[1],'type':d[2],'summary':d[3],'ts':d[4],'quote':d[5],'q':d[6],'resp':d[7],'block':find(d[1],d[4],d[5])})
for d in F['FU']:
    items.append({'kind':'후속','id':d[0],'t':d[1],'type':'후속 요청','summary':d[2],'ts':d[3],'quote':d[4],'due':d[5],'who':d[6],'block':find(d[1],d[3],d[4])})
bad=[i['id'] for i in items if i['block'] is None]
assert not bad,('원문에서 인용을 못 찾음',bad)
for it in items: it['sec']=out[it['t']]['blocks'][it['block']]['sec']
corr=[{'t':c[0],'ts':c[1],'raw':c[2],'fix':c[3],'note':c[4]} for c in CORR]
D={'meetings':out,'items':items,'corr':corr}
json.dump(D,open(BASE+'/data/viz_data.json','w'),ensure_ascii=False)
open(BASE+'/data.js','w').write('window.DATA='+json.dumps(D,ensure_ascii=False,separators=(',',':'))+';')
print('ok',{t:len(out[t]['blocks']) for t in out},len(items),'items')
