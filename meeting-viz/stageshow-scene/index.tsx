import { Bar, Stage, Text, Window, Row, Badge } from '../../kit'
import './meeting.css'

// 회의 정리 화면: 결정 목록에서 한 줄을 누르면 원문 인용과 시각이 열린다.
// 실제 글자는 이야기의 대상(결정 3건, 인용, 시각, 상태)에만 쓰고 나머지는 Bar.

type S = { picked: boolean; quote: boolean }
const initial: S = { picked: false, quote: false }

const ROWS = [
  { id: 'd2', time: '53:15', kind: '제안', tone: 'neutral', text: '슬로건 만드는 것은 괜찮은가' },
  { id: 'd4', time: '1:21:32', kind: '확정', tone: 'success', text: '공유 방식, 카운트 후 이의 없음' },
  { id: 'd5', time: '1:22:35', kind: '확정', tone: 'success', text: '다음 액션 정해짐' },
] as const

async function script(a: any) {
  await a.wait(900)
  await a.move('d4')
  await a.wait(300)
  await a.click()
  await a.set({ picked: true })
  await a.wait(250)
  await a.set({ quote: true })
  await a.move('rest')
  await a.wait(3200)
  await a.set({ quote: false })
  await a.wait(300)
  await a.set({ picked: false })
  await a.wait(500)
}

export default function MeetingMap() {
  return (
    <Stage width={720} height={340} compact={{ below: 600, width: 358, height: 300 }} initial={initial} poster={{ picked: true, quote: true }} script={script} cursor={{ at: { wide: { x: 330, y: 290 }, compact: { x: 70, y: 290 } } }} className="mm">
      {(s: S, _r: any, layout: string) => (
        <>
          <Window title="회의 정리 · 2차" className="mm-window">
            <aside className="mm-side">
              <Bar w={20} h={20} r={6} tone={4} style={{ marginBottom: 10 }} />
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="mm-nav"><Bar w={10} h={10} r={3} tone={i === 1 ? 4 : 3} /><Bar w={i === 1 ? 52 : 40} h={6} tone={i === 1 ? 4 : 2} /></div>
              ))}
            </aside>
            <div className="mm-main">
              <div className="mm-head">
                <Text className="mm-title">결정</Text>
                <Badge tone="warning">AI 1차 · 외부 검증 전</Badge>
              </div>
              <div className="mm-list">
                {ROWS.map((r) => (
                  <Row key={r.id} pad={8} className="mm-row" data-target={r.id} selected={r.id === 'd4' && s.picked}
                    title={<Text className="mm-name">{r.text}</Text>}
                    subtitle={<Text className="mm-time">{r.time}</Text>}
                    meta={<Badge tone={r.tone as any}>{r.kind}</Badge>} />
                ))}
                {[70, 56].map((w, i) => (
                  <Row key={i} pad={8} className="mm-row" title={<Bar w={w + 60} tone={3} />} subtitle={<Bar w={30} h={5} tone={2} />}
                    meta={<Bar w={34} h={16} r={8} tone={2} />} />
                ))}
              </div>
            </div>
          </Window>

          <div className="mm-quote" data-show={s.quote} data-layout={layout}>
            <Text className="mm-q-time">1:21:32 · 확인 질문 + 무반대</Text>
            <div className="mm-q-text">“3, 2, 1. 없어요?”</div>
          </div>
          <span data-target="rest" style={{ position: 'absolute', left: layout === "compact" ? 70 : 330, top: 290 }} />
        </>
      )}
    </Stage>
  )
}
