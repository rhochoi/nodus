# nodus · 회의 녹취록 → 전사 교정 → 시각화

녹취록(자동 전사본)을 넣으면 ① 음성인식 오류를 찾아 ② 원문은 그대로 둔 채 교정 층을 만들고 ③ 결정·후속 요청·구간을 뽑아 ④ 뷰어(`index.html`)와 Notion용 페이지(`notion.md`)를 만든다. 마지막에 누구나 다시 돌릴 수 있는 검사(`audit`)가 돈다.

필요한 것: Python 3 (추가 설치 없음). 뷰어는 `index.html`을 더블클릭하면 열린다.

## 새 회의 넣기

```bash
python3 nodus.py run T3 녹취록.txt --title "11월 3주 TM"
```

녹취록은 줄 머리에 `[분:초]` 또는 `[시:분:초]`가 있는 텍스트다(`0:31 본문`처럼 괄호 없는 형식도 받지만 괄호가 안전하다). 회의 길이를 알면 `--total 초`를 준다.

이 한 줄이 하는 일:

| 단계 | 하는 일 | 산출물 (`data/meetings/T3/`) |
|---|---|---|
| ingest | 타임스탬프 블록으로 자름. 글자는 안 바꾸고 공백만 정리. 받은 파일을 그대로 보관 | `raw.txt`, `blocks.json`, `meta.json` |
| detect | 교정 사전에 있는 오인식은 자동 적용, 용어집과 비슷한 낱말·드문 변이는 후보로 표시 | `asr.json` |
| extract | 규칙으로 확인 질문·결정·후속 요청 후보와 구간을 1차 추출 | `analysis.json` |
| request | LLM에게 줄 요청서(규칙 + 용어집 + 후보 + 전사본 전체) 작성 | `llm_request.md` |
| merge | `llm_response.json`이 있으면 검증해서 반영(없으면 건너뜀) | `asr.json`, `analysis.json`, `merge_report.json` |
| build | 뷰어 데이터와 Notion 마크다운 생성 | `../../../data.js`, `notion.md` |
| audit | 게이트 검사. 하나라도 실패하면 종료 코드 1 | `data/audit.json` |

### LLM 단계
`run`은 LLM 없이도 끝까지 돈다(규칙 기반 후보만 표시). 문맥 판단이 필요한 교정과 결정 분류는 LLM이 한다.

1. Claude Code 등에게 `data/meetings/T3/llm_request.md`를 읽고 같은 폴더에 `llm_response.json`을 쓰게 한다.
2. `python3 nodus.py merge T3` — 응답을 검증·반영하고 사전을 갱신한 뒤 audit까지 돈다.

LLM 응답은 믿지 않고 검사한다. `raw`가 그 블록 원문에 글자 그대로 없거나, 인용이 원문에 없거나, 형식이 틀리면 이유와 함께 `merge_report.json`으로 떨어진다. 신뢰도 0.9 미만 교정은 적용하지 않고 "확인 대기"로만 보인다.

### 사람이 확인하기
`asr.json`에서 맞는 교정의 `status`를 `confirmed`로, 틀린 것은 `rejected`로 바꾸고

```bash
python3 nodus.py learn T3
```

```bash
python3 nodus.py build
```

확정한 교정은 `lexicon.json`에 들어가 다음 회의부터 자동 적용되고, 거절한 것은 다시 제안되지 않는다.

## 교정 상태
| 상태 | 뜻 | 뷰어 표시 |
|---|---|---|
| confirmed | 사람이 확인 | 초록 |
| auto | 교정 사전에 있던 것, 또는 LLM 신뢰도 0.9 이상 | 파랑 |
| suggest | 교정안은 있으나 확신 부족 — 적용 안 됨 | 주황 점선 |
| suspect | 이상해 보이지만 교정안 없음 | 회색 점선 |
| rejected | 오탐으로 판정 | 숨김 |

뷰어 오른쪽 위에서 "교정본 / 전사 원문"을 바꿔 볼 수 있다. 결정·후속 요청의 큰 인용문은 언제나 전사 원문이다.

## Notion
`data/meetings/<ID>/notion.md`는 Notion이 바로 그리는 형식이다: mermaid 간트(구간 + 결정·후속 시점), mermaid 원형(시간 배분), 결정·후속·교정 표. Notion 페이지에 붙여 넣거나, Claude Code에 Notion 커넥터가 있으면 "T3 notion.md를 Notion에 올려 줘"라고 하면 된다.

## 검사
```bash
python3 nodus.py audit
```

```bash
python3 tests/test_nodus.py
```

| 게이트 | 확인하는 것 |
|---|---|
| G1 원문 불변 | 보관한 `raw.txt`를 다시 파싱한 결과가 `blocks.json`과 같다 |
| G2 인용 정확도 | 모든 인용이 해당 블록 원문에 글자 그대로 있다 |
| G3 교정 좌표 | 모든 교정이 원문 `[s:e]`와 일치하고 서로 겹치지 않는다 |
| G4 적용 기준 | 적용된 교정은 전부 사람 확인·사전·신뢰도 0.9 이상이다 |
| G5 시간 보존 | 구간이 0초부터 회의 끝까지 빈틈·겹침 없이 덮는다 |
| G6 교정 가역성 | 교정본에서 교정을 되돌리면 원문과 글자 단위로 같다 |
| G7 재현성 | 같은 입력으로 두 번 빌드한 결과가 같다 |
| G8 Notion 일치 | Notion 마크다운에 모든 항목·인용이 있고 간트 합이 회의 길이와 같다 |
| G9 기존 원문 일치 | T1·T2 원문이 이전 버전 `data/blocks.json`과 같다 |

`tests/test_nodus.py`는 데이터를 일부러 망가뜨려 G1~G5가 실제로 FAIL을 내는지도 확인한다.

## 지금 성능 (T1·T2, `python3 nodus.py eval`)
정답은 Ro가 확인한 교정 8건과 v3의 결정 8건·후속 요청 11건·구간 경계 15개다.

| 측정 | 값 |
|---|---|
| ASR 재현율 — 사전·용어집 없이 | 0/8 |
| ASR 재현율 — 올바른 용어 목록만 준 경우 | 5/8 |
| ASR 재현율 — 교정 사전 학습 후 | 8/8 (같은 데이터로 만든 사전이라 다음 회의에서만 의미 있음) |
| 규칙만으로 찾은 후속 요청 블록 | 8/9 |
| 규칙만으로 찾은 결정 블록 | 6/8 |
| 규칙만으로 찾은 구간 경계(±90초) | 6/15 (예측 18개) |

## 알려진 한계
- 사전이 없는 첫 회의에서는 기계 탐지가 거의 못 잡는다. 팀 고유명사(사람·프로젝트·용어)를 `lexicon.json`의 `terms`에 먼저 적어 두면 5/8 수준으로 올라간다. 나머지는 LLM 단계와 사람 확인에 달려 있다.
- T1·T2의 LLM 판정은 기계 후보와 v3 의심 표시(약 60곳)만 검토했다. 전사본 전체를 읽고 새 오류를 찾는 검토는 하지 않았다.
- "자동 적용(auto)" 가운데 LLM 판정은 사람이 확인한 것이 아니다. 팀 정정률은 아직 미측정이다.
- 규칙 기반 구간 나누기는 약하다(6/15). 구간 이름·경계는 LLM 단계에서 정하는 것을 전제로 한다.
- 분류(확정/제안/보류)의 외부 코더 일치도 α, 후속 이행률, 화자는 여전히 미측정이다. 화자는 녹취록 본문이 `화자1: …` 형식이면 읽지만 뷰어에는 아직 표시하지 않는다.
- 결정·후속의 요약 문구에는 v3 때 쓴 전사 표기가 남아 있는 곳이 있다(예: T2-A4).

## 폴더
| 경로 | 내용 |
|---|---|
| `nodus.py` | 파이프라인 전체 |
| `lexicon.json` | 교정 사전(`fixes`), 올바른 용어(`terms`), 거절 목록(`rejected`) |
| `data/meetings/<ID>/` | 회의별 원문·교정·분석·Notion 마크다운 |
| `data/gold.json` | 성능 측정용 정답(T1·T2) |
| `index.html`, `data.js` | 뷰어와 데이터 |
| `tests/test_nodus.py` | 기능·게이트 검사 |
| `scripts/build_xlsx.py`, `scripts/alpha.py`, `xlsx/` | v3 코딩 엑셀과 외부 코더 α 계산(T1·T2 전용, 그대로 동작) |
| `scripts/export_viz.py` | v3 내보내기. 지금은 `nodus.py build`가 대신한다 |
| `data/blocks.json`, `data/facts.json` | v3 원본(G9 대조용으로 보존) |
| `design-source/`, `stageshow-scene/` | 디자인 원본과 애니메이션 장면 |
