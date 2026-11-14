# 회의 정리 뷰어 (T1 · T2)

## 바로 쓰기
`index.html`을 더블클릭하면 브라우저에서 열린다. 서버·설치 불필요 (`data.js`와 같은 폴더에 있어야 함).

## 폴더
| 경로 | 내용 |
|---|---|
| `index.html`, `data.js` | 뷰어(순수 HTML/JS)와 데이터 |
| `data/blocks.json` | 전사 블록 원문 (T1 192개, T2 138개). 원문은 공백만 정리 |
| `data/facts.json` | 결정 8건·후속 요청 11건 (원문 인용 포함) |
| `data/viz_data.json` | 뷰어가 쓰는 합쳐진 데이터 (`export_viz.py`가 생성) |
| `scripts/build_xlsx.py` | 코딩 규칙·결정/후속·Ro 정정이 들어 있는 원본 스크립트. 실행하면 `xlsx/`를 다시 만든다 (인용 19건 원문 대조 검사 포함) |
| `scripts/export_viz.py` | `data/*` → `data/viz_data.json`, `data.js` |
| `scripts/alpha.py` | 외부 코더 2인의 블라인드 시트로 Krippendorff α 계산: `python3 alpha.py ../xlsx/blind_coding_sheet.xlsx` |
| `xlsx/meeting_coding_v3.xlsx` | AI 1차 코딩·요약·추적표·측정지표·Ro정정 (수식 재계산 완료본) |
| `xlsx/blind_coding_sheet.xlsx` | 외부 코더용 블라인드 시트 (AI 정답 없음) |
| `design-source/` | Claude Design 캔버스의 원본(`Main.dc.html`). Claude Design에서만 열린다 |
| `stageshow-scene/` | stageshow 애니메이션 장면(`index.tsx`, css, `REHEARSAL.md`) |

## 새 회의 추가·수정
1. 전사 블록을 `data/blocks.json`에 `{"T3":[{"ts":"0:00","sec":0,"text":"..."}]}` 형식으로 추가한다.
2. `scripts/build_xlsx.py`에서 구간 경계(`sec_T*`), 수동 코드(`MAN`), 결정(`DEC`)·후속(`FU`)·정정(`CORR`)을 추가한다. 인용은 전사 원문에 그대로 있어야 한다(없으면 검사에서 멈춘다).
3. `scripts/export_viz.py`의 `TOTAL`과 회의 목록(`for t in ('T1','T2')`)에 새 회의를 넣고 실행한다. `index.html`의 탭(`['T1','T2']`)도 추가한다.
4. 화자 정보는 아직 없다. Ro가 기록한 익명 ID 열을 `blocks.json`에 `speaker`로 넣고 뷰어에 표시를 추가하면 된다.

`build_xlsx.py`를 다시 돌리면 수식 값이 비어 있는 xlsx가 나온다. Excel/LibreOffice에서 열어 저장하면 계산된다.
필요한 것: Python 3, `openpyxl` (`pip install openpyxl`).

## 알려진 한계 (정직하게)
- 모든 분류는 AI 1차이며 외부 검증 전이다. 확인 질문·전사 의심 표시는 정규식 후보다.
- 외부 코더 α, 팀원 확인, 후속 이행률, 화자는 미측정/미기록이다. α 임계값 0.800/0.667만 문헌 기준이고 나머지 임계값은 제안값이다.
- `stageshow-scene`의 결정 줄 문구 3개는 `facts.json` 요약과 다르게 줄여 쓴 문구다(인용 카드의 원문만 정확). 쓰기 전에 `facts.json`의 요약 문자열로 바꿔야 한다.
