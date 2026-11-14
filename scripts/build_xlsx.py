import json,re,os
BASE=os.path.dirname(os.path.abspath(__file__))+'/..'
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.worksheet.datavalidation import DataValidation
B=json.load(open(BASE+'/data/blocks.json'))
TOTAL={'T1':6416,'T2':5019}
def sec_T1(s):
    for a,b,n in [(0,321,'체크인'),(321,420,'톡방 의견'),(420,1471,'브랜딩'),(1471,1566,'전환'),(1566,2486,'러닝저니'),(2486,3596,'법인·재무'),(3596,3644,'휴식'),(3644,5693,'법인·재무'),(5693,6253,'마무리'),(6253,9999,'종료 후 대화')]:
        if a<=s<b: return n
def sec_T2(s):
    for a,b,n in [(0,703,'체크인·도입'),(703,1790,'개인 작성'),(1790,2657,'각자 발표'),(2657,2979,'수렴 시도'),(2979,4693,'슬로건 논의'),(4693,4923,'공유방식 확정'),(4923,9999,'후속·잡담')]:
        if a<=s<b: return n
SEC={'T1':sec_T1,'T2':sec_T2}
Q=re.compile(r'(괜찮은지|괜찮으신가|괜찮을까요|괜찮을까|괜찮냐고|동의하|동의를|정해졌|만장|손!|찬성|수렴 ?(됐|된)|맞나요|맞아\?|어떠신가요|어떠실까|의견이 어떠|의견을 주실)')
FPQ={('T1','59:01'),('T2','18:22')}
GARB=['제모','러밍전이','버빙','필드폰','가소금','만장일 수','넥스트잭체니','한 분당','단척방','분장','비집','지갑띠','두 간','슬로번','비정립팀','상인 방','구르노','무드와 파이브','늙크크']
MAN={ # manual codes
 'C':{('T2','1:21:32'):1,('T2','1:22:35'):1,('T2','1:17:08'):'추정'},
 'P':{('T1','5:21'):1,('T1','22:55'):1,('T1','23:26'):1,('T2','44:47'):1,('T2','53:15'):1,('T2','56:47'):1,('T2','1:13:56'):1,('T2','1:18:13'):1},
 'H':{('T1','1:34:52'):1,('T1','1:35:58'):1},
 'A':{(t,ts):1 for t,ts in [('T1','1:42:39'),('T1','1:43:10'),('T1','1:43:42'),('T1','1:44:13'),('T2','1:19:17'),('T2','1:19:49'),('T2','1:20:25'),('T2','47:32'),('T2','1:22:35'),('T2','1:23:07')]},
}
F='Arial'
def font(**k): return Font(name=F,size=10,**k)
HF=PatternFill('solid',fgColor='1F2937'); IN=PatternFill('solid',fgColor='FFF2CC')
def hdr(ws,row,vals):
    for i,v in enumerate(vals,1):
        c=ws.cell(row,i,v); c.font=Font(name=F,size=10,bold=True,color='FFFFFF'); c.fill=HF; c.alignment=Alignment(wrap_text=True,vertical='center')
def plain(wbk):
    for ws in wbk.worksheets:
        for r in ws.iter_rows():
            for c in r:
                if c.font.name!=F: c.font=font()
CODES=[('C','확정'),('P','제안'),('H','보류'),('A','후속 요청'),('Q','확인 질문'),('E','전사 의심')]
CODEBOOK=[
('C 확정','① 확인 질문(괜찮은지/동의/손!/정해졌죠 등)이 있고 ② 그 직후 동의·무반대 응답이 같은 구간에 기록된 결정. 응답이 ASR 오류 해석에 의존하면 "추정".'),
('P 제안','제안·의견은 있으나 확인 질문 또는 동의 응답이 기록되지 않은 것. 확인 질문에 질문으로 되받은 경우도 제안.'),
('H 보류','발화자가 "결정하지 않는다/다음에 넘긴다"를 명시한 것.'),
('A 후속 요청','회의 이후 행동을 요청·배정·약속하는 발화(해오시면, 알려주세요, 공유해 주세요 등). 한 블록 안에 여러 개면 결정·후속 시트에서 항목 단위로 센다.'),
('Q 확인 질문','합의 여부를 묻는 발화(괜찮은지, 동의, 수렴됐는지, 손! 등). 정규식 1차 후보 + 오탐 제외. 외부 코더가 최종 판정.'),
('E 전사 의심','자동 전사 오류로 보이는 어휘가 포함된 블록(정규식 후보). 인용 시 원문 그대로 쓰고 해석은 [ ]에 분리.'),
('분석 단위','타임스탬프 블록(원문 [시:분] 단위). 한 블록에 여러 코드 가능(다중 라벨). 화자 정보 없음.'),
('금지','코더는 의도·동기·성격을 추정하지 않는다. 보이는 텍스트만 코딩한다.'),
('주의','AI 1차 코딩이며 외부 코더 검증 전이다. 구간(섹션) 경계도 AI 판단이다.'),
]
DEC=[ # id,회의,유형,내용,근거ts,verbatim quote,확인질문,응답 기록
('T1-D1','T1','제안','톡방(재무 공유·아카이빙용) 신설 의견 수렴','5:21','다른 속방을 만들어 놓는 게 어떤가에 대한 의견이 나왔어서','있음(의견을 좀 좋아하고 싶어요[ASR])','"네."(브랜딩 넘어가도 되는지에 대한 응답) — 톡방 자체의 결론 기록 없음'),
('T1-D2','T1','제안','브랜딩은 가볍게 마무리, 슬로건 문장 5개 삭제','23:26','슬로건 문장 5개는 일단 지우는 걸로 생각을 하고','있음(22:55 "어떠신가요?")','질문으로 되받음 "누가 말한 것처럼 하자는 거죠?" — 동의 기록 없음'),
('T1-D3','T1','보류','법인·재무 방향은 이번에 결정하지 않고 다음으로 넘김','1:35:58','다음에 한 차례 더 넘겨서 얘기를 해보는 게 좋지 않을까라고 생각해요','—','—'),
('T2-D1','T2','제안','팀 정체성 키워드 수렴(다양성·시야 활용)','44:47','이렇게 수렴되는 게 조금 괜찮은지?','있음(4회 재질문: 44:47/45:50/46:23/49:05)','"네","너무 동의하는 거 같아요"(44:17) 2건 · 46:23 "두 간밖에 대답을 안 했잖아"[ASR]'),
('T2-D2','T2','제안','브랜딩 슬로건을 만드는 것','53:15','브랜딩 슬로번을 만드는 것은 다들 괜찮으신가요?','있음','"좋습니다." 1건 + 형식에 대한 반대 의견 발화(같은 블록)'),
('T2-D3','T2','확정(추정)','공모전은 하지 않음','1:17:08','저희는 안 만들었죠','있음(1:17:08 "만장일 수인가요?"[ASR])','"응" — 단 1:17:38 에서 "없다 없다.있다." 혼재'),
('T2-D4','T2','확정','금요일까지 각자 한 문장+맥락 공유, 다음 TM에서 정함','1:21:32','3, 2, 1. 없어요?','있음("손!")','"없어요."'),
('T2-D5','T2','확정','세션 후 넥스트 액션 확인','1:22:35','방금 넥스트잭체니 정해졌죠?네','있음','"네"'),
]
FU=[ # id,회의,항목,ts,quote,기한,담당 언급
('T1-A1','T1','무드 아카이브 정리','1:42:39','무드와 파이브는 정리해서 구르노한테 무드와 파이브 부탁드리고요','미언급','"구르노"[ASR 표기]'),
('T1-A2','T1','재무 프로세스 정리','1:42:39','재무 상인 방은 재무 관련 내용 프로세스 정리하는 거 해서 와주시면 좋을 것 같아요','가능하면 다음 주(1:43:10)','재무 담당 방[ASR]'),
('T1-A3','T1','길어질 경우 사전 공유','1:43:10','좀 길어질 것 같다고 하면 알려주세요','—','미언급'),
('T1-A4','T1','TS 일정(예비군) 고려','1:43:42','고려를 해주시고','—','전원'),
('T1-A5','T1','각자 의견 서치·공부','1:43:42','좀 서치를 해보면 좋을 것 같아요','미언급','각자'),
('T1-A6','T1','파트 팀 운영 고민','1:44:13','만약에 파트 팀 운영도 어떻게 하면 좋을지에 대한 고민도 같이 해서 와주시면 좋을 것 같아요','미언급','브루노(언급)'),
('T2-A1','T2','슬로건 한 문장+맥락 공유','1:19:49','그러면 일단은 이번 주 금요일까지','이번 주 금요일','각자'),
('T2-A2','T2','다음 TM 때 맥락 공유·결정','1:20:25','다음주에 TM 때 맥락 공유하고 실시간으로 좀 의견 나누면서','다음 주 월요일 TM','전원'),
('T2-A3','T2','퓨처 게임 과제','47:32','여러분 내일 퓨처 게임 과제 해오시면 돼요','내일','여러분'),
('T2-A4','T2','"사이트 비집 그거"(ASR 의심)','1:22:35','금요일까지 사이트 비집 그거 하셔야 됩니다','금요일','미언급'),
('T2-A5','T2','섭외','1:23:07','월요일까지는 섭외를 해야 된다네','월요일','미언급'),
]
def build_coding(ws,t):
    bl=B[t]; hdr(ws,1,['ts','sec','구간','길이(초)']+[f'{k} {n}' for k,n in CODES]+['원문(verbatim, 공백 정리)'])
    for i,x in enumerate(bl):
        r=i+2; key=(t,x['ts'])
        ws.cell(r,1,x['ts']); ws.cell(r,2,x['sec']); ws.cell(r,3,SEC[t](x['sec']))
        ws.cell(r,4,f'=B{r+1}-B{r}' if i<len(bl)-1 else f'={TOTAL[t]}-B{r}')
        for j,(k,_) in enumerate(CODES):
            v=None
            if k in MAN: v=MAN[k].get(key)
            elif k=='Q' and Q.search(x['text']) and key not in FPQ: v=1
            elif k=='E' and any(g in x['text'] for g in GARB): v=1
            if k=='Q' and key in {('T2','1:22:35'),('T2','1:21:32'),('T2','1:17:08'),('T2','1:17:38')}: v=1
            if v is not None: ws.cell(r,5+j,v)
        ws.cell(r,11,x['text'])
    ws.freeze_panes='E2'
    for col,w in zip('ABCDEFGHIJK',[9,7,12,9,9,9,9,11,11,11,120]): ws.column_dimensions[col].width=w
def build_blind(ws,t):
    bl=B[t]; hdr(ws,1,['ts','원문']+[f'코더1 {k}' for k,_ in CODES if k!='E']+[f'코더2 {k}' for k,_ in CODES if k!='E'])
    for i,x in enumerate(bl):
        r=i+2; ws.cell(r,1,x['ts']); ws.cell(r,2,x['text'])
        for c in range(3,13): ws.cell(r,c).fill=IN
    ws.freeze_panes='C2'; ws.column_dimensions['B'].width=110
    dv=DataValidation(type='list',formula1='"1,0"',allow_blank=True); ws.add_data_validation(dv); dv.add(f'C2:L{len(bl)+1}')
def cb(ws):
    hdr(ws,1,['항목','정의']); 
    for i,(a,b) in enumerate(CODEBOOK,2):
        ws.cell(i,1,a); ws.cell(i,2,b).alignment=Alignment(wrap_text=True,vertical='top')
    ws.column_dimensions['A'].width=16; ws.column_dimensions['B'].width=110
# ---- main workbook
wb=Workbook(); ws=wb.active; ws.title='README'
for i,l in enumerate(['회의 정리 v3 — AI 1차 코딩 (외부 코더 검증 전)','','시트: 요약 · 코드북 · T1_AI코딩 · T2_AI코딩 · 결정·후속 · 추적표 · 측정지표','외부 코더에게는 이 파일이 아니라 blind_coding_sheet.xlsx 를 준다(AI 코드가 보이면 독립 검증이 아니다).','원문은 자동 전사본이며 화자 라벨·원음이 없다. 인용은 오타·전사 오류 포함 원문 그대로.','노란 칸 = 사람이 채우는 칸(추적표 · 측정지표 입력값).'],1):
    ws.cell(i,1,l)
ws['A1'].font=Font(name=F,size=13,bold=True)
cb(wb.create_sheet('코드북'))
build_coding(wb.create_sheet('T1_AI코딩'),'T1'); build_coding(wb.create_sheet('T2_AI코딩'),'T2')
wd=wb.create_sheet('결정·후속'); hdr(wd,1,['ID','회의','유형','내용','근거 ts','원문 인용(verbatim)','확인 질문','응답 기록'])
for i,d in enumerate(DEC,2):
    for j,v in enumerate(d,1): wd.cell(i,j,v)
r0=len(DEC)+4; wd.cell(r0-1,1,'후속 요청 항목'); wd.cell(r0-1,1).font=font(bold=True)
hdr_row=r0; 
for j,v in enumerate(['ID','회의','항목','근거 ts','원문 인용(verbatim)','기한(발화)','담당(발화)'],1):
    c=wd.cell(r0,j,v); c.font=Font(name=F,size=10,bold=True,color='FFFFFF'); c.fill=HF
for i,d in enumerate(FU,r0+1):
    for j,v in enumerate(d,1): wd.cell(i,j,v)
FU_START=r0+1; FU_END=r0+len(FU)
for col,w in zip('ABCDEFGH',[9,7,13,40,10,60,28,60]): wd.column_dimensions[col].width=w
# 추적표
wt=wb.create_sheet('추적표'); hdr(wt,1,['후속 ID','회의','항목','기한(발화)','결과 확인 근거(채널 글·문서 이력 링크 등)','이행 여부(Y/N)','다음 회의 재등장(Y/N)','확인자(Ro·AI 제외)'])
for i,d in enumerate(FU,2):
    wt.cell(i,1,d[0]); wt.cell(i,2,d[1]); wt.cell(i,3,d[2]); wt.cell(i,4,d[5])
    for c in range(5,9): wt.cell(i,c).fill=IN
n=len(FU)+1
wt.cell(n+2,1,'이행률'); wt.cell(n+2,6,f'=IF(COUNTA(F2:F{n})=0,"미측정",COUNTIF(F2:F{n},"Y")/COUNTA(F2:F{n}))'); wt.cell(n+2,6).number_format='0%'
wt.cell(n+3,1,'재등장률'); wt.cell(n+3,7,f'=IF(COUNTA(G2:G{n})=0,"미측정",COUNTIF(G2:G{n},"Y")/COUNTA(G2:G{n}))'); wt.cell(n+3,7).number_format='0%'
for col,w in zip('ABCDEFGH',[9,7,30,20,50,14,18,18]): wt.column_dimensions[col].width=w
# 요약
wsu=wb.create_sheet('요약',1); hdr(wsu,1,['5초 요약','T1','T2','산식/근거'])
rows=[('확정 결정',"=COUNTIFS('결정·후속'!$B$2:$B$9,\"{t}\",'결정·후속'!$C$2:$C$9,\"확정\")",'결정·후속 시트, 유형=확정'),
('확정(추정)',"=COUNTIFS('결정·후속'!$B$2:$B$9,\"{t}\",'결정·후속'!$C$2:$C$9,\"확정(추정)\")",'Ro 정정으로 전사 의심 해소, 단 1:17:38 이후 공모전 의견이 갈려 외부 코더 판정 필요'),
('제안',"=COUNTIFS('결정·후속'!$B$2:$B$9,\"{t}\",'결정·후속'!$C$2:$C$9,\"제안\")",'확인·동의 미기록'),
('보류',"=COUNTIFS('결정·후속'!$B$2:$B$9,\"{t}\",'결정·후속'!$C$2:$C$9,\"보류\")",'명시적 이월'),
('후속 요청(항목)',f"=COUNTIF('결정·후속'!$B${FU_START}:$B${FU_END},\"{{t}}\")",'항목 단위'),
('확인 질문 블록 수',"=COUNT('{t}_AI코딩'!$I$2:$I$400)",'정규식 후보 — 외부 코더 판정 필요'),
('전체 블록 수',"=COUNTA('{t}_AI코딩'!$A$2:$A$400)",'타임스탬프 블록'),
('회의 길이(초)',"=SUM('{t}_AI코딩'!$D$2:$D$400)",'블록 길이 합')]
for i,(lab,f,src) in enumerate(rows,2):
    wsu.cell(i,1,lab); wsu.cell(i,2,f.format(t='T1')); wsu.cell(i,3,f.format(t='T2')); wsu.cell(i,4,src)
wsu.cell(11,1,'다음 회의 재등장'); wsu.cell(11,2,'미측정'); wsu.cell(11,3,'미측정'); wsu.cell(11,4,'다음 회의 전사본 필요')
hdr(wsu,13,['구간별 시간 배분','T1 초','T1 %','T2 초','T2 %'])
t1s=['체크인','톡방 의견','브랜딩','전환','러닝저니','법인·재무','휴식','마무리','종료 후 대화']; t2s=['체크인·도입','개인 작성','각자 발표','수렴 시도','슬로건 논의','공유방식 확정','후속·잡담']
for i in range(max(len(t1s),len(t2s))):
    r=14+i
    if i<len(t1s):
        wsu.cell(r,1,t1s[i]); wsu.cell(r,2,f"=SUMIFS('T1_AI코딩'!$D$2:$D$400,'T1_AI코딩'!$C$2:$C$400,A{r})"); wsu.cell(r,3,f'=B{r}/$B$9'); wsu.cell(r,3).number_format='0.0%'
for i,s in enumerate(t2s):
    r=25+i
    wsu.cell(r,1,s); wsu.cell(r,4,f"=SUMIFS('T2_AI코딩'!$D$2:$D$400,'T2_AI코딩'!$C$2:$C$400,A{r})"); wsu.cell(r,5,f'=D{r}/$C$9'); wsu.cell(r,5).number_format='0.0%'
wsu.cell(36,1,'T1 합계 검산(=회의 길이)'); wsu.cell(36,2,'=SUM(B14:B22)'); wsu.cell(37,1,'T2 합계 검산'); wsu.cell(37,4,'=SUM(D25:D31)')
wsu.column_dimensions['A'].width=28; wsu.column_dimensions['D'].width=40
for c in 'BCE': wsu.column_dimensions[c].width=12
# 측정지표
wm=wb.create_sheet('측정지표'); hdr(wm,1,['지표','정의','임계값(사전 고정)','근거 수준','측정자','결과'])
M=[('M1 인용 정확도','보고서 인용이 원문 블록에 그대로 존재하는 비율',1.0,'제안값(자동 검사)','스크립트(AI 작성 → 약한 증거)'),
('M2 전사 오류율(CER)','원음 vs 전사본 글자오류율',0.15,'제안값','외부 전사자(원음 필요)'),
('M3 코더 간 일치 α(신뢰)','Krippendorff α, 코드별',0.800,'문헌(Krippendorff)','외부 코더 2인'),
('M3 잠정 기준','잠정 사용 하한',0.667,'문헌(Krippendorff)','외부 코더 2인'),
('M4 재현성','같은 코드북·같은 원문 재코딩 일치율',0.9,'제안값','외부 코더 재코딩'),
('M5 팀 정정률','member check에서 팀이 "사실과 다름"으로 지적한 항목/전체',0.10,'제안값','팀원(Ro·AI 제외)'),
('M6 이행률','후속 요청 중 증거로 확인된 이행 비율','추적표 F열','측정 중','채널·문서 이력'),
('M7 전후 변화','개입 전·후 Ro 행동 로그 차이','사전 고정 필요','미정','외부 코더 블라인드')]
for i,m in enumerate(M,2):
    for j,v in enumerate(m,1): wm.cell(i,j,v)
    wm.cell(i,3).fill=IN
wm['C2'].number_format='0%';wm['C3'].number_format='0%';wm['C5'].number_format='0.000';wm['C6'].number_format='0.000';wm['C7'].number_format='0%';wm['C8'].number_format='0%'
for col,w in zip('ABCDEF',[24,50,16,22,30,20]): wm.column_dimensions[col].width=w
wm.cell(11,1,'주의: α 문헌 기준만 외부 근거. 나머지 임계값은 제안값이며 결과를 보기 전에 팀과 합의해 고정한다.')

CORR=[
('T2','1:17:08','만장일 수인가요?','만장일치','확인 질문 문구 확정. T2-D3는 전사 의심은 해소됐으나 1:17:38 "없다 없다.있다." 등 의견 혼재로 확정 여부는 외부 판정'),
('T2','1:22:35','넥스트잭체니','넥스트 액션','T2-D5 확정 유지(전사 의심 해소)'),
('T2','1:22:35','사이트 비집 그거','site visit(레인에서 하는 과제)','T2-A4 항목명 정정'),
('T1','1:42:39','구르노','브루노(사람)','T1-A1 담당 = 브루노'),
('T1','1:42:39','무드와 파이브','무드 아카이브(프로젝트 이름)','T1-A1 항목명 정정'),
('T1','1:42:39','재무 상인 방','재무 법인 방(카톡방 이름)','T1-A2 장소 정정'),
('T2','1:18:13','단척방','단톡방','공유 채널 = 단톡방'),
('T2','1:18:13','한 분당','한 문장','Ro 확인. 1:19:49 "한 문장으로 정리된 것을 공유"에도 독립 근거')]
wc=wb.create_sheet('Ro정정'); hdr(wc,1,['회의','ts','원문(전사 그대로)','Ro 정정','영향','출처'])
for i,c in enumerate(CORR,2):
    for j,v in enumerate(c,1): wc.cell(i,j,v)
    wc.cell(i,6,'Ro 2026-11-14 답변')
    ok=any(x['ts']==c[1] and c[2] in x['text'] for x in B[c[0]])
    assert ok,c
for col,w in zip('ABCDEF',[7,9,24,30,70,20]): wc.column_dimensions[col].width=w
plain(wb)
for s in wb.worksheets:
    for r in s.iter_rows(min_row=1,max_row=1):
        for c in r:
            if c.fill.fgColor.rgb in ('001F2937','FF1F2937'): c.font=Font(name=F,size=10,bold=True,color='FFFFFF')
wb['README']['A1'].font=Font(name=F,size=13,bold=True)
wb.save(BASE+'/xlsx/meeting_coding_v3.xlsx')
# blind
wb2=Workbook(); w=wb2.active; w.title='코드북'; cb(w)
w.cell(len(CODEBOOK)+3,1,'작성법'); w.cell(len(CODEBOOK)+3,2,'노란 칸에 해당하면 1, 아니면 0(또는 공백 금지: 모두 0/1). 다른 코더와 상의하지 않는다. 의도 추정 금지. E(전사 의심)는 코딩하지 않는다.')
build_blind(wb2.create_sheet('T1_블라인드'),'T1'); build_blind(wb2.create_sheet('T2_블라인드'),'T2'); plain(wb2)
wb2.save(BASE+'/xlsx/blind_coding_sheet.xlsx')
json.dump({'DEC':DEC,'FU':FU},open(BASE+'/data/facts.json','w'),ensure_ascii=False)
# strict quote check
bad=0
tot=0
for d in DEC: 
    t=d[1];ts=d[4];q=d[5];tot+=1
    ok=any(x['ts']==ts and q in x['text'] for x in B[t]); bad+=not ok
    if not ok: print('BAD DEC',d[0],q)
for d in FU:
    t=d[1];ts=d[3];q=d[4];tot+=1
    ok=any(x['ts']==ts and q in x['text'] for x in B[t]); bad+=not ok
    if not ok: print('BAD FU',d[0],q)
print('quotes',tot,'bad',bad)
