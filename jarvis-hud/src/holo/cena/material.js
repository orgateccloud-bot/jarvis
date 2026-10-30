// Material holográfico único do palco: sem luzes e sem sombras; borda Fresnel, linhas de varredura,
// mistura aditiva e entrada por varredura de baixo para cima (uReveal 0 → 1). Funciona com InstancedMesh.
import { AdditiveBlending, ShaderMaterial } from 'three'

const VERT = /* glsl */ `
varying vec3 vNormal;
varying vec3 vView;
varying vec3 vCor;
varying float vY;
void main() {
  vec4 local = vec4(position, 1.0);
  vec3 n = normal;
  #ifdef USE_INSTANCING
    local = instanceMatrix * local;
    n = mat3(instanceMatrix) * n;
  #endif
  vec4 world = modelMatrix * local;
  vY = world.y;
  vec4 mv = viewMatrix * world;
  vView = mv.xyz;
  vNormal = normalize(mat3(viewMatrix) * mat3(modelMatrix) * n);
  #ifdef USE_INSTANCING_COLOR
    vCor = instanceColor;
  #else
    vCor = vec3(0.45, 0.78, 1.0);
  #endif
  gl_Position = projectionMatrix * mv;
}`

const FRAG = /* glsl */ `
uniform float uTempo;
uniform float uReveal;
uniform float uAltura;
varying vec3 vNormal;
varying vec3 vView;
varying vec3 vCor;
varying float vY;
void main() {
  float corte = mix(-uAltura, uAltura, uReveal);
  if (vY > corte) discard;
  float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(-vView))), 2.0);
  float scan = 0.72 + 0.28 * sin(vY * 38.0 - uTempo * 4.0);
  float frente = smoothstep(0.3, 0.0, corte - vY) * (1.0 - step(0.999, uReveal));
  vec3 c = vCor * (0.5 + 1.4 * fres) * scan + vec3(1.0) * frente;
  gl_FragColor = vec4(c, 0.35 + 0.65 * fres);
}`

/** altura: meia altura da cena em unidades do mundo, para a varredura cobrir tudo */
export function materialHolo(altura = 4) {
  return new ShaderMaterial({
    uniforms: { uTempo: { value: 0 }, uReveal: { value: 0 }, uAltura: { value: altura } },
    vertexShader: VERT,
    fragmentShader: FRAG,
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
  })
}
