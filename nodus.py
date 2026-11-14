#!/usr/bin/env python3
"""nodus — 회의 녹취록 → ASR 오류 탐지·교정 → 결정/후속 추출 → 시각화(뷰어 + Notion).

표준 라이브러리만 쓴다. 원문은 절대 덮어쓰지 않고, 교정은 (블록, 시작, 끝) 좌표를 가진 별도 층으로 둔다.

  python3 nodus.py run <ID> <녹취록.txt>   # 한 번에: ingest → detect → extract → request → (merge) → build → audit
  python3 nodus.py merge <ID>              # llm_response.json 을 검증해서 반영
  python3 nodus.py build | audit | eval    # 뷰어·Notion 산출물 / 게이트 검사 / 탐지기 성능
"""
import ast, json, re, os, sys, math, hashlib, argparse
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
MDIR = os.path.join(BASE, 'data', 'meetings')
LEX = os.path.join(BASE, 'lexicon.json')
AUTO_CONF = 0.9          # 이 값 이상인 LLM 교정만 기본 적용(auto). 미만은 제안(suggest)으로만 표시
PRIO = {'confirmed': 4, 'auto': 3, 'suggest': 2, 'suspect': 1, 'rejected': 0}
APPLIED = ('confirmed', 'auto')
METHOD = {'human': 5, 'llm': 4, 'lexicon': 3, 'legacy-flag': 2, 'glossary': 1, 'variant': 0}
TYPES = {'결정': ['확정', '확정(추정)', '제안', '보류'], '후속': ['후속 요청']}


# ---------- 공통 ----------
def jload(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def jsave(p, obj, compact=False):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)


def mpath(mid, name=''):
    return os.path.join(MDIR, mid, name)


def meetings():
    if not os.path.isdir(MDIR):
        return []
    return sorted(d for d in os.listdir(MDIR) if os.path.exists(mpath(d, 'blocks.json')))


def to_sec(ts):
    p = [int(x) for x in ts.split(':')]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def fmt(s):
    h, m, r = s // 3600, s % 3600 // 60, s % 60
    return f'{h}:{m:02d}:{r:02d}' if h else f'{m}:{r:02d}'


def text_hash(blocks):
    h = hashlib.sha256()
    for b in blocks:
        h.update((b['ts'] + '\t' + b['text'] + '\n').encode('utf-8'))
    return h.hexdigest()


def lexicon():
    return jload(LEX, {'fixes': [], 'terms': [], 'rejected': []})


def all_terms(lex):
    """올바른 표기 목록: 직접 적은 용어 + 사람이 확정한 교정의 결과(그 자리에서만 맞는 교정은 제외)."""
    return set(lex.get('terms', [])) | {f['fix'] for f in lex['fixes'] if not f.get('only')}


# ---------- 1. ingest: 녹취록 텍스트 → 타임스탬프 블록 ----------
TS_BRACKET = re.compile(r'^\s*[\[\(](\d{1,2}:\d{2}(?::\d{2})?)[\]\)]\s*(.*)$')   # [0:31] 본문
TS_BARE = re.compile(r'^\s*(\d{1,2}:\d{2}(?::\d{2})?)(?:\s+(.*))?$')              # 0:31 본문 / 0:31 만 있는 줄
SPEAKER = re.compile(r'^((?:화자|참석자|Speaker)\s?\d+)\s*[:：]\s*(.*)$', re.I)


def parse_transcript(raw):
    """[0:31] 텍스트 / 0:31 줄바꿈 텍스트 / 1:02:03 모두 받는다. 시간이 거꾸로 가는 줄, '3:30에'처럼 글자가 붙은 시각은 본문으로 본다."""
    blocks, last = [], -1
    for line in raw.replace('\r', '').split('\n'):
        m = TS_BRACKET.match(line) or TS_BARE.match(line)
        if m and to_sec(m.group(1)) >= last:
            last = to_sec(m.group(1))
            blocks.append({'ts': m.group(1), 'sec': last, 'parts': [m.group(2) or '']})
        elif blocks:
            blocks[-1]['parts'].append(line)
        elif line.strip():
            blocks.append({'ts': '0:00', 'sec': 0, 'parts': [line]})
            last = 0
    out = []
    for b in blocks:
        text = re.sub(r'\s+', ' ', ' '.join(b['parts'])).strip()   # 공백만 정리, 글자는 그대로
        if not text:
            continue
        x = {'ts': b['ts'], 'sec': b['sec'], 'text': text}
        sp = SPEAKER.match(text)
        if sp:
            x['speaker'], x['text'] = sp.group(1), sp.group(2)
        out.append(x)
    return out


def cmd_ingest(mid, path, total=None, title=None):
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    blocks = parse_transcript(raw)
    if len(blocks) < 2:
        sys.exit('타임스탬프 블록을 2개 이상 찾지 못했다. 줄 머리에 [분:초] 또는 [시:분:초] 가 있어야 한다.')
    gaps = sorted(b['sec'] - a['sec'] for a, b in zip(blocks, blocks[1:]))
    estimated = not total
    total = int(total) if total else blocks[-1]['sec'] + max(1, gaps[len(gaps) // 2])
    if total <= blocks[-1]['sec']:
        sys.exit('--total 이 마지막 타임스탬프보다 작다.')
    jsave(mpath(mid, 'blocks.json'), blocks)
    with open(mpath(mid, 'raw.txt'), 'w', encoding='utf-8') as f:
        f.write(raw)                         # 받은 그대로 보관. audit 이 여기서 블록을 다시 만들어 비교한다
    jsave(mpath(mid, 'meta.json'), {'id': mid, 'title': title or mid + ' 회의', 'total': total,
                                    'total_estimated': estimated,
                                    'source_hash': text_hash(blocks), 'source_file': os.path.basename(path)})
    print(f'ingest {mid}: {len(blocks)}블록, 길이 {fmt(total)}')


# ---------- 2. detect: ASR 오류 후보 ----------
CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = [chr(0x314F + i) for i in range(21)]
JONG = [''] + list('ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ')


def jamo(s):
    out = []
    for ch in s:
        o = ord(ch) - 0xAC00
        if 0 <= o < 11172:
            out += [CHO[o // 588], JUNG[o % 588 // 28]]
            if o % 28:
                out.append(JONG[o % 28])
        else:
            out.append(ch.lower())
    return out


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


SUF = ['이라고', '에서는', '라고', '에서', '에게', '한테', '으로', '까지', '부터', '처럼', '이랑', '하고', '이나', '에는', '에도',
       '은', '는', '이', '가', '을', '를', '에', '의', '로', '도', '만', '와', '과', '랑', '나', '요']
ENDSYL = set('은는이가을를에의로도만요죠고서면지게네다까나라야와과랑든데어아해했할한하될된돼기거걸건움울신세씩런렇러리')


def stem(tok):
    for _ in range(2):
        for s in SUF:
            if tok.endswith(s) and len(tok) - len(s) >= 2:
                tok = tok[:-len(s)]
                break
        else:
            break
    return tok


def stems(text):
    return [stem(t) for t in re.findall(r'[가-힣]+', text)]


def scan_terms(text, terms):
    """용어집의 올바른 표기와 '거의 같지만 다른' 구간을 찾는다(자모 편집거리, 띄어쓰기 무시)."""
    idx = [i for i, c in enumerate(text) if c.isalnum()]
    comp = ''.join(text[i] for i in idx)
    hits = []
    for term in terms:
        t = ''.join(c for c in term if c.isalnum())
        n = len(t)
        if n < 3 or not re.search('[가-힣]', t):
            continue
        tj, tset = jamo(t), set(t)
        maxr = 0.25 if n <= 3 else 0.34      # 짧은 낱말은 우연히 비슷할 확률이 높다
        for L in ((n,) if n < 4 else (n, n - 1, n + 1)):
            for p in range(0, len(comp) - L + 1):
                w = comp[p:p + L]
                if w[0] not in tset and w[-1] not in tset:
                    continue
                if w in t or t in w or len(tset & set(w)) * 2 < n:
                    continue
                if re.search(r'[.?!,]', text[idx[p]:idx[p + L - 1] + 1]):
                    continue                 # 문장 경계를 넘는 창은 한 낱말이 아니다
                r = lev(jamo(w), tj) / len(tj)
                if 0 < r <= maxr:
                    hits.append((r, idx[p], idx[p + L - 1] + 1, term))
    hits.sort()
    kept = []
    for r, s, e, term in hits:
        if any(s < k[2] and k[1] < e for k in kept):
            continue
        if term.replace(' ', '') in text[max(0, s - 2):e + 2].replace(' ', ''):
            continue   # 바로 옆에 올바른 표기가 이미 있으면 창이 한 글자 밀린 것
        kept.append((r, s, e, term))
    return kept


def variant_candidates(corpus_blocks, blocks):
    """자주 나오는 낱말과 한 음절만 다른 드문 낱말(예: 슬로건 40회 / 슬로번 1회)."""
    freq = Counter(s for b in corpus_blocks for s in stems(b['text']) if len(s) >= 3)
    common = [s for s, c in freq.items() if c >= 4]
    tails = Counter(s[i:] for s in freq for i in range(1, len(s)) if len(s) - i >= 2)   # 꼬리를 공유하는 서로 다른 낱말 수
    by_len = {}
    for s in common:
        by_len.setdefault(len(s), []).append(s)
    out = []
    for bi, b in enumerate(blocks):
        for m in re.finditer(r'[가-힣]+', b['text']):
            s = stem(m.group())
            if len(s) < 3 or freq[s] > 1:
                continue
            best = None
            for f in by_len.get(len(s), []):
                diff = [i for i in range(len(s)) if s[i] != f[i]]
                if len(diff) != 1:
                    continue
                a, c = s[diff[0]], f[diff[0]]
                if a in ENDSYL or c in ENDSYL:
                    continue
                if diff[0] == 0 and tails[s[1:]] >= 6:
                    continue                 # 있는데/됐는데 처럼 어미만 같은 다른 낱말
                d = lev(jamo(a), jamo(c))
                if d <= 2 and (best is None or (d, -freq[f]) < best[0]):
                    best = ((d, -freq[f]), f)
            if best:
                d = best[0][0]
                out.append({'block': bi, 's': m.start(), 'e': m.start() + len(s), 'raw': s, 'fix': best[1],
                            'conf': round(0.6 - 0.1 * d + min(0.2, freq[best[1]] / 100), 2), 'method': 'variant',
                            'status': 'suggest', 'note': f'"{best[1]}" {freq[best[1]]}회 vs "{s}" {freq[s]}회'})
    return out


def resolve(entries):
    """겹치는 교정은 하나만 남긴다: 상태 → 판정 주체(사람 > LLM > 사전 > 기계 후보) → 신뢰도 → 긴 것."""
    entries = sorted(entries, key=lambda x: (-PRIO[x['status']], -METHOD.get(x['method'], 0), -x.get('conf', 0), -(x['e'] - x['s'])))
    kept = []
    for x in entries:
        if any(k['block'] == x['block'] and x['s'] < k['e'] and k['s'] < x['e'] for k in kept):
            continue
        kept.append(x)
    kept.sort(key=lambda x: (x['block'], x['s']))
    for i, x in enumerate(kept, 1):
        x['id'] = f'F{i:03d}'
    return kept


def detect(mid, use_lexicon=True, use_terms=True, use_variant=True, lex=None):
    blocks = jload(mpath(mid, 'blocks.json'))
    lex = lex or lexicon()
    rejected = {(r['raw'], r['fix']) for r in lex.get('rejected', [])}
    out = []
    if use_lexicon:
        for fx in lex['fixes']:
            for bi, b in enumerate(blocks):
                if fx.get('only') and (fx['only'] != [mid, b['ts']]):
                    continue
                for m in re.finditer(re.escape(fx['raw']), b['text']):
                    out.append({'block': bi, 's': m.start(), 'e': m.end(), 'raw': fx['raw'], 'fix': fx['fix'],
                                'conf': 1.0 if fx.get('source', '').startswith('사람') else 0.95,
                                'method': 'lexicon', 'status': fx.get('status', 'auto'),
                                'note': fx.get('note', ''), 'source': fx.get('source', '')})
    if use_terms:
        terms = sorted(all_terms(lex))
        for bi, b in enumerate(blocks):
            for r, s, e, term in scan_terms(b['text'], terms):
                out.append({'block': bi, 's': s, 'e': e, 'raw': b['text'][s:e], 'fix': term, 'conf': round(0.8 - r, 2),
                            'method': 'glossary', 'status': 'suggest', 'note': f'용어집 "{term}"과 자모 거리 {r:.2f}'})
    if use_variant:
        corpus = [b for m in meetings() for b in jload(mpath(m, 'blocks.json'))]
        out += variant_candidates(corpus, blocks)
    out = [x for x in out if (x['raw'], x['fix']) not in rejected and x['raw'] != x['fix']]
    return blocks, out


def cmd_detect(mid):
    blocks, found = detect(mid)
    old = jload(mpath(mid, 'asr.json'), [])
    keep = [x for x in old if x['method'] in ('human', 'llm', 'legacy-flag') and x['status'] != 'rejected']   # 사람·LLM 판정은 재실행해도 보존
    rej = [x for x in old if x['status'] == 'rejected']
    gone = {(x['block'], x['s'], x['e'], x['fix']) for x in rej}
    asr = resolve(keep + [x for x in found if (x['block'], x['s'], x['e'], x['fix']) not in gone]) + rej
    for i, x in enumerate(asr, 1):
        x['id'] = f'F{i:03d}'
    for x in asr:
        x['ts'] = blocks[x['block']]['ts']
    jsave(mpath(mid, 'asr.json'), asr)
    c = Counter(x['status'] for x in asr)
    print(f'detect {mid}: ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items())))


# ---------- 3. extract: 구간·확인 질문·결정/후속 후보 (규칙 기반 1차) ----------
Q = re.compile(r'(괜찮은지|괜찮으신가|괜찮을까요|괜찮을까|괜찮냐고|동의하|동의를|정해졌|만장|손!|찬성|수렴 ?(됐|된)|맞나요|맞아\?|어떠신가요|어떠실까|의견이 어떠|의견을 주실)')
ACT = re.compile(r'(해 ?오시면|해 ?주시면|해 ?주세요|알려 ?주세요|공유해 ?주|부탁드리|와 ?주시면|하셔야 ?(됩니다|돼요|돼)|해야 ?된다|까지[^.?!]{0,24}(공유|제출|정리|섭외)|고려를 해 ?주시|해보면 좋을 것 같아요)')
HOLD = re.compile(r'(다음에[^.?!]{0,20}넘겨|다음으로 넘|결정하지 않|다음에 다시 얘기|보류)')
YES = re.compile(r'(네[.,!? ]|넵|응[.,!? ]|좋습니다|없어요|동의합니다|좋아요)')
STOP = set('그래서 근데 이제 약간 그냥 저희 우리 그거 이거 저거 생각 얘기 같아요 같아 같은 그런 이런 저런 어떤 그렇게 이렇게 저렇게 뭔가 사실 지금 일단 그러면 그리고 하지만 그러니까 때문 정도 부분 경우 대해 대한 있는 없는 하는 되는 있어요 없어요 같습니다 있습니다 합니다 거예요 건데 거죠 아니 진짜 너무 조금 많이 다시 계속 그게 이게 저는 제가 뭐지 그럼 이거는 그거는 거기 여기 저기 어떻게 무엇 누가 언제 한번 하나 그때 다른 모든 각자 여러분 사람 사람들 것들 하면 해서 했는데 하는데 하고 해야 되게 되면 좋을 좋은 좋겠다'.split())


def sentence_at(text, s, e, cap=70):
    """매치 주변의 문장 조각을 원문 그대로 잘라 온다."""
    a = max(text.rfind(c, 0, s) for c in '.?!') + 1
    ends = [i for i in (text.find(c, e) for c in '.?!') if i >= 0]
    b = min(ends) + 1 if ends else len(text)
    a, b = max(a, s - cap), min(b, e + cap)
    return text[a:b].strip()


def segment(blocks, total, k=4, min_sec=240):
    """어휘 응집도(앞뒤 k블록의 낱말 겹침)가 뚝 떨어지는 곳에서 구간을 나눈다."""
    bags = [Counter(s for s in stems(b['text']) if len(s) >= 2 and s not in STOP) for b in blocks]
    n = len(blocks)
    df = Counter(s for bag in bags for s in bag)
    w = {s: math.log(1 + n / c) for s, c in df.items()}

    def cos(a, b):
        num = sum(a[s] * b[s] * w[s] ** 2 for s in a if s in b)
        da = math.sqrt(sum((v * w[s]) ** 2 for s, v in a.items()))
        db = math.sqrt(sum((v * w[s]) ** 2 for s, v in b.items()))
        return num / (da * db) if da and db else 0.0

    sims = []
    for g in range(1, n):
        left, right = Counter(), Counter()
        for bag in bags[max(0, g - k):g]:
            left.update(bag)
        for bag in bags[g:g + k]:
            right.update(bag)
        sims.append(cos(left, right))
    depth = []
    for i, v in enumerate(sims):
        l = max(sims[max(0, i - 2 * k):i + 1])
        r = max(sims[i:i + 2 * k + 1])
        depth.append((l - v) + (r - v))
    mean = sum(depth) / len(depth) if depth else 0
    sd = math.sqrt(sum((d - mean) ** 2 for d in depth) / len(depth)) if depth else 0
    cuts = [0]
    for i in sorted(range(len(depth)), key=lambda i: -depth[i]):
        g = i + 1
        if depth[i] < mean + 0.5 * sd:
            break
        if all(abs(blocks[g]['sec'] - blocks[c]['sec']) >= min_sec for c in cuts) and total - blocks[g]['sec'] >= min_sec:
            cuts.append(g)
    cuts.sort()
    secs = []
    for a, b in zip(cuts, cuts[1:] + [n]):
        bag = Counter()
        for x in bags[a:b]:
            bag.update(x)
        top = sorted((s for s in bag if bag[s] >= 3 and len(s) >= 2), key=lambda s: -bag[s] * w[s])[:2]
        secs.append({'name': '·'.join(top) or f'구간 {len(secs) + 1}', 'start_block': a})
    return secs


def sections_to_spans(secs, blocks, total):
    out = []
    for i, s in enumerate(secs):
        start = 0 if i == 0 else blocks[s['start_block']]['sec']
        end = blocks[secs[i + 1]['start_block']]['sec'] if i < len(secs) - 1 else total
        out.append({'name': s['name'], 'start': start, 'end': end, 'start_block': s['start_block']})
    return out


def rule_extract(blocks, total):
    codes, items = {}, []
    for i, b in enumerate(blocks):
        t, c = b['text'], []
        q, a, h = Q.search(t), ACT.search(t), HOLD.search(t)
        if q:
            c.append('Q')
            yes = YES.search(t, q.end()) or (i + 1 < len(blocks) and YES.match(blocks[i + 1]['text']))
            items.append({'kind': '결정', 'type': '확정(추정)' if yes else '제안', 'block': i,
                          'summary': '확인 질문: ' + sentence_at(t, q.start(), q.end(), 30),
                          'quote': sentence_at(t, q.start(), q.end()), 'q': '있음(규칙 후보)',
                          'resp': '긍정 응답 후보 있음' if yes else '응답 기록 못 찾음', 'origin': 'rule'})
        if h:
            c.append('H')
            items.append({'kind': '결정', 'type': '보류', 'block': i, 'summary': '보류: ' + sentence_at(t, h.start(), h.end(), 30),
                          'quote': sentence_at(t, h.start(), h.end()), 'q': '—', 'resp': '—', 'origin': 'rule'})
        if a:
            c.append('A')
            items.append({'kind': '후속', 'type': '후속 요청', 'block': i, 'summary': sentence_at(t, a.start(), a.end(), 30),
                          'quote': sentence_at(t, a.start(), a.end()), 'due': '미확인', 'who': '미확인', 'origin': 'rule'})
        if c:
            codes[str(i)] = c
    return {'sections': segment(blocks, total), 'codes': codes, 'items': items, 'origin': 'rule'}


def number_items(mid, items):
    n = {'결정': 0, '후속': 0}
    for it in sorted(items, key=lambda x: x['block']):
        n[it['kind']] += 1
        it['id'] = f"{mid}-{'D' if it['kind'] == '결정' else 'A'}{n[it['kind']]}"
    return sorted(items, key=lambda x: (x['kind'], x['block']))


def cmd_extract(mid, force=False):
    p = mpath(mid, 'analysis.json')
    old = jload(p)
    if old and old.get('origin') != 'rule' and not force:
        print(f'extract {mid}: 사람/LLM이 확정한 분석이 있어 건너뜀(--force 로 덮어쓰기)')
        return
    blocks, meta = jload(mpath(mid, 'blocks.json')), jload(mpath(mid, 'meta.json'))
    an = rule_extract(blocks, meta['total'])
    an['items'] = number_items(mid, an['items'])
    jsave(p, an)
    print(f"extract {mid}: 구간 {len(an['sections'])}, 결정 후보 {sum(i['kind'] == '결정' for i in an['items'])}, 후속 후보 {sum(i['kind'] == '후속' for i in an['items'])}")


# ---------- 4. LLM 단계: 요청 파일 만들기 / 응답 검증·병합 ----------
PROMPT = """너는 회의 전사본(자동 음성인식 결과)을 교정하고 구조화하는 편집자다. 아래 규칙을 지켜 JSON 하나만 출력해 `{resp}` 에 저장하라.

규칙
1. 원문은 고치지 않는다. 교정은 {{"block": 블록번호, "raw": "원문에 그대로 있는 글자", "fix": "바른 표기", "conf": 0~1, "reason": "근거"}} 로만 낸다.
   - raw 는 해당 블록 원문에 글자 그대로(띄어쓰기 포함) 있어야 한다. 없으면 기계가 버린다.
   - 음성인식이 잘못 들은 낱말(고유명사·전문용어·발음이 비슷한 낱말)만 고친다. 말버릇·문법·구어체는 고치지 않는다.
   - conf 0.9 이상 = 문맥상 다른 해석이 불가능. 확신이 없으면 낮게 주거나 fix 를 null 로 두어 '의심'만 표시한다.
   - 뜻을 추정해서 내용을 바꾸지 않는다. 화자의 의도·감정은 쓰지 않는다.
2. `candidates` 는 기계가 찾은 후보다. 각각 corrections 에 넣거나(동의/수정) `rejections` 에 id 를 넣어라(오탐).
3. sections: 주제가 바뀌는 지점. 첫 구간은 start_block 0. 이름은 12자 이내 명사구.
4. items: 결정과 후속 요청. quote 는 그 블록 원문에 그대로 있는 구절(80자 이내)이어야 한다.
   - 결정 type: "확정"(확인 질문 + 동의/무반대 응답이 기록됨) / "확정(추정)"(응답이 전사 오류 해석에 의존) / "제안"(동의 기록 없음) / "보류"(다음으로 넘긴다고 명시)
   - 후속 type: "후속 요청". due·who 는 발화에 있는 그대로, 없으면 "미언급".
   - summary 는 전사 오류를 교정한 표기로 40자 이내.

출력 형식
{{"corrections": [...], "rejections": ["F003"], "sections": [{{"name": "...", "start_block": 0}}],
  "items": [{{"kind": "결정", "type": "확정", "block": 0, "summary": "...", "quote": "...", "q": "확인 질문 유무·문구", "resp": "응답 기록"}},
            {{"kind": "후속", "type": "후속 요청", "block": 0, "summary": "...", "quote": "...", "due": "...", "who": "..."}}]}}
"""


def cmd_request(mid):
    blocks, asr, lex = jload(mpath(mid, 'blocks.json')), jload(mpath(mid, 'asr.json'), []), lexicon()
    cand = [{'id': x['id'], 'block': x['block'], 'raw': x['raw'], 'fix': x['fix'], 'method': x['method']} for x in asr if x['status'] in ('suggest', 'suspect')]
    terms = sorted(all_terms(lex))
    body = [PROMPT.format(resp=os.path.relpath(mpath(mid, 'llm_response.json'), BASE)),
            '## 팀 용어집(올바른 표기)\n' + ', '.join(terms),
            '## candidates\n' + json.dumps(cand, ensure_ascii=False),
            '## 전사본 (블록번호|시각|원문)\n' + '\n'.join(f"{i}|{b['ts']}|{b['text']}" for i, b in enumerate(blocks))]
    with open(mpath(mid, 'llm_request.md'), 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(body) + '\n')
    print(f"request {mid}: {os.path.relpath(mpath(mid, 'llm_request.md'), BASE)} (후보 {len(cand)}건, {len(blocks)}블록)")


def cmd_merge(mid):
    resp = jload(mpath(mid, 'llm_response.json'))
    if resp is None:
        print(f'merge {mid}: llm_response.json 없음 — 규칙 기반 결과만 사용')
        return
    blocks, meta = jload(mpath(mid, 'blocks.json')), jload(mpath(mid, 'meta.json'))
    asr = jload(mpath(mid, 'asr.json'), [])
    report = {'accepted': 0, 'dropped': []}
    by_id = {x['id']: x for x in asr}
    for rid in resp.get('rejections', []):
        if rid in by_id and by_id[rid]['status'] in ('suggest', 'suspect'):
            by_id[rid]['status'] = 'rejected'
            by_id[rid]['note'] = (by_id[rid].get('note', '') + ' · LLM 오탐 판정').strip(' ·')
    new = []
    for c in resp.get('corrections', []):
        bi, raw, fix = c.get('block'), c.get('raw'), c.get('fix')
        if not isinstance(bi, int) or not 0 <= bi < len(blocks) or not raw or raw == fix:
            report['dropped'].append({'why': '형식 오류', 'item': c})
            continue
        pos = [m.start() for m in re.finditer(re.escape(raw), blocks[bi]['text'])]
        if not pos:
            report['dropped'].append({'why': 'raw 가 원문에 없음', 'item': c})
            continue
        try:
            conf = min(1.0, max(0.0, float(c.get('conf', 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        st = 'suspect' if not fix else ('auto' if conf >= AUTO_CONF else 'suggest')
        for s in pos:
            new.append({'block': bi, 's': s, 'e': s + len(raw), 'raw': raw, 'fix': fix, 'conf': conf, 'method': 'llm',
                        'status': st, 'note': c.get('reason', '')})
        report['accepted'] += 1
    # LLM 이 같은 자리를 다시 판정한 기계 후보는 LLM 판정으로 대체(사람 확정은 유지)
    asr = [x for x in asr if x['method'] != 'llm']
    asr = [x for x in asr if x['status'] in APPLIED + ('rejected',) or not any(n['block'] == x['block'] and n['s'] < x['e'] and x['s'] < n['e'] for n in new)]
    rej = [x for x in asr if x['status'] == 'rejected']
    asr = resolve([x for x in asr if x['status'] != 'rejected'] + new) + rej
    for i, x in enumerate(asr, 1):
        x['id'], x['ts'] = f'F{i:03d}', blocks[x['block']]['ts']
    jsave(mpath(mid, 'asr.json'), asr)
    # 구간·항목
    an = jload(mpath(mid, 'analysis.json'))
    secs = resp.get('sections')
    if secs:
        sb = [s.get('start_block') for s in secs]
        if sb[0] == 0 and all(isinstance(x, int) for x in sb) and sb == sorted(set(sb)) and sb[-1] < len(blocks) and all(s.get('name') for s in secs):
            an['sections'] = [{'name': s['name'], 'start_block': s['start_block']} for s in secs]
        else:
            report['dropped'].append({'why': 'sections 가 0에서 시작하는 오름차순이 아님', 'item': sb})
    if 'items' in resp:
        items = []
        for it in resp['items']:
            bi = it.get('block')
            ok = it.get('kind') in TYPES and it.get('type') in TYPES.get(it.get('kind'), []) and isinstance(bi, int) and 0 <= bi < len(blocks) and it.get('summary')
            if not ok:
                report['dropped'].append({'why': '형식 오류', 'item': it})
            elif not it.get('quote') or it['quote'] not in blocks[bi]['text']:
                report['dropped'].append({'why': '인용이 원문에 없음', 'item': it})
            else:
                keys = ('kind', 'type', 'block', 'summary', 'quote') + (('q', 'resp') if it['kind'] == '결정' else ('due', 'who'))
                items.append({**{k: it.get(k, '—') for k in keys}, 'origin': 'llm'})
        an['items'] = number_items(mid, items)
        codes = {}
        for it in an['items']:
            code = {'확정': 'C', '확정(추정)': 'C?', '제안': 'P', '보류': 'H', '후속 요청': 'A'}[it['type']]
            codes.setdefault(str(it['block']), [])
            if code not in codes[str(it['block'])]:
                codes[str(it['block'])].append(code)
        for i, b in enumerate(blocks):
            if Q.search(b['text']):
                codes.setdefault(str(i), []).append('Q')
        an['codes'] = codes
        an['origin'] = 'llm'
    jsave(mpath(mid, 'analysis.json'), an)
    jsave(mpath(mid, 'merge_report.json'), report)
    print(f"merge {mid}: 교정 {report['accepted']}건 반영, {len(report['dropped'])}건 탈락(merge_report.json)")


# ---------- 5. build: 뷰어 데이터 + Notion 마크다운 ----------
def assemble(mid):
    blocks, meta = jload(mpath(mid, 'blocks.json')), jload(mpath(mid, 'meta.json'))
    an, asr = jload(mpath(mid, 'analysis.json')), jload(mpath(mid, 'asr.json'), [])
    total = meta['total']
    spans = sections_to_spans(an['sections'], blocks, total)
    out = []
    for i, b in enumerate(blocks):
        end = blocks[i + 1]['sec'] if i < len(blocks) - 1 else total
        name = [s['name'] for s in spans if s['start_block'] <= i][-1]
        fixes = [{'id': x['id'], 's': x['s'], 'e': x['e'], 'fix': x['fix'], 'st': x['status']} for x in asr if x['block'] == i and x['status'] != 'rejected']
        codes = list(an['codes'].get(str(i), []))
        if any(f['st'] != 'rejected' for f in fixes) and 'E' not in codes:
            codes.append('E')
        row = {'i': i, 'ts': b['ts'], 'sec': b['sec'], 'dur': end - b['sec'], 'sec_name': name, 'codes': codes, 'text': b['text'], 'fixes': fixes}
        if b.get('speaker'):
            row['speaker'] = b['speaker']
        out.append(row)
    merged = []
    for s in spans:
        if merged and merged[-1]['name'] == s['name'] and merged[-1]['end'] == s['start']:
            merged[-1]['end'] = s['end']
        else:
            merged.append({'name': s['name'], 'start': s['start'], 'end': s['end']})
    items = [{**it, 't': mid, 'ts': blocks[it['block']]['ts'], 'sec': blocks[it['block']]['sec']} for it in an['items']]
    corr = [{'id': x['id'], 't': mid, 'ts': x['ts'], 'block': x['block'], 'raw': x['raw'], 'fix': x['fix'], 'st': x['status'],
             'method': x['method'], 'conf': x.get('conf'), 'note': x.get('note', '')} for x in asr if x['status'] != 'rejected']
    return {'title': meta.get('title', mid), 'total': total, 'origin': an.get('origin', 'rule'), 'sections': merged, 'blocks': out}, items, corr


def fixed_text(text, fixes, upto=APPLIED):
    out, p = [], 0
    for f in sorted(fixes, key=lambda f: f['s']):
        if f['st'] in upto and f['fix']:
            out.append(text[p:f['s']] + f['fix'])
            p = f['e']
    return ''.join(out) + text[p:]


def md(s):
    return str(s).replace('|', '\\|').replace('\n', ' ')


def mm(s):
    return re.sub(r'[:;#"`,]', ' ', str(s)).strip()


def clock(s):
    return f'{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}'


def notion_md(mid, M, items, corr):
    """Notion 이 그대로 그리는 마크다운: mermaid 코드 블록(간트·원형·흐름) + 표."""
    its = [i for i in items if i['t'] == mid]
    dec, fu = [i for i in its if i['kind'] == '결정'], [i for i in its if i['kind'] == '후속']
    applied = [c for c in corr if c['t'] == mid and c['st'] in APPLIED]
    pending = [c for c in corr if c['t'] == mid and c['st'] in ('suggest', 'suspect')]
    seen = set()                             # 같은 블록에 같은 교정이 여러 번이면 표에는 한 줄만
    applied = [c for c in applied if (c['ts'], c['raw'], c['fix']) not in seen and not seen.add((c['ts'], c['raw'], c['fix']))]
    pending = [c for c in pending if (c['ts'], c['raw'], c['fix']) not in seen and not seen.add((c['ts'], c['raw'], c['fix']))]
    cnt = Counter(i['type'] for i in dec)
    L = [f"> **{fmt(M['total'])}** 회의 · 확정 **{cnt['확정']}** · 확정(추정) **{cnt['확정(추정)']}** · 제안 **{cnt['제안']}** · 보류 **{cnt['보류']}** · 후속 요청 **{len(fu)}** · 전사 교정 **{len(applied)}**종 적용 / **{len(pending)}**종 확인 대기",
         '', '분류는 AI 1차이고, 인용은 전사 원문 그대로다(교정은 아래 표에 따로 둔다).', '',
         '## 타임라인', '```mermaid', 'gantt', '    dateFormat HH:mm:ss', '    axisFormat %H:%M', '    section 구간']
    for k, s in enumerate(M['sections']):
        L.append(f"    {mm(s['name'])} :s{k}, {clock(s['start'])}, {s['end'] - s['start']}s")
    if dec:
        L.append('    section 결정')
        L += [f"    {mm(i['id'] + ' ' + i['type'])} :milestone, {'crit, ' if i['type'] == '확정' else ''}d{k}, {clock(i['sec'])}, 0s" for k, i in enumerate(dec)]
    if fu:
        L.append('    section 후속 요청')
        L += [f"    {mm(i['id'])} :milestone, a{k}, {clock(i['sec'])}, 0s" for k, i in enumerate(fu)]
    L += ['```', '', '## 시간 배분', '```mermaid', 'pie showData', '    title 구간별 시간(분)']
    agg = {}
    for s in M['sections']:
        agg[s['name']] = agg.get(s['name'], 0) + s['end'] - s['start']
    L += [f'    "{mm(n)}" : {v / 60:.1f}' for n, v in agg.items()]
    L += ['```', '', '## 결정', '| ID | 시각 | 유형 | 내용 | 원문 인용 | 확인 질문 | 응답 기록 |', '|---|---|---|---|---|---|---|']
    L += [f"| {i['id']} | {i['ts']} | {i['type']} | {md(i['summary'])} | “{md(i['quote'])}” | {md(i.get('q', '—'))} | {md(i.get('resp', '—'))} |" for i in dec]
    L += ['', '## 후속 요청', '| ID | 시각 | 내용 | 원문 인용 | 기한(발화) | 담당(발화) | 이행 |', '|---|---|---|---|---|---|---|']
    L += [f"| {i['id']} | {i['ts']} | {md(i['summary'])} | “{md(i['quote'])}” | {md(i.get('due', '—'))} | {md(i.get('who', '—'))} | ☐ |" for i in fu]
    L += ['', '## 전사 교정', '적용된 교정(사람 확인 또는 신뢰도 0.9 이상).', '', '| 시각 | 전사 원문 | 교정 | 근거 | 방법 |', '|---|---|---|---|---|']
    L += [f"| {c['ts']} | {md(c['raw'])} | **{md(c['fix'])}** | {md(c['note'])} | {c['method']} · {c['st']} |" for c in applied]
    if pending:
        L += ['', '확인 대기(적용 안 됨 — 아는 사람이 맞는지 봐 주세요).', '', '| 시각 | 전사 원문 | 제안 | 근거 |', '|---|---|---|---|']
        L += [f"| {c['ts']} | {md(c['raw'])} | {md(c['fix'] or '?')} | {md(c['note'])} |" for c in pending]
    return '\n'.join(L) + '\n'


WIDGET_TPL = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fff;--fg:#1b1b1f;--mu:#55555f;--ln:#e4e4e9;--cd:#f7f7f9;--ac:#1a56c4;--ok:#14612f;--wr:#b36b00}
@media(prefers-color-scheme:dark){:root{--bg:#191919;--fg:#ececf0;--mu:#a0a0aa;--ln:#33333a;--cd:#232327;--ac:#7aa7ff;--ok:#6fd08c;--wr:#f0b24a}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,-apple-system,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif}
h1{font-size:16px;margin:0 0 4px}.sub{color:var(--mu);font-size:12px;margin-bottom:12px}
.kp{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}.kp div{flex:1 1 90px;background:var(--cd);border-radius:10px;padding:8px 12px}.kp b{display:block;font-size:20px}.kp span{font-size:11px;color:var(--mu)}
.bar{display:flex;height:28px;border-radius:6px;overflow:hidden;border:1px solid var(--ln)}.bar i{display:block;height:100%;min-width:2px;border-right:1px solid var(--bg);opacity:.85}
.lane{position:relative;height:44px;margin-top:4px}.lane button{position:absolute;top:3px;width:18px;height:18px;margin-left:-9px;border-radius:50%;border:2px solid var(--bg);padding:0;cursor:pointer;box-shadow:0 0 0 1px var(--mu)}
.lane button[aria-pressed=true]{outline:3px solid var(--ac)}
.lg{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--mu);margin:8px 0 12px}.lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.tabs{display:flex;gap:6px;margin:6px 0 10px}.tabs button{font:inherit;cursor:pointer;min-height:36px;padding:4px 14px;border-radius:999px;border:1px solid var(--ln);background:var(--bg);color:var(--fg)}.tabs button[aria-pressed=true]{background:var(--fg);color:var(--bg)}
.box{background:var(--cd);border-radius:10px;padding:12px 14px;min-height:96px}.q{font-size:16px;font-weight:700;line-height:1.5;margin:4px 0;overflow-wrap:anywhere}
.tag{display:inline-block;font-size:11px;font-weight:600;padding:1px 8px;border-radius:999px;background:var(--ln);margin-right:6px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--ln);vertical-align:top}th{color:var(--mu);font-weight:600}
.fx{font-weight:700;color:var(--ok)}.sg{color:var(--wr)}
</style></head><body>
<h1 id="t"></h1><div class="sub" id="s"></div><div class="kp" id="k"></div>
<div class="bar" id="bar" role="img" aria-label="구간 타임라인"></div>
<div class="lane" id="ld" aria-label="결정"></div><div class="lane" id="lf" aria-label="후속 요청"></div>
<div class="lg" id="lg"></div>
<div class="tabs" id="tb"></div><div class="box" id="bx"></div><div id="tbl"></div>
<script id="nodus-data" type="application/json">__DATA__</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('nodus-data').textContent);
var PAL=['#7aa7ff','#6fd08c','#f0b24a','#c39bf0','#f08a80','#6cc7d1','#c9c96b','#9a9aa6'];
function $(i){return document.getElementById(i)}
function E(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function fm(s){var h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=s%60,p=function(n){return String(n).padStart(2,'0')};return h?h+':'+p(m)+':'+p(r):m+':'+p(r)}
$('t').textContent=D.title;$('s').textContent=D.id+' · 총 '+fm(D.total)+' · 원문 인용은 전사 원문 그대로, 교정은 별도 표';
D.kpi.forEach(function(k){var d=E('div');d.appendChild(E('b','',k[1]));d.appendChild(E('span','',k[0]));$('k').appendChild(d)});
var names=[];D.sections.forEach(function(s){if(names.indexOf(s.name)<0)names.push(s.name)});
D.sections.forEach(function(s){var i=E('i');i.style.width=((s.end-s.start)/D.total*100)+'%';i.style.background=PAL[names.indexOf(s.name)%PAL.length];i.title=s.name+' '+fm(s.start)+'–'+fm(s.end);$('bar').appendChild(i)});
names.forEach(function(n){var d=E('span');var i=E('i');i.style.background=PAL[names.indexOf(n)%PAL.length];d.appendChild(i);d.appendChild(document.createTextNode(n));$('lg').appendChild(d)});
var sel=null,tab='결정',last={ld:-9,lf:-9},stk={ld:0,lf:0};
function mk(it,lane,color){var b=E('button');var x=it.sec/D.total*100;stk[lane]=(x-last[lane]<2)?stk[lane]+1:0;last[lane]=x;b.style.left=x+'%';b.style.top=(3+(stk[lane]%3)*13)+'px';b.style.background=color;b.title=it.id+' '+it.ts;b.setAttribute('aria-label',it.id+' '+it.ts);b.setAttribute('aria-pressed','false');b.onclick=function(){sel=it;tab=it.kind==='결정'?'결정':'후속';draw()};it._b=b;$(lane).appendChild(b)}
D.items.forEach(function(it){mk(it,it.kind==='결정'?'ld':'lf',it.kind==='결정'?'#1a56c4':'#b36b00')});
function draw(){
D.items.forEach(function(it){it._b.setAttribute('aria-pressed',it===sel?'true':'false')});
var tb=$('tb');tb.textContent='';['결정','후속','교정'].forEach(function(n){var b=E('button','',n);b.setAttribute('aria-pressed',n===tab?'true':'false');b.onclick=function(){tab=n;draw()};tb.appendChild(b)});
var bx=$('bx');bx.textContent='';
if(sel){bx.appendChild(E('span','tag',sel.id+' · '+(sel.type||sel.kind)));bx.appendChild(E('span','',sel.ts));bx.appendChild(E('div','q','“'+sel.quote+'”'));bx.appendChild(E('div','',sel.summary));if(sel.q)bx.appendChild(E('div','sub','확인 질문: '+sel.q))}
else bx.appendChild(E('div','sub','타임라인의 점을 누르면 원문 인용이 나옵니다.'));
var t=$('tbl');t.textContent='';var tbl=E('table');var rows,head;
if(tab==='교정'){head=['시각','전사 원문','교정','상태'];rows=D.corr.map(function(c){return [c.ts,c.raw,c.fix||'?',c.applied?'적용':'확인 대기']})}
else{head=['ID','시각','내용','유형'];rows=D.items.filter(function(i){return i.kind===tab}).map(function(i){return [i.id,i.ts,i.summary,i.type||'']})}
var tr=E('tr');head.forEach(function(h){tr.appendChild(E('th','',h))});tbl.appendChild(tr);
rows.forEach(function(r){var tr=E('tr');r.forEach(function(c,j){var td=E('td','',c);if(tab==='교정'&&j===2)td.className=r[3]==='적용'?'fx':'sg';tr.appendChild(td)});tbl.appendChild(tr)});
t.appendChild(tbl)}
draw();
})();
</script></body></html>
"""


def widget_html(mid, M, items, corr):
    """Notion HTML 블록용 한 파일 위젯. 외부 주소·CDN·fetch 없이 데이터를 안에 넣는다(샌드박스에서 막히므로).
    인용은 전사 원문 그대로, 교정은 별도 표로만 보여준다."""
    its = [i for i in items if i['t'] == mid]
    cs = [c for c in corr if c['t'] == mid]
    cnt = Counter(i['type'] for i in its if i['kind'] == '결정')
    secs = []
    for s in M['sections']:
        if secs and secs[-1]['name'] == s['name'] and secs[-1]['end'] == s['start']:
            secs[-1]['end'] = s['end']
        else:
            secs.append({'name': s['name'], 'start': s['start'], 'end': s['end']})
    data = {
        'id': mid, 'title': M['title'], 'total': M['total'], 'sections': secs,
        'kpi': [['회의 시간', fmt(M['total'])], ['결정 항목', str(sum(cnt.values()))], ['후속 요청', str(sum(i['kind'] == '후속' for i in its))],
                ['교정 적용', str(sum(c['st'] in APPLIED for c in cs))], ['확인 대기', str(sum(c['st'] in ('suggest', 'suspect') for c in cs))]],
        'items': [{k: i.get(k, '') for k in ('id', 'kind', 'type', 'ts', 'sec', 'summary', 'quote', 'q')} for i in its],
        'corr': [{'ts': c['ts'], 'raw': c['raw'], 'fix': c['fix'], 'applied': c['st'] in APPLIED} for c in cs],
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/').replace('<!--', '<\\!--')
    return WIDGET_TPL.replace('__TITLE__', md(M['title']).replace('<', '&lt;')).replace('__DATA__', blob)


def cmd_build(quiet=False):
    D = {'order': meetings(), 'meetings': {}, 'items': [], 'corr': []}
    for mid in D['order']:
        M, items, corr = assemble(mid)
        D['meetings'][mid] = M
        D['items'] += items
        D['corr'] += corr
        with open(mpath(mid, 'notion.md'), 'w', encoding='utf-8') as f:
            f.write(notion_md(mid, M, items, corr))
        with open(mpath(mid, 'notion_widget.html'), 'w', encoding='utf-8') as f:
            f.write(widget_html(mid, M, items, corr))
    D['audit'] = jload(os.path.join(BASE, 'data', 'audit.json'), {})
    jsave(os.path.join(BASE, 'data', 'viz_data.json'), D, compact=True)
    with open(os.path.join(BASE, 'data.js'), 'w', encoding='utf-8') as f:
        f.write('window.DATA=' + json.dumps(D, ensure_ascii=False, separators=(',', ':')) + ';')
    if not quiet:
        print('build: ' + ', '.join(f"{m} {len(D['meetings'][m]['blocks'])}블록" for m in D['order']) + f" · 항목 {len(D['items'])} · 교정 {len(D['corr'])}")
    return D


# ---------- 6. audit: 사람·AI 없이 다시 돌려 확인할 수 있는 게이트 ----------
def audit_meeting(mid):
    blocks, meta = jload(mpath(mid, 'blocks.json')), jload(mpath(mid, 'meta.json'))
    an, asr = jload(mpath(mid, 'analysis.json')), jload(mpath(mid, 'asr.json'), [])
    G = {}
    same, how = text_hash(blocks) == meta['source_hash'], 'blocks.json 해시 = ingest 때 해시'
    if os.path.exists(mpath(mid, 'raw.txt')):
        with open(mpath(mid, 'raw.txt'), encoding='utf-8') as f:
            again = parse_transcript(f.read())
        same &= [(b['ts'], b['text']) for b in again] == [(b['ts'], b['text']) for b in blocks]
        how = '받은 녹취록(raw.txt)을 다시 파싱한 결과 = blocks.json, 해시 일치'
    G['G1 원문 불변'] = [same, how]
    bad = [i['id'] for i in an['items'] if i['quote'] not in blocks[i['block']]['text']]
    G['G2 인용 정확도'] = [not bad, f"{len(an['items']) - len(bad)}/{len(an['items'])} 인용이 원문 블록에 그대로 존재" + (f' · 실패 {bad}' if bad else '')]
    live = [x for x in asr if x['status'] != 'rejected']
    anchor = [x['id'] for x in live if blocks[x['block']]['text'][x['s']:x['e']] != x['raw']]
    overlap = [(a['id'], b['id']) for a in live for b in live if a['id'] < b['id'] and a['block'] == b['block'] and a['s'] < b['e'] and b['s'] < a['e']]
    G['G3 교정 좌표'] = [not anchor and not overlap, f'{len(live)}건 모두 원문[s:e]=raw, 겹침 {len(overlap)}' + (f' · 어긋남 {anchor}' if anchor else '')]
    weak = [x['id'] for x in live if x['status'] in APPLIED and (not x['fix'] or (x['method'] == 'llm' and x.get('conf', 0) < AUTO_CONF))]
    G['G4 적용 기준'] = [not weak, f"적용 {sum(x['status'] in APPLIED for x in live)}건 모두 사람 확인·용어집·conf≥{AUTO_CONF}" + (f' · 위반 {weak}' if weak else '')]
    spans = sections_to_spans(an['sections'], blocks, meta['total'])
    ok = spans[0]['start'] == 0 and spans[-1]['end'] == meta['total'] and all(a['end'] == b['start'] and a['start'] < a['end'] for a, b in zip(spans, spans[1:]))
    durs = sum((blocks[i + 1]['sec'] if i < len(blocks) - 1 else meta['total']) - b['sec'] for i, b in enumerate(blocks))
    G['G5 시간 보존'] = [ok and durs + blocks[0]['sec'] == meta['total'], f"구간 {len(spans)}개가 0~{meta['total']}초를 빈틈·겹침 없이 덮음"]
    # 교정본을 원문으로 되돌릴 수 있는가(교정이 정보를 잃지 않는가)
    rev = True
    for i, b in enumerate(blocks):
        fx = sorted((x for x in live if x['block'] == i and x['status'] in APPLIED), key=lambda x: x['s'])
        t, p, back = fixed_text(b['text'], [{'s': x['s'], 'e': x['e'], 'fix': x['fix'], 'st': x['status']} for x in fx]), 0, []
        shift = 0
        for x in fx:
            s2 = x['s'] + shift
            back.append(t[p:s2] + x['raw'])
            p = s2 + len(x['fix'])
            shift += len(x['fix']) - (x['e'] - x['s'])
        rev &= ''.join(back) + t[p:] == b['text']
    G['G6 교정 가역성'] = [rev, '교정본에서 교정을 되돌리면 원문과 글자 단위로 같음']
    return G


def cmd_audit():
    res = {'meetings': {}, 'pass': True}
    for mid in meetings():
        G = audit_meeting(mid)
        res['meetings'][mid] = G
        res['pass'] &= all(v[0] for v in G.values())
    # 산출물 게이트
    d1 = json.dumps(cmd_build(quiet=True), ensure_ascii=False, sort_keys=True)
    d2 = json.dumps(cmd_build(quiet=True), ensure_ascii=False, sort_keys=True)
    with open(os.path.join(BASE, 'data.js'), encoding='utf-8') as f:
        js = f.read()
    D = json.loads(js[len('window.DATA='):-1])
    out = {'G7 재현성': [d1 == d2, '같은 입력으로 두 번 빌드한 결과가 같음']}
    miss = []
    for mid in meetings():
        with open(mpath(mid, 'notion.md'), encoding='utf-8') as f:
            nm = f.read()
        miss += [i['id'] for i in D['items'] if i['t'] == mid and (i['id'] not in nm or md(i['quote']) not in nm)]
        secs = sum(int(x) for x in re.findall(r':s\d+, [\d:]+, (\d+)s', nm))
        if secs != D['meetings'][mid]['total']:
            miss.append(f'{mid} 간트 합 {secs}')
    out['G8 Notion 일치'] = [not miss, 'Notion 마크다운에 모든 항목·인용이 있고 간트 구간 합 = 회의 길이' + (f' · 누락 {miss}' if miss else '')]
    wbad = []
    for mid in meetings():
        with open(mpath(mid, 'notion_widget.html'), encoding='utf-8') as f:
            wh = f.read()
        m = re.search(r'<script id="nodus-data" type="application/json">(.*?)</script>', wh, re.S)
        wd = json.loads(m.group(1).replace('<\\/', '</').replace('<\\!--', '<!--')) if m else None
        rest = wh.replace(m.group(0), '') if m else wh
        if re.search(r'(?:src|href)\s*=\s*["\']?(?:https?:)?//|@import|url\(\s*["\']?https?:|\bfetch\(|XMLHttpRequest|WebSocket|<link\b|<iframe\b', rest):
            wbad.append(f'{mid} 외부 참조')
        if not wd or [i['id'] for i in wd['items']] != [i['id'] for i in D['items'] if i['t'] == mid] or any(i['quote'] != x['quote'] for i, x in zip(wd['items'], [x for x in D['items'] if x['t'] == mid])):
            wbad.append(f'{mid} 항목·인용 불일치')
        if wd and sum(s['end'] - s['start'] for s in wd['sections']) != D['meetings'][mid]['total']:
            wbad.append(f'{mid} 구간 합')
        if len(wh.encode('utf-8')) > 500_000:
            wbad.append(f'{mid} 500KB 초과')
    out['G10 위젯 자기완결'] = [not wbad, 'Notion HTML 위젯이 외부 주소·네트워크 호출 없이 한 파일이고, 항목·인용·구간 합이 뷰어 데이터와 같으며 500KB 이하' + (f' · {wbad}' if wbad else '')]
    legacy = jload(os.path.join(BASE, 'data', 'blocks.json'))
    if legacy:
        same = all([(b['ts'], b['text']) for b in legacy[m]] == [(b['ts'], b['text']) for b in jload(mpath(m, 'blocks.json'))] for m in legacy if m in meetings())
        out['G9 기존 원문 일치'] = [same, '이전 버전 data/blocks.json 과 글자 단위로 같음']
    res['outputs'] = out
    res['pass'] &= all(v[0] for v in out.values())
    res['eval'] = evaluate()
    jsave(os.path.join(BASE, 'data', 'audit.json'), res)
    cmd_build(quiet=True)
    for scope, G in list(res['meetings'].items()) + [('산출물', out)]:
        for k, v in G.items():
            print(f"{'PASS' if v[0] else 'FAIL'}  {scope:4s} {k}: {v[1]}")
    for k, v in res['eval'].items():
        print(f'측정  {k}: {v}')
    print('audit:', 'PASS' if res['pass'] else 'FAIL')
    return res['pass']


# ---------- 7. eval: 사람이 확정한 정답(gold)에 대한 탐지기 성능 ----------
def evaluate():
    gold = jload(os.path.join(BASE, 'data', 'gold.json'))
    if not gold:
        return {}
    lex = lexicon()

    def recall(found_by_mid):
        hit = 0
        for g in gold['corrections']:
            blocks = jload(mpath(g['t'], 'blocks.json'))
            hit += any(blocks[x['block']]['ts'] == g['ts'] and (x['raw'] in g['raw'] or g['raw'] in x['raw']) for x in found_by_mid[g['t']])
        return hit

    mids = sorted({g['t'] for g in gold['corrections']})
    n = len(gold['corrections'])
    cold = {m: detect(m, use_lexicon=False, use_terms=False)[1] for m in mids}
    terms_only = {'fixes': [], 'terms': sorted(all_terms(lex)), 'rejected': []}
    warm = {m: detect(m, use_lexicon=False, lex=terms_only)[1] for m in mids}
    full = {m: detect(m)[1] for m in mids}
    res = {'ASR 재현율 ① 사전 없음(변이 탐지만)': f'{recall(cold)}/{n} · 후보 {sum(map(len, cold.values()))}건',
           'ASR 재현율 ② 올바른 용어 목록만 줌': f'{recall(warm)}/{n} · 후보 {sum(map(len, warm.values()))}건',
           'ASR 재현율 ③ 교정 사전 학습 후': f'{recall(full)}/{n} (정답으로 사전을 만들었으므로 당연한 값 — 다음 회의에서만 의미 있음)'}
    fu_hit = dec_hit = seg_hit = seg_n = seg_pred = 0
    for m in mids:
        blocks, meta = jload(mpath(m, 'blocks.json')), jload(mpath(m, 'meta.json'))
        r = rule_extract(blocks, meta['total'])
        ts = lambda kind: {blocks[i['block']]['ts'] for i in r['items'] if i['kind'] == kind}
        fu_hit += len(set(gold['followups'][m]) & ts('후속'))
        dec_hit += len(set(gold['decisions'][m]) & ts('결정'))
        pred = [blocks[s['start_block']]['sec'] for s in r['sections'][1:]]
        seg_pred += len(pred)
        seg_n += len(gold['boundaries'][m])
        seg_hit += sum(any(abs(p - g) <= 90 for p in pred) for g in gold['boundaries'][m])
    nf, nd = sum(len(set(v)) for v in gold['followups'].values()), sum(len(set(v)) for v in gold['decisions'].values())
    res['규칙만으로 찾은 후속 요청 블록'] = f'{fu_hit}/{nf}'
    res['규칙만으로 찾은 결정 블록'] = f'{dec_hit}/{nd}'
    res['규칙만으로 찾은 구간 경계(±90초)'] = f'{seg_hit}/{seg_n} · 예측 {seg_pred}개'
    return res


# ---------- 기존 T1/T2 데이터 이관(한 번만) ----------
def cmd_migrate():
    V = jload(os.path.join(BASE, 'data', 'viz_data.json'))
    if 'order' in V:
        sys.exit('이미 이관됨')
    raw_fix = {'만장일 수인가요?': ('만장일 수', '만장일치')}
    local_only = {'한 분당'}
    lex = {'fixes': [], 'terms': ['슬로건', '러닝저니', '넥스트 액션', '단톡방', '브루노', '무드 아카이브', '만장일치'], 'rejected': []}
    gold = {'corrections': [], 'decisions': {}, 'followups': {}, 'boundaries': {}}
    src = open(os.path.join(BASE, 'scripts', 'build_xlsx.py'), encoding='utf-8').read()
    garb = ast.literal_eval(re.search(r"GARB=(\[.*?\])\n", src).group(1))
    for mid, M in V['meetings'].items():
        blocks = [{'ts': b['ts'], 'sec': b['sec'], 'text': b['text']} for b in M['blocks']]
        jsave(mpath(mid, 'blocks.json'), blocks)
        jsave(mpath(mid, 'meta.json'), {'id': mid, 'title': mid + ' 회의', 'total': M['total'], 'source_hash': text_hash(blocks), 'source_file': 'data/blocks.json (v3)'})
        secs, last = [], None
        for b in M['blocks']:
            if b['sec_name'] != last:
                secs.append({'name': b['sec_name'], 'start_block': b['i']})
                last = b['sec_name']
        items = []
        for it in V['items']:
            if it['t'] != mid:
                continue
            keys = ('id', 'kind', 'type', 'block', 'summary', 'quote') + (('q', 'resp') if it['kind'] == '결정' else ('due', 'who'))
            items.append({**{k: it[k] for k in keys}, 'origin': 'v3'})
        codes = {str(b['i']): [c for c in b['codes'] if c != 'E'] for b in M['blocks'] if [c for c in b['codes'] if c != 'E']}
        jsave(mpath(mid, 'analysis.json'), {'sections': secs, 'codes': codes, 'items': items, 'origin': 'v3'})
        asr = []
        for c in V['corr']:
            if c['t'] != mid:
                continue
            raw, fix = raw_fix.get(c['raw'], (c['raw'], c['fix']))
            g = re.match(r'^(.*?)\((.*)\)$', fix)
            fix, gloss = (g.group(1), g.group(2)) if g else (fix, '')
            bi = next(i for i, b in enumerate(blocks) if b['ts'] == c['ts'] and raw in b['text'])
            s = blocks[bi]['text'].index(raw)
            note = ' · '.join(x for x in (gloss, c['note']) if x)
            asr.append({'block': bi, 's': s, 'e': s + len(raw), 'raw': raw, 'fix': fix, 'conf': 1.0, 'method': 'human', 'status': 'confirmed', 'note': note, 'source': 'Ro 2026-11-14'})
            fx = {'raw': raw, 'fix': fix, 'note': gloss, 'source': '사람(Ro 2026-11-14)'}
            if raw in local_only:
                fx['only'] = [mid, c['ts']]
            lex['fixes'].append(fx)
            gold['corrections'].append({'t': mid, 'ts': c['ts'], 'raw': raw, 'fix': fix})
        for bi, b in enumerate(blocks):
            for gterm in garb:
                for m in re.finditer(re.escape(gterm), b['text']):
                    asr.append({'block': bi, 's': m.start(), 'e': m.end(), 'raw': gterm, 'fix': None, 'conf': 0.3, 'method': 'legacy-flag', 'status': 'suspect', 'note': 'v3에서 전사 의심으로 표시'})
        asr = resolve(asr)
        for x in asr:
            x['ts'] = blocks[x['block']]['ts']
        jsave(mpath(mid, 'asr.json'), asr)
        gold['decisions'][mid] = [i['ts'] for i in V['items'] if i['t'] == mid and i['kind'] == '결정']
        gold['followups'][mid] = [i['ts'] for i in V['items'] if i['t'] == mid and i['kind'] == '후속']
        gold['boundaries'][mid] = [blocks[s['start_block']]['sec'] for s in secs[1:]]
    jsave(LEX, lex)
    jsave(os.path.join(BASE, 'data', 'gold.json'), gold)
    print('migrate: T1/T2 → data/meetings/, lexicon.json, data/gold.json')


def cmd_learn(mid):
    """사람이 confirmed 로 바꾼 교정을 사전에 넣고, rejected 는 다시 제안하지 않게 한다."""
    lex, asr = lexicon(), jload(mpath(mid, 'asr.json'), [])
    have = {(f['raw'], f['fix']) for f in lex['fixes']}
    rej = {(r['raw'], r['fix']) for r in lex['rejected']}
    add = 0
    for x in asr:
        k = (x['raw'], x['fix'])
        if x['status'] == 'confirmed' and x['fix'] and k not in have:
            lex['fixes'].append({'raw': x['raw'], 'fix': x['fix'], 'note': x.get('note', ''), 'source': f'사람({mid})'})
            have.add(k)
            add += 1
        local = any(f['fix'] == x['fix'] and f.get('only') for f in lex['fixes'])   # 그 자리에서만 맞는 교정은 용어로 일반화하지 않는다
        if x['status'] in APPLIED and x['fix'] and not local and x['fix'] not in lex['terms'] and len(x['fix'].replace(' ', '')) >= 3:
            lex['terms'].append(x['fix'])
        if x['status'] == 'rejected' and k not in rej:
            lex['rejected'].append({'raw': x['raw'], 'fix': x['fix']})
            rej.add(k)
    lex['terms'].sort()
    jsave(LEX, lex)
    print(f'learn {mid}: 교정 사전 +{add}건 (총 {len(lex["fixes"])}건), 용어 {len(lex["terms"])}개, 거절 목록 {len(lex["rejected"])}건')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('run', 'ingest'):
        p = sub.add_parser(name)
        p.add_argument('id')
        p.add_argument('file')
        p.add_argument('--total', help='회의 길이(초). 없으면 마지막 블록 뒤를 추정')
        p.add_argument('--title')
    for name in ('detect', 'extract', 'request', 'merge', 'learn'):
        p = sub.add_parser(name)
        p.add_argument('id')
        if name == 'extract':
            p.add_argument('--force', action='store_true')
    for name in ('build', 'audit', 'eval', 'migrate'):
        sub.add_parser(name)
    a = ap.parse_args()
    if a.cmd in ('run', 'ingest'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,20}', a.id):
            sys.exit('ID 는 영문·숫자·-_ 20자 이내')
        if os.path.exists(mpath(a.id, 'blocks.json')):
            sys.exit(f'{a.id} 는 이미 있다. 다른 ID 를 쓰거나 data/meetings/{a.id} 를 지워라.')
        cmd_ingest(a.id, a.file, a.total, a.title)
        if a.cmd == 'run':
            cmd_detect(a.id)
            cmd_extract(a.id)
            cmd_request(a.id)
            cmd_merge(a.id)
            sys.exit(0 if cmd_audit() else 1)
    elif a.cmd == 'detect':
        cmd_detect(a.id)
    elif a.cmd == 'extract':
        cmd_extract(a.id, a.force)
    elif a.cmd == 'request':
        cmd_request(a.id)
    elif a.cmd == 'merge':
        cmd_merge(a.id)
        cmd_learn(a.id)
        sys.exit(0 if cmd_audit() else 1)
    elif a.cmd == 'learn':
        cmd_learn(a.id)
    elif a.cmd == 'build':
        cmd_build()
    elif a.cmd == 'audit':
        sys.exit(0 if cmd_audit() else 1)
    elif a.cmd == 'eval':
        for k, v in evaluate().items():
            print(f'{k}: {v}')
    elif a.cmd == 'migrate':
        cmd_migrate()


if __name__ == '__main__':
    main()
