"""nodus 검사. 실행: python3 tests/test_nodus.py  (표준 라이브러리만 사용, 저장소 데이터는 건드리지 않고 임시 복사본에서 돈다)

두 종류를 본다.
 1) 기능: 녹취록 파싱, 탐지, LLM 응답 검증이 의도대로 동작하는가
 2) 게이트의 이빨: 데이터를 일부러 망가뜨리면 audit 이 정말 FAIL 을 내는가 (통과만 하는 검사는 증거가 아니다)
"""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import nodus  # noqa: E402

FAILS = []


def check(name, cond, detail=''):
    print(('ok   ' if cond else 'FAIL ') + name + (f'  [{detail}]' if detail and not cond else ''))
    if not cond:
        FAILS.append(name)


def sandbox():
    d = tempfile.mkdtemp(prefix='nodus-test-')
    for f in ('nodus.py', 'lexicon.json', 'index.html'):
        shutil.copy(os.path.join(ROOT, f), d)
    shutil.copytree(os.path.join(ROOT, 'data'), os.path.join(d, 'data'))
    return d


def run(d, *args):
    r = subprocess.run([sys.executable, os.path.join(d, 'nodus.py'), *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def edit(path, fn):
    with open(path, encoding='utf-8') as f:
        obj = json.load(f)
    fn(obj)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


DEMO = """[0:00] 자 시작할게요. 오늘은 브랜딩 슬로번 얘기랑 무드 아카이블 정산 얘기입니다.
[0:40] 슬로건 후보가 다섯 개 모였어요.
슬로건은 짧을수록 좋다는 의견이 많았고요.
[2:40] 그럼 두 번째 슬로건으로 가는 것 다들 괜찮으신가요? 네. 없어요.
[4:10] 가수금 내역은 구르노가 정리해 주세요.
[5:00] 이건 다음에 한 차례 더 넘겨서 얘기하죠.
5:45 정산 자료는 금요일까지 단척방에 공유해 주세요.
[6:30] 3:30에 다음 회의 잡혀 있으니까 여기까지 할게요.
3:30에 봅시다.
[7:00] 수고하셨습니다.
"""

# ---- 1) 기능
b = nodus.parse_transcript(DEMO)
check('파싱: 블록 8개([..]·맨 시각 모두 인식)', [x['ts'] for x in b] == ['0:00', '0:40', '2:40', '4:10', '5:00', '5:45', '6:30', '7:00'], [x['ts'] for x in b])
check('파싱: 숫자로 시작하는 본문도 블록으로 남는다', b[6]['text'].startswith('3:30에 다음 회의'), b[6]['text'][:20])
check("파싱: 본문 속 '3:30에'는 타임스탬프가 아니다", '3:30에 봅시다.' in b[6]['text'])
check('파싱: 줄바꿈은 공백 하나로, 글자는 그대로', b[1]['text'] == '슬로건 후보가 다섯 개 모였어요. 슬로건은 짧을수록 좋다는 의견이 많았고요.')
check('파싱: 시간이 거꾸로 가면 본문 취급', len(nodus.parse_transcript('[1:00] 가\n[0:30] 나\n[2:00] 다')) == 2)

hits = nodus.scan_terms('오늘은 브랜딩 슬로번 얘기랑 무드 아카이블 정산', ['슬로건', '무드 아카이브'])
check('탐지: 용어집과 비슷한 오인식 2건', sorted(h[3] for h in hits) == ['무드 아카이브', '슬로건'], hits)
check('탐지: 바른 표기는 건드리지 않는다', nodus.scan_terms('슬로건을 정하고 무드 아카이브를 정리', ['슬로건', '무드 아카이브']) == [])
check('탐지: 문장 경계를 넘는 창은 무시', nodus.scan_terms('그랬고. 톡방에 올려요', ['단톡방']) == [])
check('자모 거리: 슬로번↔슬로건 = 1', nodus.lev(nodus.jamo('슬로번'), nodus.jamo('슬로건')) == 1)

d = sandbox()
try:
    src = os.path.join(d, 'demo.txt')
    with open(src, 'w', encoding='utf-8') as f:
        f.write(DEMO)
    code, out = run(d, 'run', 'DEMO', src)
    check('run: 새 녹취록 한 번에 처리하고 audit 통과', code == 0 and 'audit: PASS' in out, out[-300:])
    code, out = run(d, 'run', 'DEMO', src)
    check('run: 같은 ID 를 덮어쓰지 않는다', code != 0)
    M = os.path.join(d, 'data', 'meetings', 'DEMO')
    asr = json.load(open(os.path.join(M, 'asr.json'), encoding='utf-8'))
    got = {(x['raw'], x['fix'], x['status']) for x in asr}
    check('run: 사전에 있는 오인식은 자동 적용', {('구르노', '브루노', 'auto'), ('단척방', '단톡방', 'auto')} <= got, got)
    check('run: 처음 보는 오인식은 제안으로만', ('슬로번', '슬로건', 'suggest') in got and ('무드 아카이블', '무드 아카이브', 'suggest') in got, got)
    data = json.loads(open(os.path.join(d, 'data.js'), encoding='utf-8').read()[len('window.DATA='):-1])
    check('build: 뷰어 데이터에 새 회의가 들어간다', 'DEMO' in data['order'] and len(data['meetings']['DEMO']['blocks']) == 8)
    check('build: Notion 마크다운에 mermaid 간트·원형', all(k in open(os.path.join(M, 'notion.md'), encoding='utf-8').read() for k in ('```mermaid\ngantt', 'pie showData')))

    # LLM 응답 검증: 원문에 없는 raw / 인용은 버려지고, 낮은 신뢰도는 적용되지 않는다
    resp = {'corrections': [{'block': 0, 'raw': '슬로번', 'fix': '슬로건', 'conf': 0.97, 'reason': 't'},
                            {'block': 0, 'raw': '없는글자', 'fix': 'x', 'conf': 0.99, 'reason': 't'},
                            {'block': 3, 'raw': '가수금', 'fix': '가지급금', 'conf': 0.4, 'reason': 't'},
                            {'block': 99, 'raw': '가', 'fix': '나', 'conf': 1}],
            'sections': [{'name': '슬로건', 'start_block': 0}, {'name': '정산', 'start_block': 3}],
            'items': [{'kind': '결정', 'type': '확정', 'block': 2, 'summary': '두 번째 슬로건 채택', 'quote': '다들 괜찮으신가요?', 'q': '있음', 'resp': '네. 없어요.'},
                      {'kind': '결정', 'type': '확정', 'block': 2, 'summary': '지어낸 결정', 'quote': '만장일치로 통과됐습니다', 'q': '-', 'resp': '-'},
                      {'kind': '후속', 'type': '후속 요청', 'block': 5, 'summary': '정산 자료 공유', 'quote': '금요일까지 단척방에 공유해 주세요', 'due': '금요일', 'who': '미언급'},
                      {'kind': '후속', 'type': '확정', 'block': 5, 'summary': '유형 오류', 'quote': '정산 자료', 'due': '-', 'who': '-'}]}
    with open(os.path.join(M, 'llm_response.json'), 'w', encoding='utf-8') as f:
        json.dump(resp, f, ensure_ascii=False)
    code, out = run(d, 'merge', 'DEMO')
    rep = json.load(open(os.path.join(M, 'merge_report.json'), encoding='utf-8'))
    why = sorted(x['why'] for x in rep['dropped'])
    check('merge: 통과하고 audit PASS', code == 0 and 'audit: PASS' in out, out[-300:])
    check('merge: 잘못된 4건을 이유와 함께 탈락', why == ['raw 가 원문에 없음', '인용이 원문에 없음', '형식 오류', '형식 오류'], why)
    asr = json.load(open(os.path.join(M, 'asr.json'), encoding='utf-8'))
    st = {(x['raw'], x['fix']): x['status'] for x in asr}
    check('merge: conf 0.97 은 적용, 0.4 는 제안', st[('슬로번', '슬로건')] == 'auto' and st[('가수금', '가지급금')] == 'suggest', st)
    an = json.load(open(os.path.join(M, 'analysis.json'), encoding='utf-8'))
    check('merge: 검증된 항목 2건만 남는다', [i['id'] for i in an['items']] == ['DEMO-D1', 'DEMO-A1'], [i['id'] for i in an['items']])
    lex = json.load(open(os.path.join(d, 'lexicon.json'), encoding='utf-8'))
    check('learn: 적용된 바른 표기가 용어집에 들어간다', '슬로건' in lex['terms'])
    code, out = run(d, 'detect', 'DEMO')
    asr2 = json.load(open(os.path.join(M, 'asr.json'), encoding='utf-8'))
    check('detect 재실행: LLM·사람 판정이 사라지지 않는다', {(x['raw'], x['fix'], x['status']) for x in asr} == {(x['raw'], x['fix'], x['status']) for x in asr2})

    # ---- 2) 게이트의 이빨: 하나씩 망가뜨리고 FAIL 이 나는지
    def must_fail(name, gate, path, fn):
        bak = path + '.bak'
        shutil.copy(path, bak)
        edit(path, fn)
        code, out = run(d, 'audit')
        line = [l for l in out.split('\n') if gate in l and 'DEMO' in l or gate in l and '산출물' in l]
        check(f'게이트 {gate}: {name} → FAIL', code != 0 and any(l.startswith('FAIL') for l in line), out[-400:])
        shutil.move(bak, path)

    must_fail('원문 한 글자 수정', 'G1', os.path.join(M, 'blocks.json'), lambda o: o[1].__setitem__('text', o[1]['text'].replace('다섯', '여섯')))
    def both(o):
        o[1]['text'] = o[1]['text'].replace('다섯', '여섯')
        edit(os.path.join(M, 'meta.json'), lambda m: m.__setitem__('source_hash', nodus.text_hash(o)))
    shutil.copy(os.path.join(M, 'meta.json'), os.path.join(M, 'meta.keep'))
    must_fail('원문과 해시를 함께 수정', 'G1', os.path.join(M, 'blocks.json'), both)
    shutil.move(os.path.join(M, 'meta.keep'), os.path.join(M, 'meta.json'))
    must_fail('인용을 고쳐 씀', 'G2', os.path.join(M, 'analysis.json'), lambda o: o['items'][0].__setitem__('quote', '다들 동의하셨습니다'))
    must_fail('교정 좌표를 한 칸 밀기', 'G3', os.path.join(M, 'asr.json'), lambda o: o[0].__setitem__('s', o[0]['s'] + 1))
    must_fail('신뢰도 낮은 LLM 교정을 적용 상태로', 'G4', os.path.join(M, 'asr.json'),
              lambda o: [x.__setitem__('status', 'auto') for x in o if x['fix'] == '가지급금'])
    must_fail('구간 순서 뒤집기', 'G5', os.path.join(M, 'analysis.json'), lambda o: o['sections'].reverse())
    code, out = run(d, 'audit')
    check('되돌리면 다시 PASS', code == 0 and 'audit: PASS' in out, out[-300:])
finally:
    shutil.rmtree(d, ignore_errors=True)

# G10 위젯: 외부 호출이 끼어들면 audit 이 FAIL 을 내야 한다
d = sandbox()
src = open(os.path.join(d, 'nodus.py'), encoding='utf-8').read().replace('(function(){', '(function(){fetch("https://x.invalid");', 1)
open(os.path.join(d, 'nodus.py'), 'w', encoding='utf-8').write(src)
code, out = run(d, 'audit')
check('게이트 G10: 위젯에 fetch 삽입 → FAIL', code != 0 and 'FAIL' in out and 'G10' in out, out[-300:])
shutil.rmtree(d)

print(f'\n{"모두 통과" if not FAILS else "실패 " + str(len(FAILS)) + "건: " + ", ".join(FAILS)}')
sys.exit(1 if FAILS else 0)
