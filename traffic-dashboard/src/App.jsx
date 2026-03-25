import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Chart as ChartJS,
  LineElement, PointElement, LinearScale, CategoryScale,
  Filler, Tooltip, Title,
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip, Title)

// ── Constants ─────────────────────────────────────────────────
const API    = 'http://localhost:5050/api'
const WS_URL = 'ws://localhost:5050/ws'

// ── Helpers ───────────────────────────────────────────────────
function movingAvg(data, win) {
  return data.map((_, i) => {
    const slice = data.slice(Math.max(0, i - win + 1), i + 1)
    return +(slice.reduce((a, b) => a + b, 0) / slice.length).toFixed(2)
  })
}

function fmtTime(ts) {
  return `t=${Math.floor(ts)}s`
}

// ── Shared chart options factory ──────────────────────────────
function chartOpts(yLabel) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
    scales: {
      x: {
        ticks: { color: '#bbb', font: { size: 9 }, maxTicksLimit: 6, maxRotation: 0 },
        grid:  { color: '#f5f5f5' },
      },
      y: {
        min: 0,
        title: { display: true, text: yLabel, color: '#bbb', font: { size: 9 } },
        grid:  { color: '#f5f5f5' },
        ticks: { color: '#bbb', font: { size: 9 }, maxTicksLimit: 4 },
      },
    },
  }
}

// ── Sub-components ────────────────────────────────────────────

function StatusDot({ on, error }) {
  const bg = error ? '#f97316' : on ? '#22c55e' : '#ddd'
  return (
    <span style={{
      display: 'inline-block', width: 7, height: 7,
      borderRadius: '50%', background: bg, flexShrink: 0,
    }} />
  )
}

function StatBar({ junctions, totalQueue, avgWait, cmds }) {
  const items = [
    { label: 'Junctions',   value: junctions ?? '—' },
    { label: 'Total queue', value: totalQueue ?? '—' },
    { label: 'Avg wait',    value: avgWait != null ? avgWait + 's' : '—' },
    { label: 'Switches',    value: cmds ?? '—' },
  ]
  return (
    <div style={{ display: 'flex', borderBottom: '1px solid #e5e5e5' }}>
      {items.map(({ label, value }, i) => (
        <div key={label} style={{
          flex: 1, padding: '12px 16px',
          borderRight: i < items.length - 1 ? '1px solid #e5e5e5' : 'none',
        }}>
          <div style={{ fontSize: 11, color: '#999', marginBottom: 2 }}>{label}</div>
          <div style={{ fontSize: 22, fontWeight: 300 }}>{value}</div>
        </div>
      ))}
    </div>
  )
}

function LiveNums({ live }) {
  if (!live) return null
  const items = [
    { label: 'PCU queue', value: live.pcu_queue ?? '—',                    color: '#3b82f6' },
    { label: 'Max wait',  value: live.max_wait != null ? live.max_wait + 's' : '—', color: '#f97316' },
    { label: 'Phase',     value: 'p' + (live.current_phase ?? '—'),        color: '#111' },
    { label: 'Duration',  value: (live.phase_duration ?? '—') + 's',       color: '#111' },
  ]
  return (
    <div style={{
      display: 'flex', gap: 28, padding: '8px 0',
      borderTop: '1px solid #f0f0f0', borderBottom: '1px solid #f0f0f0',
      marginBottom: 14,
    }}>
      {items.map(({ label, value, color }) => (
        <div key={label}>
          <div style={{ fontSize: 10, color: '#999', marginBottom: 1 }}>{label}</div>
          <div style={{ fontSize: 20, fontWeight: 300, color }}>{value}</div>
        </div>
      ))}
    </div>
  )
}

function QueueChart({ labels, data }) {
  const chartData = {
    labels,
    datasets: [{
      data,
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,.06)',
      borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3,
    }],
  }
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 10, color: '#999', marginBottom: 4 }}>PCU queue</div>
      <div style={{ height: 110 }}>
        <Line data={chartData} options={chartOpts('PCU')} />
      </div>
    </div>
  )
}

function WaitChart({ labels, data, maWindow }) {
  const maData = movingAvg(data, maWindow)
  const chartData = {
    labels,
    datasets: [
      {
        label: 'Avg wait',
        data,
        borderColor: '#f97316',
        backgroundColor: 'rgba(249,115,22,.06)',
        borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3,
      },
      {
        label: `MA(${maWindow})`,
        data: maData,
        borderColor: '#333',
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        borderDash: [4, 3],
        pointRadius: 0, fill: false, tension: 0.3,
      },
    ],
  }
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <div style={{ fontSize: 10, color: '#999' }}>Max wait time</div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <LegendItem color="#f97316" label="avg wait" />
          <LegendItem dashed label={`MA(${maWindow})`} />
        </div>
      </div>
      <div style={{ height: 110 }}>
        <Line data={chartData} options={chartOpts('seconds')} />
      </div>
    </div>
  )
}

function LegendItem({ color, dashed, label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: '#999' }}>
      <div style={{
        width: 20, height: 0,
        borderTop: dashed ? '2px dashed #333' : `2px solid ${color}`,
      }} />
      {label}
    </div>
  )
}

function PhaseChart({ labels, data }) {
  const chartData = {
    labels,
    datasets: [{
      data,
      borderColor: '#aaa',
      backgroundColor: 'rgba(170,170,170,.05)',
      borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0, stepped: true
    }],
  }
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: '#999', marginBottom: 4 }}>Phase index</div>
      <div style={{ height: 110 }}>
        <Line data={chartData} options={chartOpts('index')} />
      </div>
    </div>
  )
}

function CmdTicks({ ticks }) {
  return (
    <div style={{ display: 'flex', gap: 1, height: 3, marginTop: 8 }}>
      {ticks.map((action, i) => (
        <div key={i} style={{ flex: 1, background: action === 1 ? '#f97316' : '#f0f0f0' }} />
      ))}
    </div>
  )
}

function JunctionCard({ jid, rows, live, cmdTicks, maWindow }) {
  const labels = rows.map(r => fmtTime(r.ts))
  return (
    <div style={{ background: '#fff', padding: '16px 20px', borderBottom: '1px solid #e5e5e5' }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
        marginBottom: 12,
      }}>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{jid}</span>
        <span style={{ fontSize: 11, color: '#999' }}>
          {live ? `t=${Math.floor(live.ts)}s` : '—'}
        </span>
      </div>

      <LiveNums live={live} />

      <QueueChart labels={labels} data={rows.map(r => r.pcu_queue)} />
      <WaitChart  labels={labels} data={rows.map(r => +r.max_wait.toFixed(2))} maWindow={maWindow} />
      <PhaseChart labels={labels} data={rows.map(r => r.current_phase)} />
      <CmdTicks ticks={cmdTicks} />
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────
export default function App() {
  const [jids,       setJids]       = useState([])
  const [filterJid,  setFilterJid]  = useState('all')
  const [rangeMin,   setRangeMin]   = useState('15')
  const [maWindow,   setMaWindow]   = useState(5)
  const [stateData,  setStateData]  = useState({})   // jid -> rows[]
  const [cmdData,    setCmdData]    = useState({})   // jid -> rows[]
  const [liveData,   setLiveData]   = useState({})   // jid -> latest WS msg
  const [cmdTicks,   setCmdTicks]   = useState({})   // jid -> bool[]
  const [wsStatus,   setWsStatus]   = useState(false)
  const [wsError,    setWsError]    = useState(false)
  const [apiStatus,  setApiStatus]  = useState(false)
  const [apiError,   setApiError]   = useState(false)
  const [lastPoll,   setLastPoll]   = useState(null)
  const rangeSeconds = {
    "5": 300,
    "15": 900,
    "60": 3600,
  }[rangeMin]

  // Summary stats derived from stateData
  const visibleJids = filterJid === 'all' ? jids : jids.filter(j => j === filterJid)
  const totalQueue  = visibleJids.reduce((s, j) => s + (stateData[j]?.at(-1)?.pcu_queue ?? 0), 0)
  const avgWait     = visibleJids.length
    ? (visibleJids.reduce((s, j) => s + (stateData[j]?.at(-1)?.max_wait ?? 0), 0) / visibleJids.length).toFixed(1)
    : null
  // count only switch commands (action === 1)
  const totalSwitches = visibleJids.reduce(
    (s, j) => s + (cmdData[j]?.filter(c => c.action === 1).length ?? 0), 0
  )

  // ── WebSocket ───────────────────────────────────────────────
  const wsRef = useRef(null)

  const connectWS = useCallback(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen  = () => { setWsStatus(true);  setWsError(false) }
    ws.onclose = () => { setWsStatus(false); setWsError(true); setTimeout(connectWS, 3000) }
    ws.onerror = () => setWsError(true)

    ws.onmessage = ({ data }) => {
      try {
        const msg   = JSON.parse(data)
        const parts = (msg._topic || '').split('/')
        const jid = parts[1], kind = parts[2]
        if (!jid) return

        if (kind === 'state') {
          setLiveData(prev => ({ ...prev, [jid]: msg }))
        }
        if (kind === 'cmd') {
          // store the raw action value (0 or 1) so CmdTicks can colour correctly
          const action = msg.action ?? 0
          setCmdTicks(prev => {
            const existing = prev[jid] || []
            const updated  = [action, ...existing].slice(0, 80)
            return { ...prev, [jid]: updated }
          })
        }
      } catch {}
    }
  }, [])

  useEffect(() => {
    connectWS()
    return () => wsRef.current?.close()
  }, [connectWS])

  // ── Historical poll ─────────────────────────────────────────
  const poll = useCallback(async () => {
  try {
    // 1. get current simulation time
    const { sim_ts } = await fetch(`${API}/sim_time`).then(r => r.json())

    const since = Math.max(0, sim_ts - rangeSeconds)

    const discovered = await fetch(`${API}/junctions`).then(r => r.json())
    if (!discovered.length) { setApiError(true); setApiStatus(false); return }

    setJids(prev => {
      const merged = [...new Set([...prev, ...discovered])]
      return merged.length !== prev.length ? merged : prev
    })

    setApiStatus(true); setApiError(false)

    // 2. use since instead of minutes
    const [states, cmds] = await Promise.all([
      Promise.all(
        discovered.map(j =>
          fetch(`${API}/state/${j}?since=${since}&limit=200`).then(r => r.json())
        )
      ),
      Promise.all(
        discovered.map(j =>
          fetch(`${API}/cmds/${j}?since=${since}&limit=200`).then(r => r.json())
        )
      ),
    ])

    const newState = {}, newCmds = {}
    discovered.forEach((jid, i) => {
      newState[jid] = states[i]
      newCmds[jid] = cmds[i]
    })

    setStateData(newState)
    setCmdData(newCmds)

    // show simulation time instead of wall time
    setLastPoll(`t=${Math.floor(sim_ts)}s`)
  } catch {
    setApiStatus(false); setApiError(true)
  }
}, [rangeMin])

  useEffect(() => {
    poll()
    const id = setInterval(poll, 10000)
    return () => clearInterval(id)
  }, [poll])

  // ── Render ──────────────────────────────────────────────────
  return (
    <div>
      {/* Top bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        padding: '10px 16px', borderBottom: '1px solid #e5e5e5',
      }}>
        <span style={{ fontSize: 13, fontWeight: 500, flex: 1, minWidth: 120 }}>
          Traffic Monitor
        </span>

        {/* Junction filter */}
        <select
          value={filterJid}
          onChange={e => setFilterJid(e.target.value)}
          style={{ border: '1px solid #ddd', padding: '3px 7px', background: '#fff', cursor: 'pointer' }}
        >
          <option value="all">All junctions</option>
          {jids.map(j => <option key={j} value={j}>{j}</option>)}
        </select>

        {/* Time range */}
        <select
          value={rangeMin}
          onChange={e => setRangeMin(e.target.value)}
          style={{ border: '1px solid #ddd', padding: '3px 7px', background: '#fff', cursor: 'pointer' }}
        >
          <option value="5">5 min</option>
          <option value="15">15 min</option>
          <option value="60">1 h</option>
        </select>

        {/* MA window slider */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 11, color: '#999' }}>
          <span>MA</span>
          <input
            type="range" min={2} max={20} value={maWindow}
            onChange={e => setMaWindow(+e.target.value)}
            style={{ width: 80, cursor: 'pointer', accentColor: '#333' }}
          />
          <span style={{ minWidth: 16, color: '#111' }}>{maWindow}</span>
        </div>

        {/* Status indicators */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#999' }}>
          <StatusDot on={wsStatus} error={wsError} /> WS
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#999' }}>
          <StatusDot on={apiStatus} error={apiError} /> API
        </div>
        <span style={{ fontSize: 11, color: '#bbb' }}>{lastPoll || '—'}</span>
      </div>

      {/* Stat bar */}
      <StatBar
        junctions={visibleJids.length || null}
        totalQueue={visibleJids.length ? totalQueue : null}
        avgWait={visibleJids.length ? avgWait : null}
        cmds={visibleJids.length ? totalSwitches : null}
      />

      {/* Cards */}
      {visibleJids.length === 0 ? (
        <div style={{ padding: 60, textAlign: 'center', color: '#bbb', fontSize: 12 }}>
          Waiting for data — is the system running?
        </div>
      ) : (
        <div>
          {visibleJids.map(jid => (
            <JunctionCard
              key={jid}
              jid={jid}
              rows={stateData[jid] || []}
              live={liveData[jid] || null}
              cmdTicks={cmdTicks[jid] || Array(40).fill(false)}
              maWindow={maWindow}
            />
          ))}
        </div>
      )}
    </div>
  )
}