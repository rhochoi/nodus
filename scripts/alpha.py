"""Krippendorff alpha (nominal, 2 coders, binary) per code from blind_coding_sheet.xlsx.
Usage: python3 alpha.py blind_coding_sheet.xlsx  (임계값은 결과를 보기 전에 고정: 0.800 신뢰 / 0.667 잠정)"""
import sys,random
from openpyxl import load_workbook
def alpha(a,b):
    pairs=[(x,y) for x,y in zip(a,b) if x in (0,1) and y in (0,1)]
    n=len(pairs)*2
    if n<2: return None
    o={}
    for x,y in pairs:
        o[(x,y)]=o.get((x,y),0)+1; o[(y,x)]=o.get((y,x),0)+1
    nc={c:sum(v for (i,j),v in o.items() if i==c) for c in (0,1)}
    do=(o.get((0,1),0)+o.get((1,0),0))/n
    de=2*nc[0]*nc[1]/(n*(n-1))
    return None if de==0 else 1-do/de
def boot(a,b,k=2000):
    idx=list(range(len(a))); r=[]
    for _ in range(k):
        s=[random.choice(idx) for _ in idx]; v=alpha([a[i] for i in s],[b[i] for i in s])
        if v is not None: r.append(v)
    r.sort(); return (r[int(.025*len(r))],r[int(.975*len(r))]) if r else (None,None)
def num(v):
    try: return int(v)
    except: return None
wb=load_workbook(sys.argv[1],data_only=True)
codes=['C','P','H','A','Q']
for sh in ['T1_블라인드','T2_블라인드']:
    rows=list(wb[sh].iter_rows(min_row=2,values_only=True))
    print(sh,len(rows),'blocks')
    for j,c in enumerate(codes):
        a=[num(r[2+j]) for r in rows]; b=[num(r[7+j]) for r in rows]
        v=alpha(a,b); lo,hi=boot(a,b) if v is not None else (None,None)
        print(f'  {c}: alpha={v if v is None else round(v,3)} 95%CI=({lo if lo is None else round(lo,3)},{hi if hi is None else round(hi,3)})')
