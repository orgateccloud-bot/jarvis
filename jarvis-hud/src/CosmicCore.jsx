import { useEffect, useRef } from 'react'

/*
 * CosmicCore — o "corpo" do JARVIS: um astro de luz renderizado na GPU (WebGL2, sem dependências).
 *
 * Leitura das imagens do universo que guia cada camada do shader:
 *   núcleo de galáxia / quasar   → núcleo branco-quente com halo 1/r (respira no ocioso)
 *   estrelas do JWST             → picos de difração 6 + 2 (intensificam na fala)
 *   espirais / disco de acreção  → braços em espiral logarítmica num disco inclinado (aceleram ao pensar)
 *   nebulosas (Pilares, Carina)  → gás turbulento por fbm com domain warp (cor por modelo)
 *   pulsar                       → ondas concêntricas puxadas pela energia da fala
 *   supernova (Caranguejo)       → paleta vermelho-laranja no alerta
 *   campo profundo               → estrelas em 3 camadas com cintilação
 */

// Paletas [núcleo, gás interno, gás externo] por camada — RGB 0..1
const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
const PALETTES = {
  regras: ['#EAF6FF', '#4D7CFF', '#0052FF'].map(hex), // Aurora Blue (design system ORGATEC)
  simples: ['#F2F9FF', '#6FB8FF', '#1E40AF'].map(hex), // Plêiades: estrela jovem e quente
  media: ['#FFF4FB', '#A78BFA', '#0EA5E9'].map(hex), // Órion/Carina: violeta e teal
  complexa: ['#FFFDF5', '#FFC56B', '#C2410C'].map(hex), // quasar: ouro e bronze
  alerta: ['#FFF1EC', '#FF5A4D', '#FF8A00'].map(hex), // Caranguejo: supernova
}

const VERT = `#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`

const FRAG = `#version 300 es
precision highp float;
out vec4 o;
uniform vec2 uRes;
uniform float uTime, uListen, uThink, uSpeak, uEnergy;
uniform vec3 uCore, uMid, uOuter;

const float PI = 3.14159265;

float hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p){
  float v = 0.0, a = 0.5; mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 5; i++){ v += a * noise(p); p = m * p; a *= 0.5; }
  return v;
}

// campo profundo: 3 camadas de estrelas com cintilação
vec3 stars(vec2 uv, float t){
  vec3 c = vec3(0.0);
  for (int l = 0; l < 3; l++){
    float s = 14.0 + float(l) * 20.0;
    vec2 g = uv * s + float(l) * 17.3 + vec2(t * 0.004 * float(l + 1), 0.0);
    vec2 id = floor(g), f = fract(g) - 0.5;
    float h = hash(id);
    if (h > 0.9){
      vec2 off = vec2(hash(id + 1.3), hash(id + 7.1)) - 0.5;
      float d = length(f - off * 0.7);
      float tw = 0.55 + 0.45 * sin(t * (1.0 + h * 3.0) + h * 40.0);
      vec3 tint = mix(vec3(0.65, 0.78, 1.0), vec3(1.0, 0.86, 0.72), hash(id + 3.0));
      c += tint * smoothstep(0.07, 0.0, d) * ((h - 0.9) / 0.1) * tw / (1.0 + float(l));
    }
  }
  return c;
}

// pico de difração ao longo de uma direção
float spike(vec2 p, float ang, float len, float w){
  vec2 dir = vec2(cos(ang), sin(ang));
  float along = abs(dot(p, dir)), perp = abs(dot(p, vec2(-dir.y, dir.x)));
  return exp(-perp / w) * exp(-along / len);
}

void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / min(uRes.x, uRes.y);
  float t = uTime;
  float r = length(uv), a = atan(uv.y, uv.x);
  float energy = uEnergy * (0.35 + 0.65 * uSpeak);

  // disco inclinado (sensação de 3D) e rotação — acelera ao pensar
  vec2 d = vec2(uv.x, uv.y / 0.55);
  float rot = t * (0.05 + 0.45 * uThink);
  vec2 dr = mat2(cos(rot), -sin(rot), sin(rot), cos(rot)) * d;
  float rd = length(dr), ad = atan(dr.y, dr.x);

  // braços espirais logarítmicos + nebulosa com domain warp
  vec2 q = vec2(fbm(dr * 3.0 + t * 0.03), fbm(dr * 3.0 - t * 0.04 + 5.2));
  float neb = fbm(dr * 4.0 + q * 2.2 + vec2(t * 0.02, -t * 0.015));
  // braços quebrados pelo próprio gás: menos "anéis", mais galáxia
  float spiral = sin(2.0 * ad + 4.5 * log(rd + 0.001) - t * (0.35 + 1.8 * uThink) + (neb - 0.5) * 3.0);
  float arm = smoothstep(0.0, 1.0, spiral);
  float disk = exp(-rd * rd * (14.0 - 5.0 * uListen));
  float gas = pow(neb, 1.5) * disk * (0.25 + 0.75 * arm);
  // faixas de poeira escura (como no Sombrero)
  float dust = smoothstep(0.55, 0.78, fbm(dr * 7.0 + q * 3.0 - t * 0.02)) * disk;

  vec3 col = stars(uv, t) * 0.55;
  vec3 gasCol = mix(uOuter, uMid, smoothstep(0.2, 0.7, neb));
  gasCol = mix(gasCol, uCore, exp(-rd * 9.0));
  col += gasCol * gas * (2.1 + 0.8 * uThink + 0.6 * energy);
  col *= 1.0 - 0.55 * dust;

  // filamentos externos de nebulosa (preenchem o campo sem competir com o núcleo)
  float wisp = fbm(uv * 2.3 + q * 1.4 + vec2(t * 0.012, t * 0.008));
  col += mix(uOuter, uMid, wisp) * pow(wisp, 3.0) * smoothstep(0.48, 0.12, r) * 0.7;

  // halo amplo (nebulosa difusa ao redor)
  col += uOuter * 0.05 / (r + 0.08) * smoothstep(0.5, 0.0, r);

  // núcleo: respira no ocioso, expande ao ouvir e pulsa com a fala
  float size = 0.045 + 0.01 * sin(t * 1.3) + 0.02 * uListen + 0.035 * energy;
  float core = exp(-(r * r) / (size * size));
  float halo = pow(size * 0.55 / (r + 0.004), 1.5);
  col += uCore * halo * 0.9 + vec3(1.0) * core * 1.6;

  // picos de difração estilo JWST (6 longos + 2 curtos)
  float sp = spike(uv, PI * 0.5, 0.16, 0.0022) + spike(uv, PI / 6.0, 0.16, 0.0022)
           + spike(uv, 5.0 * PI / 6.0, 0.16, 0.0022) + 0.45 * spike(uv, 0.0, 0.06, 0.0018);
  col += mix(uCore, vec3(1.0), 0.5) * sp * (0.45 + 1.4 * energy + 0.6 * uListen);

  // pulsar: ondas concêntricas com a fala
  // pulsar: frentes de onda finas e irregulares saindo do núcleo
  float wave = sin((r + 0.025 * (neb - 0.5)) * 38.0 - t * 7.0);
  float ring = pow(max(wave, 0.0), 16.0) * exp(-r * 7.5) * smoothstep(0.03, 0.09, r) * energy;
  col += mix(uMid, uCore, 0.4) * ring * 0.75;

  // pensamento: partículas caindo em espiral para o núcleo
  float lanes = 42.0;
  float sector = (a + PI) / (2.0 * PI) * lanes;
  float h = hash(vec2(floor(sector), 3.0));
  float pr = fract(h - t * (0.12 + 0.22 * h)) * 0.48;
  float dAng = (fract(sector) - 0.5) / lanes * 2.0 * PI * r;
  // rastros alongados no sentido radial (matéria caindo no núcleo)
  float part = smoothstep(0.006, 0.0, length(vec2((r - pr) * 0.28, dAng))) * smoothstep(0.48, 0.08, pr);
  col += mix(uMid, uCore, 0.5) * part * uThink * 1.4;

  // tone mapping, borda suave e alfa para compor sobre o HUD
  col = 1.0 - exp(-col * 1.35);
  col *= smoothstep(0.5, 0.36, r);
  o = vec4(col, clamp(max(col.r, max(col.g, col.b)) * 1.15, 0.0, 1.0));
}`

function compile(gl, type, src) {
  const s = gl.createShader(type)
  gl.shaderSource(s, src)
  gl.compileShader(s)
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s))
  return s
}

const lerp = (a, b, k) => a + (b - a) * k

/**
 * state: 'idle' | 'listening' | 'thinking' | 'speaking'
 * tier: 'regras' | 'simples' | 'media' | 'complexa'
 * alert: boolean — tinge de supernova
 * energyRef: ref numérico 0..1 que o app "chuta" a cada palavra/trecho; decai sozinho
 */
export default function CosmicCore({ state = 'idle', tier = 'regras', alert = false, energyRef, size = 420 }) {
  const canvasRef = useRef(null)
  const target = useRef({ state, tier, alert })
  target.current = { state, tier, alert }

  useEffect(() => {
    const canvas = canvasRef.current
    const gl = canvas.getContext('webgl2', { premultipliedAlpha: true, alpha: true, antialias: false })
    if (!gl) {
      canvas.classList.add('cosmic-fallback')
      return
    }
    const prog = gl.createProgram()
    try {
      gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT))
      gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG))
    } catch (e) {
      console.error('CosmicCore: shader', e)
      canvas.classList.add('cosmic-fallback')
      return
    }
    gl.linkProgram(prog)
    gl.useProgram(prog)
    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
    const loc = gl.getAttribLocation(prog, 'p')
    gl.enableVertexAttribArray(loc)
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
    const u = name => gl.getUniformLocation(prog, name)
    const U = {
      res: u('uRes'), time: u('uTime'), listen: u('uListen'), think: u('uThink'),
      speak: u('uSpeak'), energy: u('uEnergy'), core: u('uCore'), mid: u('uMid'), outer: u('uOuter'),
    }

    const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
    canvas.width = size * dpr
    canvas.height = size * dpr
    gl.viewport(0, 0, canvas.width, canvas.height)

    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const paletteOf = tg => (tg.alert ? PALETTES.alerta : PALETTES[tg.tier] || PALETTES.regras)
    const cur = { listen: 0, think: 0, speak: 0, energy: 0, pal: paletteOf(target.current).map(c => [...c]) }
    let raf = 0
    let last = performance.now()
    let clock = 0

    const frame = now => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      clock += dt * (reduce ? 0.25 : 1)
      const tg = target.current
      const k = 1 - Math.exp(-dt * 4) // transições suaves entre estados
      cur.listen = lerp(cur.listen, tg.state === 'listening' ? 1 : 0, k)
      cur.think = lerp(cur.think, tg.state === 'thinking' ? 1 : 0, k)
      cur.speak = lerp(cur.speak, tg.state === 'speaking' ? 1 : 0, k)
      if (energyRef) {
        cur.energy = Math.max(cur.energy * Math.exp(-dt * 3.5), energyRef.current || 0)
        energyRef.current = (energyRef.current || 0) * Math.exp(-dt * 6)
      }
      const pal = paletteOf(tg)
      cur.pal = cur.pal.map((c, i) => c.map((v, j) => lerp(v, pal[i][j], k)))

      gl.uniform2f(U.res, canvas.width, canvas.height)
      gl.uniform1f(U.time, clock)
      gl.uniform1f(U.listen, cur.listen)
      gl.uniform1f(U.think, cur.think)
      gl.uniform1f(U.speak, cur.speak)
      gl.uniform1f(U.energy, cur.energy)
      gl.uniform3fv(U.core, cur.pal[0])
      gl.uniform3fv(U.mid, cur.pal[1])
      gl.uniform3fv(U.outer, cur.pal[2])
      gl.clearColor(0, 0, 0, 0)
      gl.clear(gl.COLOR_BUFFER_BIT)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      gl.deleteBuffer(buf)
      gl.deleteProgram(prog)
    }
  }, [size, energyRef])

  return (
    <canvas
      ref={canvasRef}
      className="cosmic-core"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`JARVIS — ${state}`}
    />
  )
}
