import { useEffect, useRef } from 'react'
import { FRAG, VERT } from './shaders.js'
import { fpsAlvo, proximoQuadro } from './pacing.js'
import { TIERS, hexToRgb } from '../lib/tiers.js'

function shader(gl, type, src) {
  const s = gl.createShader(type)
  gl.shaderSource(s, src)
  gl.compileShader(s) // o status só é lido depois de pronto, para não bloquear a página
  return s
}

const lerp = (a, b, k) => a + (b - a) * k

// textura 256² de ruído aleatório determinístico (mulberry32), base de todo o fbm do shader
function noiseTexture(gl) {
  let seed = 0x9e3779b9
  const rnd = () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  const data = new Uint8Array(256 * 256)
  for (let i = 0; i < data.length; i++) data[i] = Math.floor(rnd() * 256)
  const tex = gl.createTexture()
  gl.bindTexture(gl.TEXTURE_2D, tex)
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, 256, 256, 0, gl.RED, gl.UNSIGNED_BYTE, data)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT)
  return tex
}

/**
 * Cosmos em tela cheia atrás da interface: universo em expansão, galáxia espiral e sol flamejante.
 *
 * state: 'idle' | 'listening' | 'thinking' | 'speaking'
 * tier: chave de TIERS (regras | simples | media | complexa) — define a classe estelar do sol
 * alert: tinge de classe M e dispara a ejeção de massa coronal
 * energyRef: ref 0..1 "chutado" a cada trecho/palavra; decai sozinho
 * statsRef: opcional, recebe { fps, scale } para diagnóstico
 */
export default function CosmosScene({ state = 'idle', tier = 'regras', alert = false, energyRef, statsRef }) {
  const canvasRef = useRef(null)
  const target = useRef({ state, tier, alert })
  target.current = { state, tier, alert }

  useEffect(() => {
    const canvas = canvasRef.current
    const gl = canvas.getContext('webgl2', { antialias: false, alpha: false, powerPreference: 'high-performance' })
    if (!gl) {
      canvas.classList.add('cosmos-fallback')
      return
    }
    canvas.classList.add('cosmos-fallback') // gradiente enquanto o shader compila
    const vs = shader(gl, gl.VERTEX_SHADER, VERT)
    const fs = shader(gl, gl.FRAGMENT_SHADER, FRAG)
    const prog = gl.createProgram()
    gl.attachShader(prog, vs)
    gl.attachShader(prog, fs)
    gl.bindAttribLocation(prog, 0, 'p') // posição fixa: consultar o atributo antes do link pronto bloquearia
    // compilação paralela: sem a extensão, a primeira leitura de status bloquearia a página por segundos
    const parallel = gl.getExtension('KHR_parallel_shader_compile')
    gl.linkProgram(prog)
    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
    gl.enableVertexAttribArray(0)
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0)
    const tex = noiseTexture(gl)
    const names = ['uRes', 'uTime', 'uExpand', 'uSpin', 'uListen', 'uThink', 'uSpeak', 'uEnergy',
      'uAlert', 'uBoot', 'uTemp', 'uGiant', 'uTint', 'uSun', 'uSunR']
    let U = null
    let ready = false
    let failed = false
    const finishLink = () => {
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        console.error('CosmosScene: shader', gl.getShaderInfoLog(fs) || gl.getProgramInfoLog(prog))
        failed = true
        return
      }
      gl.useProgram(prog)
      U = Object.fromEntries([...names, 'uOct', 'uLayers', 'uNoise'].map(n => [n, gl.getUniformLocation(prog, n)]))
      gl.uniform1i(U.uOct, 5)
      gl.uniform1i(U.uLayers, 4)
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, tex)
      gl.uniform1i(U.uNoise, 0)
      ready = true
      canvas.classList.remove('cosmos-fallback')
    }

    const dprCap = Math.min(window.devicePixelRatio || 1, 1.5)
    let scale = 0.75
    const resize = () => {
      const w = Math.max(1, Math.round(window.innerWidth * dprCap * scale))
      const h = Math.max(1, Math.round(window.innerHeight * dprCap * scale))
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w
        canvas.height = h
        gl.viewport(0, 0, w, h)
      }
    }
    resize()
    window.addEventListener('resize', resize)

    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const tierOf = tg => TIERS[tg.alert ? 'alerta' : tg.tier] || TIERS.regras
    const t0 = tierOf(target.current)
    const cur = {
      listen: 0, think: 0, speak: 0, energy: 0, alert: 0, boot: 0,
      temp: t0.temp, giant: t0.giant, tint: hexToRgb(t0.galaxy),
      expand: 0, spin: 0, clock: 0,
    }
    let raf = 0
    let last = performance.now()
    let marca = last // cadência do limite de quadros (pacing.js)
    let acc = 0
    let frames = 0

    const draw = () => {
      const aspect = canvas.width / canvas.height
      const mobile = aspect < 0.85
      gl.uniform2f(U.uRes, canvas.width, canvas.height)
      gl.uniform1f(U.uTime, cur.clock)
      gl.uniform1f(U.uExpand, cur.expand)
      gl.uniform1f(U.uSpin, cur.spin)
      gl.uniform1f(U.uListen, cur.listen)
      gl.uniform1f(U.uThink, cur.think)
      gl.uniform1f(U.uSpeak, cur.speak)
      gl.uniform1f(U.uEnergy, cur.energy)
      gl.uniform1f(U.uAlert, cur.alert)
      gl.uniform1f(U.uBoot, cur.boot)
      gl.uniform1f(U.uTemp, cur.temp)
      gl.uniform1f(U.uGiant, cur.giant)
      gl.uniform3fv(U.uTint, cur.tint)
      gl.uniform2f(U.uSun, 0, mobile ? 0.17 : 0.13)
      gl.uniform1f(U.uSunR, mobile ? 0.085 : 0.105)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
    }

    const frame = now => {
      if (!ready) {
        if (failed) return
        if (!parallel || gl.getProgramParameter(prog, parallel.COMPLETION_STATUS_KHR)) finishLink()
        last = marca = now
        raf = requestAnimationFrame(frame)
        return
      }
      // limite de quadros: 30 fps em repouso e escutando, 60 fps pensando ou falando
      const fps = fpsAlvo(target.current.state)
      const prox = proximoQuadro(now, marca, fps)
      if (prox === null) {
        raf = requestAnimationFrame(frame)
        return
      }
      marca = prox
      const realDt = (now - last) / 1000
      const dt = Math.min(0.05, realDt) * (reduce ? 0.3 : 1)
      last = now

      // qualidade adaptativa: mede ~1 s de quadros e ajusta a resolução interna
      acc += realDt
      frames += 1
      if (acc > 1) {
        const ms = (acc / frames) * 1000
        // limiares folgados: navegadores que limitam a 30 fps (aba em 2º plano, economia) não derrubam a resolução;
        // a subida compara com o alvo do limite, senão a 30 fps a resolução nunca voltaria a 1
        if (ms > 45 && scale > 0.5) scale = Math.max(0.5, scale - 0.1)
        else if (ms < (1000 / fps) * 1.2 && scale < 1) scale = Math.min(1, scale + 0.05)
        resize()
        if (statsRef) statsRef.current = { fps: Math.round(frames / acc), scale }
        acc = 0
        frames = 0
      }

      const tg = target.current
      const k = 1 - Math.exp(-dt * 3.5)
      cur.listen = lerp(cur.listen, tg.state === 'listening' ? 1 : 0, k)
      cur.think = lerp(cur.think, tg.state === 'thinking' ? 1 : 0, k)
      cur.speak = lerp(cur.speak, tg.state === 'speaking' ? 1 : 0, k)
      cur.alert = lerp(cur.alert, tg.alert ? 1 : 0, k)
      cur.boot = Math.min(1, cur.boot + dt / 3.2)
      if (energyRef) {
        cur.energy = Math.max(cur.energy * Math.exp(-dt * 3), energyRef.current || 0)
        energyRef.current = (energyRef.current || 0) * Math.exp(-dt * 6)
      }
      const t = tierOf(tg)
      // temperatura interpola em escala log (o olho percebe a cor assim)
      cur.temp = Math.exp(lerp(Math.log(cur.temp), Math.log(t.temp), k * 0.8))
      cur.giant = lerp(cur.giant, t.giant, k * 0.8)
      const tint = hexToRgb(t.galaxy)
      cur.tint = cur.tint.map((v, i) => lerp(v, tint[i], k * 0.8))

      cur.clock += dt
      cur.expand += dt * (1 + 2.2 * cur.think + 0.8 * cur.speak - 0.5 * cur.listen)
      cur.spin += dt * (0.025 + 0.09 * cur.think - 0.01 * cur.listen)

      draw()
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

    if (statsRef) {
      window.__cosmosStill = ({ t = 8, energy = 0.8 } = {}) => {
        if (!ready) finishLink()
        if (!ready) return false
        const tg = target.current
        const tier = tierOf(tg)
        Object.assign(cur, {
          listen: tg.state === 'listening' ? 1 : 0, think: tg.state === 'thinking' ? 1 : 0,
          speak: tg.state === 'speaking' ? 1 : 0, alert: tg.alert ? 1 : 0, boot: 1,
          energy: tg.state === 'speaking' ? energy : 0, temp: tier.temp, giant: tier.giant,
          tint: hexToRgb(tier.galaxy), clock: t, expand: t * 1.5, spin: t * 0.05,
        })
        draw()
        return true
      }
    }

    return () => {
      cancelAnimationFrame(raf)
      if (statsRef) delete window.__cosmosStill
      window.removeEventListener('resize', resize)
      gl.deleteBuffer(buf)
      gl.deleteTexture(tex)
      gl.deleteProgram(prog)
      gl.deleteShader(vs)
      gl.deleteShader(fs)
    }
  }, [energyRef, statsRef])

  return <canvas ref={canvasRef} className="cosmos" aria-hidden="true" />
}
