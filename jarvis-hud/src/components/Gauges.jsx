// Medidores em SVG: anel de progresso e sparkline.

export function Ring({ value = 0, size = 64, stroke = 5, color = 'var(--aurora-2)', children, label }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(100, value || 0))
  return (
    <div className="ring" style={{ width: size, height: size }} role="meter" aria-valuenow={Math.round(v)}
      aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,.07)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 600ms var(--ease), stroke 300ms', filter: `drop-shadow(0 0 4px ${color})` }}
        />
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  )
}

export function Sparkline({ data = [], color = 'var(--aurora-3)', height = 34, max = 100 }) {
  const w = 120
  if (data.length < 2) return <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" />
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, height - (Math.min(v, max) / max) * (height - 2) - 1])
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `0,${height} ${line} ${w},${height}`
  const id = `g${color.replace(/[^a-z0-9]/gi, '')}`
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.35" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${id})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
