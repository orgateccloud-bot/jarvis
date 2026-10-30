// Palco holográfico em Three.js. Carregado sob demanda (React.lazy): o three só baixa quando o palco abre.
// Canvas só na área do palco, transparente, sem pós-processamento; 30 fps girando, 60 fps só na
// entrada e na saída; para com a aba oculta; perda de contexto recria a cena num canvas novo.
import { useEffect, useRef, useState } from 'react'
import { PerspectiveCamera, Raycaster, Scene, Vector2, Vector3, WebGLRenderer } from 'three'
import { criarProjetos, posicoes } from './cena/projetos.js'
import { criarCustos, ordemCustos } from './cena/custos.js'
import { proximoQuadro } from '../cosmos/pacing.js'
import { TRANSICAO_MS } from '../cosmos/sol.js'

// cada cena: criar(dados) → { grupo, nos, ids, local, selecionar, atualizar, descartar }; ordem(dados) → itens dos rótulos
const CENAS = {
  projetos: { criar: criarProjetos, ordem: d => posicoes(d.itens, d.grupos).map(p => d.itens.find(it => it.id === p.id)) },
  custos: { criar: criarCustos, ordem: ordemCustos },
}
const REVEAL_S = 0.42

export default function PalcoCena({ categoria, dados, w, h, aberto, selecionado, onSelecionar, onSaiu }) {
  const canvasRef = useRef(null)
  const rotulos = useRef([])
  const ajustar = useRef(null)
  const cenaRef = useRef(null)
  const vivo = useRef({})
  const tamanho = useRef({ w, h })
  const selecionadoInicial = useRef(selecionado)
  const [geracao, setGeracao] = useState(0) // sobe quando o contexto WebGL volta: canvas e cena novos
  const [sobre, setSobre] = useState(null)
  const itens = CENAS[categoria].ordem(dados)

  useEffect(() => { vivo.current = { aberto, onSelecionar, onSaiu } })

  useEffect(() => {
    let cancelado = false
    let limpar = null
    // a cena só nasce depois que o sol termina de andar: criar o contexto e compilar os shaders no meio
    // da transição engasgava o cosmos (fase 3: quadro de 85 ms)
    const t = setTimeout(() => { if (!cancelado) limpar = montar() }, vivo.current.aberto ? TRANSICAO_MS : 0)
    function montar() {
      const canvas = canvasRef.current
      if (!canvas) return null
      let renderer
      try {
        renderer = new WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: 'high-performance' })
      } catch {
        return null // sem WebGL: ficam os rótulos e o painel de detalhes
      }
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
      renderer.setClearColor(0x000000, 0)
      const scene = new Scene()
      const camera = new PerspectiveCamera(38, 1, 0.1, 100)
      camera.position.set(0, 1.4, 10.5)
      camera.lookAt(0, -0.2, 0)
      const cena = CENAS[categoria].criar(dados)
      cenaRef.current = cena
      cena.selecionar(selecionadoInicial.current)
      scene.add(cena.grupo)

      let W = 1
      let H = 1
      ajustar.current = (w2, h2) => {
        W = Math.max(1, w2)
        H = Math.max(1, h2)
        renderer.setSize(W, H, false)
        camera.aspect = W / H
        camera.updateProjectionMatrix()
      }
      ajustar.current(tamanho.current.w, tamanho.current.h)

      const v = new Vector3()
      const posRotulos = reveal => {
        cena.grupo.updateMatrixWorld()
        cena.local.forEach((p, i) => {
          const el = rotulos.current[i]
          if (!el) return
          v.copy(p).applyMatrix4(cena.grupo.matrixWorld)
          const frente = Math.min(1, Math.max(0, (v.z + 3.5) / 7)) // 0 atrás, 1 na frente
          v.project(camera)
          el.style.transform = `translate(${((v.x + 1) / 2) * W}px, ${((1 - v.y) / 2) * H}px) translate(-50%, -160%)`
          el.style.opacity = String(reveal * (0.35 + 0.65 * frente))
        })
      }

      let raf = 0
      let marca = 0
      let last = performance.now()
      let reveal = 0
      let perdido = false
      const frame = now => {
        if (document.hidden || perdido) { raf = 0; return }
        const alvo = vivo.current.aberto ? 1 : 0
        const anim = reveal !== alvo
        const prox = proximoQuadro(now, marca, anim ? 60 : 30)
        if (prox === null) { raf = requestAnimationFrame(frame); return }
        marca = prox
        const dt = Math.min(0.05, (now - last) / 1000)
        last = now
        const passo = reduce ? 1 : dt / REVEAL_S
        reveal = alvo > reveal ? Math.min(alvo, reveal + passo) : Math.max(alvo, reveal - passo)
        cena.atualizar(dt, now / 1000, reveal, !reduce)
        renderer.render(scene, camera)
        posRotulos(reveal)
        if (!alvo && reveal === 0) { raf = 0; vivo.current.onSaiu?.(); return }
        raf = requestAnimationFrame(frame)
      }
      const start = () => {
        if (raf || document.hidden || perdido) return
        last = marca = performance.now()
        raf = requestAnimationFrame(frame)
      }
      // shaders compilados em paralelo (KHR_parallel_shader_compile) antes do primeiro quadro
      renderer.compileAsync(scene, camera).catch(() => {}).then(() => { if (!cancelado) start() })
      const onVis = () => (document.hidden ? (cancelAnimationFrame(raf), (raf = 0)) : start())
      document.addEventListener('visibilitychange', onVis)

      // ponteiro: realça o nó sob o cursor e seleciona no clique
      const ray = new Raycaster()
      const ndc = new Vector2()
      let atual = null
      const onMove = e => {
        const r = canvas.getBoundingClientRect()
        ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
        ray.setFromCamera(ndc, camera)
        const hit = ray.intersectObject(cena.nos)[0]
        const id = hit ? cena.ids[hit.instanceId] : null
        if (id !== atual) {
          atual = id
          canvas.style.cursor = id ? 'pointer' : ''
          setSobre(id)
        }
      }
      const onClick = () => { if (atual) vivo.current.onSelecionar?.(atual) }
      const onLeave = () => { atual = null; canvas.style.cursor = ''; setSobre(null) }
      canvas.addEventListener('pointermove', onMove)
      canvas.addEventListener('click', onClick)
      canvas.addEventListener('pointerleave', onLeave)

      // perda de contexto: para; na volta, um canvas novo recria tudo (o contexto de um canvas é permanente)
      const onLost = e => { e.preventDefault(); perdido = true; cancelAnimationFrame(raf); raf = 0 }
      const onRestored = () => setGeracao(g => g + 1)
      canvas.addEventListener('webglcontextlost', onLost)
      canvas.addEventListener('webglcontextrestored', onRestored)

      return () => {
        cancelAnimationFrame(raf)
        document.removeEventListener('visibilitychange', onVis)
        canvas.removeEventListener('pointermove', onMove)
        canvas.removeEventListener('click', onClick)
        canvas.removeEventListener('pointerleave', onLeave)
        canvas.removeEventListener('webglcontextlost', onLost)
        canvas.removeEventListener('webglcontextrestored', onRestored)
        ajustar.current = null
        cenaRef.current = null
        cena.descartar()
        renderer.dispose()
        renderer.forceContextLoss() // libera a memória de vídeo já, sem esperar o coletor
      }
    }
    return () => { cancelado = true; clearTimeout(t); limpar?.() }
  }, [categoria, dados, geracao])

  // tamanho e seleção mudam sem recriar a cena
  useEffect(() => { tamanho.current = { w, h }; ajustar.current?.(w, h) }, [w, h])
  useEffect(() => { selecionadoInicial.current = selecionado; cenaRef.current?.selecionar(selecionado) }, [selecionado])

  return (
    <>
      <canvas key={geracao} ref={canvasRef} className="holo-palco-canvas" aria-hidden="true" />
      <div className="holo-rotulos">
        {itens.map((it, i) => (
          <button
            key={it.id}
            ref={el => { rotulos.current[i] = el }}
            className={`holo-rotulo ${it.id === selecionado ? 'on' : ''} ${it.id === sobre ? 'sobre' : ''}`}
            style={{ '--c': it.cor || dados.grupos?.[it.grupo]?.cor }}
            onClick={() => onSelecionar(it.id)}
            aria-pressed={it.id === selecionado}
          >
            {it.rotulo || it.nome}
          </button>
        ))}
      </div>
    </>
  )
}
