// Cena "Projetos": constelação de nós (uma InstancedMesh, 1 draw call) e ligações (um LineSegments),
// girando devagar sobre um anel de base. Tamanho do nó pelo commit mais recente; cor pelo grupo.
import {
  AdditiveBlending, BufferGeometry, Color, Float32BufferAttribute, Group, IcosahedronGeometry, InstancedMesh,
  LineBasicMaterial, LineSegments, Mesh, MeshBasicMaterial, Object3D, RingGeometry, Vector3,
} from 'three'
import { materialHolo } from './material.js'

const HOJE = Date.parse('2026-10-30')
const RAIO = 3.1

// tamanho do nó: 0,75 (sem commit) a 1,25 (commit hoje), decaindo em ~3 meses
export const escalaRecencia = ultimo => (ultimo ? 0.75 + 0.5 * Math.exp(-Math.max(0, (HOJE - Date.parse(ultimo)) / 864e5) / 90) : 0.75)

/** Posições determinísticas: nós em anel ordenados por grupo (grupos ficam juntos), alturas variadas. */
export function posicoes(itens, grupos) {
  const ordem = Object.keys(grupos)
  const lista = [...itens].sort((a, b) => ordem.indexOf(a.grupo) - ordem.indexOf(b.grupo))
  return lista.map((it, i) => {
    const ang = (i / lista.length) * Math.PI * 2
    return { id: it.id, x: Math.cos(ang) * RAIO, y: Math.sin(i * 1.7) * 1.1, z: Math.sin(ang) * RAIO }
  })
}

export function criarProjetos(dados) {
  const grupo = new Group()
  grupo.rotation.x = 0.28

  const pos = posicoes(dados.itens, dados.grupos)
  const porId = Object.fromEntries(dados.itens.map(it => [it.id, it]))
  const ids = pos.map(p => p.id)

  const geo = new IcosahedronGeometry(0.32, 1)
  const mat = materialHolo(4)
  const nos = new InstancedMesh(geo, mat, pos.length)
  const o = new Object3D()
  const cores = pos.map(p => new Color(dados.grupos[porId[p.id].grupo]?.cor || '#8fd3ff'))
  pos.forEach((p, i) => {
    o.position.set(p.x, p.y, p.z)
    o.scale.setScalar(escalaRecencia(porId[p.id].ultimo))
    o.updateMatrix()
    nos.setMatrixAt(i, o.matrix)
    nos.setColorAt(i, cores[i])
  })
  nos.computeBoundingSphere()
  grupo.add(nos)

  const idx = Object.fromEntries(ids.map((id, i) => [id, i]))
  const linhas = []
  for (const l of dados.ligacoes) {
    const a = pos[idx[l.de]]
    const b = pos[idx[l.para]]
    if (a && b) linhas.push(a.x, a.y, a.z, b.x, b.y, b.z)
  }
  const geoL = new BufferGeometry()
  geoL.setAttribute('position', new Float32BufferAttribute(linhas, 3))
  const matL = new LineBasicMaterial({ color: 0x8fd3ff, transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false })
  grupo.add(new LineSegments(geoL, matL))

  // anel de base, como um projetor sob o holograma
  const geoA = new RingGeometry(RAIO + 0.35, RAIO + 0.42, 96)
  const matA = new MeshBasicMaterial({ color: 0x4d7cff, transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false })
  const anel = new Mesh(geoA, matA)
  anel.rotation.x = -Math.PI / 2
  anel.position.y = -1.6
  grupo.add(anel)

  const realce = new Color()
  let selecionado = null
  const aplicarSelecao = id => {
    if (id === selecionado) return
    selecionado = id
    cores.forEach((c, i) => nos.setColorAt(i, ids[i] === id ? realce.copy(c).multiplyScalar(2.2) : c))
    nos.instanceColor.needsUpdate = true
  }

  const local = pos.map(p => new Vector3(p.x, p.y, p.z))
  return {
    grupo, nos, ids, local,
    selecionar: aplicarSelecao,
    atualizar(dt, tempo, reveal, girar) {
      if (girar) grupo.rotation.y += dt * 0.12
      mat.uniforms.uTempo.value = tempo
      mat.uniforms.uReveal.value = reveal
      matL.opacity = 0.45 * reveal
      matA.opacity = 0.35 * reveal
    },
    descartar() {
      geo.dispose(); mat.dispose(); nos.dispose(); geoL.dispose(); matL.dispose(); geoA.dispose(); matA.dispose()
    },
  }
}
