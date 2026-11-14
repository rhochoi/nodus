# nodus
Because nobody actually reads 1-hour sync docs in Notion

녹취록 → 전사 교정 → 결정·후속 요청 추출 → 뷰어·Notion 페이지까지 한 번에 만드는 파이프라인입니다.
사용법과 검사 항목은 **[`meeting-viz/README.md`](meeting-viz/README.md)** 를 보세요.

```bash
cd meeting-viz
python3 nodus.py run T3 녹취록.txt --title "회의 제목"
python3 nodus.py audit
```

## 폴더 안내
- `meeting-viz/` — 파이프라인 본체(`nodus.py`), 교정 사전, 회의별 데이터, 뷰어
- `meeting-viz/data/meetings/<ID>/` — 회의 하나의 원문·교정·분석·Notion 산출물
- v3 원본 파일(`meeting-viz/data/blocks.json`, `facts.json`, `viz_data.json`, `scripts/export_viz.py`, `xlsx/`)은 **이전 버전 기록과 검사(G9)용으로 보존**합니다. 새 작업에는 쓰지 않습니다.
