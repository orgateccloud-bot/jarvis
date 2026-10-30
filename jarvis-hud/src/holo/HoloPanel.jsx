/**
 * Painel de vidro posicionado pelo arranjo. Escala sempre 1 (texto nítido): profundidade só pela rotação
 * no eixo Y. `glare` muda a cada evento (fim de resposta, troca de modelo) e faz um brilho varrer o vidro uma vez.
 * decorativo: sem texto para ler, escondido de leitores de tela.
 */
export default function HoloPanel({ id, rect, title, aside, label, glare = '', i = 0, decorativo = false, children }) {
  if (!rect) return null
  const Tag = decorativo ? 'div' : 'section'
  return (
    <Tag
      className={`holo holo-${id}`}
      aria-label={decorativo ? undefined : label || title}
      aria-hidden={decorativo ? 'true' : undefined}
      style={{
        width: rect.w, height: rect.h, '--i': i,
        transform: `translate3d(${rect.x}px, ${rect.y}px, 0) rotateY(${rect.rot}deg)`,
      }}
    >
      {glare ? <span className="holo-glare" key={glare} aria-hidden="true" /> : null}
      {title != null && (
        <header className="holo-head">
          <h2>{title}</h2>
          {aside}
        </header>
      )}
      {children}
    </Tag>
  )
}
