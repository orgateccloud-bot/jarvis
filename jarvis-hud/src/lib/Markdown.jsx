// Markdown mínimo e seguro: gera elementos React (nunca innerHTML).
// Cobre títulos, parágrafos, listas, blocos de código, tabelas simples, **negrito**, *itálico* e `código`.

function inline(text, key) {
  const out = []
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g
  let last = 0
  let i = 0
  let m
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    const k = `${key}-${i++}`
    if (tok.startsWith('`')) out.push(<code key={k}>{tok.slice(1, -1)}</code>)
    else if (tok.startsWith('**')) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>)
    else out.push(<em key={k}>{tok.slice(1, -1)}</em>)
    last = re.lastIndex
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const LIST = /^\s*([-*•]|\d+[.)])\s+/
const TABLE = /^\s*\|.*\|\s*$/
const TABLE_SEP = /^\s*\|?[\s:|-]+\|?\s*$/
const cells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())

export default function Markdown({ text }) {
  const lines = (text || '').replace(/\r/g, '').split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const k = `b${i}`
    if (line.startsWith('```')) {
      const buf = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++])
      i++
      blocks.push(<pre key={k}><code>{buf.join('\n')}</code></pre>)
      continue
    }
    const h = /^(#{1,4})\s+(.*)/.exec(line)
    if (h) {
      const Tag = `h${Math.min(6, h[1].length + 2)}`
      blocks.push(<Tag key={k}>{inline(h[2], k)}</Tag>)
      i++
      continue
    }
    if (LIST.test(line)) {
      const ordered = /^\s*\d/.test(line)
      const items = []
      while (i < lines.length && LIST.test(lines[i])) {
        items.push(<li key={`${k}-${items.length}`}>{inline(lines[i].replace(LIST, ''), `${k}-${items.length}`)}</li>)
        i++
      }
      blocks.push(ordered ? <ol key={k}>{items}</ol> : <ul key={k}>{items}</ul>)
      continue
    }
    if (TABLE.test(line)) {
      const rows = []
      while (i < lines.length && TABLE.test(lines[i])) {
        if (!TABLE_SEP.test(lines[i])) rows.push(cells(lines[i]))
        i++
      }
      if (!rows.length) continue // tabela ainda chegando pelo stream (só separadores)
      const [head, ...body] = rows
      blocks.push(
        <div className="md-table" key={k}>
          <table>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
            <tbody>{body.map((r, ri) => (
              <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>,
      )
      continue
    }
    if (!line.trim()) {
      i++
      continue
    }
    const para = []
    while (i < lines.length && lines[i].trim() && !LIST.test(lines[i]) && !TABLE.test(lines[i])
      && !lines[i].startsWith('```') && !/^#{1,4}\s/.test(lines[i])) {
      para.push(lines[i++])
    }
    blocks.push(<p key={k}>{inline(para.join(' '), k)}</p>)
  }
  return <div className="md">{blocks}</div>
}
