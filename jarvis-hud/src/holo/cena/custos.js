// Cena "Custos": uma barra por modelo (uma InstancedMesh, 1 draw call), altura proporcional ao custo do mês
// a partir de zero, cor da camada. Oscila devagar em vez de girar, para as barras continuarem legíveis.
import {
  AdditiveBlending, BoxGeometry, BufferGeometry, Color, Float32BufferAttribute, Group, InstancedMesh,
  LineBasicMaterial, LineSegments, Object3D, Vector3,
} from 'three'
import { materialHolo } from './material.js'

const BASE = -1.6
const ALTURA = 3.4
const PASSO = 2.2 // espaço entre barras: os rótulos com o valor não se encostam

export const ordemCustos = dados => dados.itens

export function criarCustos(dados) {
  const grupo = new Group()
  grupo.rotation.x = 0.16
  const n = dados.itens.length
  const max = Math.max(1e-6, ...dados.itens.map(it => it.valor))

  const geo = new BoxGeometry(0.9, 1, 0.9)
  geo.translate(0, 0.5, 0) // base da barra no zero
  const mat = materialHolo(2.2)
  const barras = new InstancedMesh(geo, mat, n)
  const o = new Object3D()
  const cores = dados.itens.map(it => new Color(it.cor))
  const local = []
  dados.itens.forEach((it, i) => {
    const x = (i - (dados.itens.length - 1) / 2) * PASSO
    const h = Math.max(0.02, (it.valor / max) * ALTURA)
    o.position.set(x, BASE, 0)
    o.scale.set(1, h, 1)
    o.updateMatrix()
    barras.setMatrixAt(i, o.matrix)
    barras.setColorAt(i, cores[i])
    local.push(new Vector3(x, BASE + h, 0))
  })
  if (n) barras.computeBoundingSphere()
  grupo.add(barras)

  // linha de base (o zero do gráfico)
  const meia = (dados.itens.length / 2) * PASSO + 0.4
  const geoL = new BufferGeometry()
  geoL.setAttribute('position', new Float32BufferAttribute([-meia, BASE, 0.6, meia, BASE, 0.6, -meia, BASE, -0.6, meia, BASE, -0.6], 3))
  const matL = new LineBasicMaterial({ color: 0x8fd3ff, transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false })
  grupo.add(new LineSegments(geoL, matL))

  const ids = dados.itens.map(it => it.id)
  const realce = new Color()
  let selecionado = null
  return {
    grupo, nos: barras, ids, local,
    selecionar(id) {
      if (id === selecionado || !barras.instanceColor) return
      selecionado = id
      cores.forEach((c, i) => barras.setColorAt(i, ids[i] === id ? realce.copy(c).multiplyScalar(2.2) : c))
      barras.instanceColor.needsUpdate = true
    },
    atualizar(dt, tempo, reveal, girar) {
      if (girar) grupo.rotation.y = 0.35 * Math.sin(tempo * 0.25)
      mat.uniforms.uTempo.value = tempo
      mat.uniforms.uReveal.value = reveal
      matL.opacity = 0.5 * reveal
    },
    descartar() {
      geo.dispose(); mat.dispose(); barras.dispose(); geoL.dispose(); matL.dispose()
    },
  }
}
