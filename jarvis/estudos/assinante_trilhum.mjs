// Lê, só para leitura, o registro do aluno no Firestore do Trilhum (assinantes/{uid}): plano, WhatsApp e consentimento.
// As regras do Firestore negam o acesso direto; só o Admin SDK (conta de serviço) lê, como a função "api" do Trilhum.
// Usa o firebase-admin já instalado em Trilha\functions\node_modules, sem instalar nada no JARVIS.
//
//     node assinante_trilhum.mjs <node_modules com o firebase-admin>   < {"uid": "...", "projeto": "..."}
//
// Credencial: GOOGLE_APPLICATION_CREDENTIALS (arquivo da conta de serviço, fora do Git) ou, no modo teste,
// FIRESTORE_EMULATOR_HOST (emulador do Firebase, projeto demo-trilhum). Nada é gravado.
// Saída (stdout): {"existe", "plano", "whatsapp", "whatsappConsentimento"}. O e-mail e o resto do registro não saem daqui.
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {join} from 'node:path';

const [modulos] = process.argv.slice(2);
if (!modulos) {
  process.stderr.write('uso: node assinante_trilhum.mjs <node_modules>  (uid e projeto pela entrada)\n');
  process.exit(2);
}
const {uid, projeto} = JSON.parse(readFileSync(0, 'utf8') || '{}');
if (!/^[A-Za-z0-9]{1,128}$/.test(uid || '') || !/^[a-z0-9-]{4,30}$/.test(projeto || '')) {
  process.stderr.write('uid ou projeto inválido\n');
  process.exit(2);
}
const exigir = createRequire(join(modulos, 'firebase-admin.cjs'));
const {initializeApp, applicationDefault} = exigir('firebase-admin/app');
const {getFirestore} = exigir('firebase-admin/firestore');

const app = process.env.FIRESTORE_EMULATOR_HOST
  ? initializeApp({projectId: projeto})
  : initializeApp({projectId: projeto, credential: applicationDefault()});
const texto = (v) => (v == null ? null : v.toDate ? v.toDate().toISOString() : String(v));
try {
  const s = await getFirestore(app).collection('assinantes').doc(uid).get();
  const d = s.exists ? s.data() : {};
  process.stdout.write(JSON.stringify({existe: s.exists, plano: texto(d.plano), whatsapp: texto(d.whatsapp),
    whatsappConsentimento: texto(d.whatsappConsentimento)}));
} catch (e) {
  process.stderr.write('o Firestore recusou a leitura: ' + String(e && (e.code || e.message) || e).slice(0, 200) + '\n');
  process.exitCode = 1;
} finally {
  await app.delete();
}
