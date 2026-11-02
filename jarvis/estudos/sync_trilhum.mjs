// Lê, só para leitura, um plano da sincronização do Trilhum no Firestore (sync/{uid}/planos/{plano}), como a função
// "api" do Trilhum faz em lerSync. As regras do Firestore negam o acesso direto; só o Admin SDK (conta de serviço) lê.
// Usa o firebase-admin já instalado em Trilha\functions\node_modules, sem instalar nada no JARVIS.
//
//     node sync_trilhum.mjs <node_modules com o firebase-admin>   < {"uid": "...", "projeto": "...", "plano": "..."}
//
// Credencial: GOOGLE_APPLICATION_CREDENTIALS (arquivo da conta de serviço, fora do Git) ou, no modo teste,
// FIRESTORE_EMULATOR_HOST (emulador do Firebase, projeto demo-trilhum). Nada é gravado.
// Saída (stdout): {"existe", "json", "em"}; json é a string que o app gravou ({app, plano, ts, data, em}).
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {join} from 'node:path';

const [modulos] = process.argv.slice(2);
if (!modulos) {
  process.stderr.write('uso: node sync_trilhum.mjs <node_modules>  (uid, projeto e plano pela entrada)\n');
  process.exit(2);
}
const {uid, projeto, plano} = JSON.parse(readFileSync(0, 'utf8') || '{}');
if (!/^[A-Za-z0-9]{1,128}$/.test(uid || '') || !/^[a-z0-9-]{4,30}$/.test(projeto || '')
    || !/^(?!\.{1,2}$)[A-Za-z0-9_.-]{1,80}$/.test(plano || '')) {
  process.stderr.write('uid, projeto ou plano inválido\n');
  process.exit(2);
}
const exigir = createRequire(join(modulos, 'firebase-admin.cjs'));
const {initializeApp, applicationDefault} = exigir('firebase-admin/app');
const {getFirestore} = exigir('firebase-admin/firestore');

const app = process.env.FIRESTORE_EMULATOR_HOST
  ? initializeApp({projectId: projeto})
  : initializeApp({projectId: projeto, credential: applicationDefault()});
try {
  const s = await getFirestore(app).collection('sync').doc(uid).collection('planos').doc(plano).get();
  const d = s.exists ? s.data() : {};
  process.stdout.write(JSON.stringify({existe: s.exists, json: typeof d.json === 'string' ? d.json : null,
    em: d.em == null ? null : String(d.em)}));
} catch (e) {
  process.stderr.write('o Firestore recusou a leitura: ' + String(e && (e.code || e.message) || e).slice(0, 200) + '\n');
  process.exitCode = 1;
} finally {
  await app.delete();
}
