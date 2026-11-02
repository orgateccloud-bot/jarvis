// GLSL do cosmos do JARVIS: universo em expansão + galáxia espiral + o astro do centro (sol ou planeta).
// Coordenadas: uv normalizado pela altura, y para cima, (0,0) no centro da tela.
// O astro é escolhido na compilação (#define ASTRO, ids em lib/astro.js): cada JARVIS compila só o seu.

export const VERT = `#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`

/** Fragment shader do astro `id` (0 = sol). O #version tem de ser a primeira linha; o #define vem logo depois. */
export const fragDoAstro = (id = 0) => `#version 300 es\n#define ASTRO ${id}\n${CORPO}`

const CORPO = `
precision highp float;
out vec4 o;

uniform vec2  uRes;
uniform float uTime;     // relógio da animação
uniform float uExpand;   // fase acumulada da expansão do universo
uniform float uSpin;     // fase acumulada da rotação da galáxia
uniform float uListen, uThink, uSpeak, uEnergy, uAlert, uBoot;
uniform float uTemp;     // temperatura da estrela (K)
uniform float uGiant;    // 0..1 — estrela gigante (Opus)
uniform vec3  uTint;     // tonalidade da galáxia
uniform vec2  uSun;      // centro do sol (uv)
uniform float uSunR;     // raio do sol (uv)
uniform float uFlameLim; // SPIKE: limite da regiao das chamas, em raios (4,5 = como no main)
uniform float uWave;    // 0..1: onda de voz que atravessa o sol enquanto ele fala
// limites de laço vindos de uniforms: impedem o desenrolamento e deixam a compilação (ANGLE/D3D) muito mais rápida
uniform int   uOct;      // oitavas do fbm (5)
uniform int   uLayers;   // camadas do campo profundo (4)
uniform sampler2D uNoise; // textura 256² de ruído aleatório (filtro linear, repetição)

const float PI = 3.14159265;

float hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
// ruído de valor suave com UMA leitura de textura (curva cúbica aplicada à coordenada):
// muito mais barato de compilar e executar do que o ruído por hash
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return texture(uNoise, (i + f + 0.5) / 256.0).r;
}
float fbmN(vec2 p, int oct){
  float v = 0.0, a = 0.5; mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < oct; i++){ v += a * noise(p); p = m * p; a *= 0.5; }
  return v;
}
float fbm(vec2 p){ return fbmN(p, uOct); }
float fbm3(vec2 p){ return fbmN(p, uOct - 2); }   // versão barata para o fundo

// cor de corpo negro (aprox. de Tanner Helland), normalizada
vec3 blackbody(float K){
  float t = K / 100.0;
  float r = t <= 66.0 ? 1.0 : clamp(1.292936 * pow(t - 60.0, -0.1332047), 0.0, 1.0);
  float g = t <= 66.0 ? clamp(0.3900816 * log(t) - 0.6318414, 0.0, 1.0)
                      : clamp(1.129891 * pow(t - 60.0, -0.0755148), 0.0, 1.0);
  float b = t >= 66.0 ? 1.0 : (t <= 19.0 ? 0.0 : clamp(0.5432068 * log(t - 10.0) - 1.19625408, 0.0, 1.0));
  return vec3(r, g, b);
}

mat2 rot(float a){ float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

// ── 1. universo em expansão: camadas que se afastam do centro (zoom infinito) ──
vec3 deepField(vec2 uv){
  vec3 c = vec3(0.0);
  for (int i = 0; i < uLayers; i++){
    float fi = float(i);
    float phase = uExpand * 0.06 + fi / float(uLayers);
    float z = fract(phase);
    float cycle = floor(phase);
    float w = smoothstep(0.0, 0.25, z) * smoothstep(1.0, 0.7, z);   // nasce pequeno, some grande
    float density = mix(26.0, 3.0, z);
    vec2 p = uv * density + vec2(fi * 31.7 + cycle * 7.3, fi * 17.1);
    vec2 id = floor(p), f = fract(p) - 0.5;
    float h = hash(id);
    vec2 off = vec2(hash(id + 3.1), hash(id + 8.7)) - 0.5;
    float d = length(f - off * 0.6) / density;      // distância em uv: tamanho estável na tela
    if (h > 0.86){            // estrela: cresce pouco e brilha mais ao se aproximar
      float tw = 0.6 + 0.4 * sin(uTime * (1.0 + h * 4.0) + h * 50.0);
      vec3 tint = mix(vec3(0.7, 0.8, 1.0), vec3(1.0, 0.85, 0.7), hash(id + 1.7));
      float core = smoothstep(0.0018 + 0.0022 * z, 0.0, d);
      float glow = exp(-d * (420.0 - 200.0 * z)) * 0.35;
      c += tint * (core + glow) * ((h - 0.86) / 0.14) * tw * w * (0.5 + z);
    } else if (h < 0.012){    // galáxia distante: mancha elíptica
      vec2 q = rot(h * 600.0) * (f - off * 0.5);
      q.y *= 2.6;
      float g = exp(-dot(q, q) * 60.0);
      c += mix(uTint, vec3(1.0, 0.9, 0.8), 0.5) * g * 0.55 * w;
    }
  }
  // nebulosa em expansão: duas fases cruzadas, sem emenda
  float neb = 0.0;
  for (int i = 0; i < uLayers / 2; i++){
    float z = fract(uExpand * 0.025 + float(i) * 0.5);
    float wz = sin(z * PI);
    vec2 p = uv * 1.5 * exp2(-z) + float(i) * 13.0;
    vec2 q = vec2(fbm3(p + uTime * 0.01), fbm3(p - 4.3));
    neb += fbm(p + q * 1.8) * wz;
  }
  neb = pow(neb, 2.2);
  c += mix(uTint * 0.6, vec3(0.9, 0.35, 0.6), smoothstep(0.3, 0.7, neb)) * neb * 0.32;
  return c;
}

// ── 2. galáxia espiral ao redor do sol ──
vec3 galaxy(vec2 g){
  float unfold = smoothstep(0.05, 1.0, uBoot);
  vec2 d = vec2(g.x, g.y / 0.5) * rot(uSpin);        // disco inclinado + rotação
  float rd = length(d);
  float radius = 1.05 * unfold;
  if (rd > radius) return vec3(0.0);
  float ad = atan(d.y, d.x);
  float wind = 1.9 - 0.6 * uThink;                   // espiral aberta; desenrola mais ao pensar
  float n = fbm(d * 5.0 + uSpin * 0.2);
  float sp = cos(2.0 * (ad - wind * log(rd + 0.03)) + (n - 0.5) * 2.4);
  float arm = pow(0.5 + 0.5 * sp, 2.6);
  float fall = exp(-rd * 2.4) * smoothstep(radius, radius * 0.35, rd);
  vec3 col = mix(uTint, vec3(1.0, 0.86, 0.66), exp(-rd * 5.0)) * arm * (0.35 + 0.9 * n) * fall * 1.5;
  // aglomerados estelares e regiões HII ao longo dos braços
  float knots = smoothstep(0.72, 0.95, noise(d * 18.0 + 11.0)) * arm;
  col += vec3(1.0, 0.38, 0.62) * knots * fall * 0.7;
  // estrelas do disco no espaço da tela (redondas), giram junto com o disco via deslocamento angular
  vec2 sp2 = (g * rot(uSpin * 0.5)) * 110.0;
  vec2 sid = floor(sp2), sf = fract(sp2) - 0.5;
  float sh = hash(sid + 17.0);
  float star = smoothstep(0.22, 0.0, length(sf - (vec2(hash(sid + 2.0), hash(sid + 5.0)) - 0.5) * 0.5))
             * step(0.9, sh) * (0.3 + arm);
  col += vec3(0.9, 0.95, 1.0) * star * fall * 1.2;
  // faixas de poeira
  float dust = smoothstep(0.52, 0.78, fbm(d * 9.0 + 3.0)) * arm;
  col *= 1.0 - 0.6 * dust * smoothstep(0.05, 0.25, rd);
  // bojo luminoso
  col += vec3(1.0, 0.82, 0.6) * exp(-rd * rd * 40.0) * 0.5;
  return col;
}

#if ASTRO == 0
// ── 3. sol flamejante ──
vec3 sunColor(vec2 g, out float occl){
  occl = 0.0;
  float R = uSunR * (1.0 + 0.18 * uGiant) * smoothstep(0.25, 0.85, uBoot) * (1.0 + 0.03 * uEnergy);
  vec2 sv = g / max(R, 1e-4);
  float sr = length(sv);
  // ajuste artístico: pow satura o corpo negro (5800 K puro é quase branco)
  vec3 star = pow(blackbody(uTemp), vec3(2.2));
  vec3 flame = pow(blackbody(uTemp * 0.7), vec3(2.4));
  vec3 col = vec3(0.0);

  if (sr < 1.0){
    float z = sqrt(1.0 - sr * sr);
    vec3 n = vec3(sv, z);
    float r0 = uTime * 0.035;
    vec3 rn = vec3(n.x * cos(r0) + n.z * sin(r0), n.y, -n.x * sin(r0) + n.z * cos(r0));
    vec2 suv = vec2(atan(rn.x, rn.z), asin(clamp(rn.y, -1.0, 1.0)));
    float boil = uTime * (0.12 + 0.55 * uThink);
    float gran = fbm(suv * 10.0 + vec2(boil, -boil * 0.7));
    float sup = fbm(suv * 2.6 - boil * 0.2 + 5.0);
    float spots = smoothstep(0.7, 0.8, fbm3(suv * 3.2 + 7.0)) * (0.6 + 0.4 * uGiant);
    float limb = pow(z, 0.5);
    float cells = pow(gran, 1.6);
    vec3 photo = mix(flame, star, smoothstep(0.25, 0.75, cells)) * (0.35 + 1.25 * cells + 0.35 * sup) * limb;
    photo *= 1.0 - 0.8 * spots;
    photo = mix(photo, star * 1.4, 0.18 * pow(z, 4.0)); // centro um pouco mais quente
    photo += flame * pow(1.0 - z, 2.5) * 0.9;            // cromosfera na borda
    col = photo * 1.35;
    occl = smoothstep(1.0, 0.985, sr);
  }

  float h = sr - 1.0;
  if (sr < uFlameLim){
    float a = atan(sv.y, sv.x);
    vec2 dir = sv / max(sr, 1e-4);
    // chamas: fluxo radial com duas fases cruzadas (sem distorção acumulada)
    float spd = 0.22 + 0.25 * uSpeak + 0.2 * uThink;
    float t1 = fract(uTime * spd), t2 = fract(uTime * spd + 0.5);
    float f1 = fbm(sv * 2.4 - dir * t1 * 2.2);
    float f2 = fbm(sv * 2.4 - dir * t2 * 2.2 + 9.0);
    float fl = mix(f1, f2, abs(2.0 * t1 - 1.0));
    float reach = max(2.6, 4.6 - 1.4 * uEnergy - 0.9 * uGiant - 0.6 * uThink);   // chamas ficam junto ao limbo
    float flames = pow(fl, 1.7) * exp(-max(h, 0.0) * reach) * smoothstep(-0.02, 0.02, h);
    float tongues = smoothstep(0.5, 0.85, fl) * exp(-max(h, 0.0) * reach * 0.55);   // línguas de fogo
    // proeminências: arcos que sobem do limbo
    vec2 ring = vec2(cos(a), sin(a));
    float prom = smoothstep(0.58, 0.8, fbm3(ring * 3.5 + uTime * 0.07)) * exp(-max(h, 0.0) * (4.5 - 2.0 * uEnergy));
    // coroa e raios
    float corona = exp(-max(h, 0.0) * 2.6) * (0.55 + 0.6 * uListen + 0.7 * uEnergy);
    float rays = pow(noise(ring * 7.0 + uTime * 0.03), 3.0) * exp(-max(h, 0.0) * 1.2) * 0.45;
    vec3 ember = flame * vec3(1.0, 0.62, 0.38);                                       // base mais rubra
    vec3 outer = mix(ember, flame, flames) * (flames * 3.4 + tongues * 2.2 + prom * 1.8)
               + mix(flame, star, 0.5) * (corona * 0.5 + rays);
    col += outer * step(0.0, h) * smoothstep(uFlameLim, uFlameLim * 0.5777778, sr);   // some antes do limite do cálculo (4,5 → 2,6)
    // ejeção de massa coronal (alerta)
    float cz = fract(uTime * 0.35);
    float cme = exp(-abs(sr - (1.0 + cz * 3.4)) * 7.0) * (1.0 - cz) * fbm3(sv * 3.0 + uTime * 0.2);
    col += vec3(1.0, 0.28, 0.12) * cme * uAlert * 2.4;
  }
  // brilho amplo (bloom analítico) e reflexo anamórfico
  col += mix(flame, star, 0.6) * (0.035 / (dot(sv, sv) * 0.35 + 0.05)) * (0.6 + 0.4 * uEnergy + 0.3 * uListen) * (1.0 - occl);
  col += star * exp(-abs(g.y) * 140.0) * exp(-abs(g.x) * 2.2) * 0.45 * smoothstep(0.3, 0.9, uBoot);
  return col;
}
#else
// ── 3b. planeta (os JARVIS que não são o principal) ──
// Iluminado pela estrela da camada que respondeu (uTemp), fora da tela, de cima e da esquerda.
const vec3 LUZ = normalize(vec3(-0.55, 0.42, 0.72));
#if ASTRO == 1        // Marte: rochoso, ferrugem, calota polar, atmosfera fina e rosada
const float ESCALA = 0.95, INCLINACAO = -0.42, ELEVACAO = 0.22, ESPESSURA = 26.0;
const vec3 ATM = vec3(0.95, 0.5, 0.38);
#elif ASTRO == 2      // Saturno: faixas cor de areia e ouro, com anéis
const float ESCALA = 0.74, INCLINACAO = -0.38, ELEVACAO = 0.3, ESPESSURA = 22.0;
const vec3 ATM = vec3(0.95, 0.82, 0.55);
#else                 // Netuno: gelado, azul profundo, atmosfera forte
const float ESCALA = 0.95, INCLINACAO = -0.48, ELEVACAO = 0.2, ESPESSURA = 12.0;
const vec3 ATM = vec3(0.3, 0.55, 1.0);
#endif

// ruído sobre a esfera sem costura: três projeções 2D misturadas pela normal (o mapa atan/asin do sol
// deixaria uma emenda visível na longitude quando o planeta gira)
float fbmEsfera(vec3 p, float s){
  vec3 w = pow(abs(p), vec3(4.0)); w /= w.x + w.y + w.z;
  return fbm(p.yz * s) * w.x + fbm(p.zx * s + 7.3) * w.y + fbm(p.xy * s + 13.1) * w.z;
}
float fbmEsfera3(vec3 p, float s){
  vec3 w = pow(abs(p), vec3(4.0)); w /= w.x + w.y + w.z;
  return fbm3(p.yz * s) * w.x + fbm3(p.zx * s + 7.3) * w.y + fbm3(p.xy * s + 13.1) * w.z;
}

// normal da tela → coordenadas do planeta: eixo inclinado na tela (z), polo voltado para quem olha (x), rotação (y)
vec3 girar(vec3 n, float ang){
  vec3 a = vec3(rot(INCLINACAO) * n.xy, n.z);
  a.yz = rot(ELEVACAO) * a.yz;
  float c = cos(ang), s = sin(ang);
  return vec3(a.x * c + a.z * s, a.y, -a.x * s + a.z * c);
}

vec3 superficie(vec3 q){
  float lat = q.y;
#if ASTRO == 1
  float h = fbmEsfera(q, 2.2);
  vec3 c = mix(vec3(0.42, 0.17, 0.08), vec3(0.8, 0.42, 0.2), smoothstep(0.35, 0.65, h));
  c = mix(c, vec3(0.24, 0.11, 0.07), smoothstep(0.56, 0.74, fbmEsfera3(q + 9.0, 3.0)) * 0.65);   // regiões escuras
  float cr = fbmEsfera3(q + 3.0, 14.0);                                                          // crateras discretas
  c *= 0.88 + 0.24 * fbmEsfera3(q + 4.0, 6.0) - 0.16 * smoothstep(0.62, 0.7, cr) + 0.06 * smoothstep(0.56, 0.6, cr);
  c = mix(c, vec3(0.96, 0.94, 0.9), smoothstep(0.86, 0.9, abs(lat) + (h - 0.5) * 0.12));         // calota polar
  return c;
#elif ASTRO == 2
  float turb = fbmEsfera3(q, 3.0);
  float bands = 0.5 + 0.5 * sin(lat * 26.0 + (turb - 0.5) * 2.2) * (0.6 + 0.4 * sin(lat * 7.0));
  vec3 c = mix(vec3(0.7, 0.55, 0.34), vec3(0.96, 0.87, 0.64), bands);
  c *= 0.92 + 0.16 * fbmEsfera3(q + 5.0, 8.0);
  return mix(c, vec3(0.6, 0.55, 0.47), smoothstep(0.78, 0.97, abs(lat)));                         // polos mais frios
#else
  float turb = fbmEsfera3(q, 2.5);
  float bands = 0.5 + 0.5 * sin(lat * 8.0 + (turb - 0.5) * 2.4);
  vec3 c = mix(vec3(0.04, 0.13, 0.48), vec3(0.16, 0.36, 0.84), bands * 0.55 + turb * 0.45);
  vec3 d = q - normalize(vec3(0.62, -0.38, 0.69));                                                // Grande Mancha Escura
  d.y *= 1.8;
  c = mix(c, vec3(0.02, 0.05, 0.22), exp(-dot(d, d) * 45.0) * 0.85);
  vec3 e = q - normalize(vec3(0.66, -0.5, 0.56));                                                 // nuvem clara ao lado dela
  e.y *= 2.5;
  float cirros = smoothstep(0.66, 0.82, fbmEsfera3(q + vec3(uTime * 0.008, 0.0, 21.0), 6.0))
               * (0.35 + 0.65 * smoothstep(0.2, 0.9, sin(lat * 9.0 + 1.0)));
  return mix(c, vec3(0.88, 0.93, 1.0), clamp(cirros * 0.8 + exp(-dot(e, e) * 160.0) * 0.9, 0.0, 1.0));
#endif
}

vec3 planetColor(vec2 g, out float occl){
  occl = 0.0;
  float R = uSunR * ESCALA * smoothstep(0.25, 0.85, uBoot) * (1.0 + 0.015 * uEnergy);
  vec2 sv = g / max(R, 1e-4);
  float sr = length(sv);
  vec3 luz = pow(blackbody(uTemp), vec3(1.4)) * (1.15 + 0.25 * uGiant);
  float brilho = 0.6 + 0.7 * uListen + 0.6 * uEnergy;            // a atmosfera acende ouvindo e falando
  vec3 col = vec3(0.0);

  if (sr < 1.0){
    float z = sqrt(1.0 - sr * sr);
    vec3 n = vec3(sv, z);
    vec3 q = girar(n, uSpin * 2.0);                                // uSpin já acumula: pensando, gira mais rápido
    float dl = dot(n, LUZ);
    col = superficie(q) * luz * (0.025 + 1.25 * smoothstep(-0.15, 1.0, dl));
    col += ATM * luz * pow(1.0 - z, 2.5) * smoothstep(-0.3, 0.4, dl) * brilho * 0.9;
    occl = smoothstep(1.0, 0.985, sr);
  }
  float h = sr - 1.0;
  if (h > 0.0 && h < 1.5){
    vec2 dir = sv / sr;
    float lado = 0.25 + 0.75 * smoothstep(-0.6, 0.8, dot(dir, normalize(LUZ.xy)));
    col += ATM * luz * exp(-h * ESPESSURA) * 0.55 * lado * brilho;
    // aurora vermelha no alerta
    col += vec3(1.0, 0.22, 0.12) * exp(-h * 7.0) * uAlert * (0.55 + 0.45 * sin(uTime * 3.0 + atan(sv.y, sv.x) * 6.0)) * 1.2;
  }
  col += ATM * luz * (0.012 / (dot(sv, sv) * 0.4 + 0.05)) * (0.5 + 0.5 * brilho) * (1.0 - occl);   // halo fraco

#if ASTRO == 2
  // anéis no plano inclinado: a metade de cima fica atrás do planeta, a de baixo passa na frente
  vec2 rq = rot(INCLINACAO) * sv;
  float rr = length(vec2(rq.x, rq.y / 0.3));
  float fino = noise(vec2(rr * 42.0, 3.7));
  float a = smoothstep(1.3, 1.34, rr) * smoothstep(2.3, 2.22, rr)
          * (0.45 + 0.55 * fino) * (rr < 1.62 ? 0.5 : 1.0)
          * (1.0 - 0.9 * smoothstep(0.045, 0.01, abs(rr - 1.92)))   // divisão de Cassini
          * 0.92 * smoothstep(0.25, 0.85, uBoot);
  if (a > 0.0 && !(rq.y > 0.0 && sr < 1.0)){
    col = mix(col, vec3(0.86, 0.77, 0.6) * luz * (0.55 + 0.25 * fino) * (0.85 + 0.3 * uListen), a);
    occl = max(occl, a);
  }
#endif
  return col;
}
#endif

// ── 4. onda de voz: linha luminosa que atravessa o sol na horizontal enquanto ele fala ──
// amplitude sintética (a síntese de voz do navegador não entrega o áudio); só uma faixa estreita é calculada
vec3 voiceWave(vec2 g){
  float ax = abs(g.x);
  const float span = 1.05;
  if (uWave < 0.002 || ax > span || abs(g.y) > 0.1) return vec3(0.0);
  float env = smoothstep(span, span * 0.6, ax) * (0.35 + 0.65 * exp(-ax * ax * 4.0));
  float y = uWave * 0.06 * env
          * (0.6 * sin(g.x * 23.0 - uTime * 9.0) + 0.4 * sin(g.x * 41.0 + uTime * 13.0))
          * (0.55 + 0.45 * sin(g.x * 6.0 + uTime * 2.3));
  float d = abs(g.y - y);
  float core = exp(-d * d * 60000.0);
  float glow = exp(-d * 220.0) * 0.45;
  return mix(vec3(1.0, 0.5, 0.15), vec3(1.0, 0.95, 0.85), core) * (core * 1.3 + glow) * uWave;
}

vec3 aces(vec3 x){ return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }

void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
  vec2 g = uv - uSun;

  vec3 col = deepField(uv) * smoothstep(0.0, 0.6, uBoot);
  col += galaxy(g);
  float occl;
#if ASTRO == 0
  vec3 astro = sunColor(g, occl);
#else
  vec3 astro = planetColor(g, occl);
#endif
  col = mix(col, astro, occl) + astro * (1.0 - occl);
  col += voiceWave(g);

#if ASTRO == 0
  // clarão da ignição (só a estrela acende; o planeta só aparece)
  col += vec3(1.0, 0.9, 0.75) * exp(-length(g) * 7.0) * smoothstep(0.0, 0.12, uBoot) * smoothstep(0.5, 0.12, uBoot) * 3.0;
#endif

  col = aces(col * 1.05);
  vec2 vq = gl_FragCoord.xy / uRes - 0.5;
  col *= 1.0 - 0.55 * dot(vq, vq);                  // vinheta
  col += (hash(gl_FragCoord.xy + fract(uTime) * 91.0) - 0.5) * 0.018;   // granulação de filme
  o = vec4(col, 1.0);
}`
