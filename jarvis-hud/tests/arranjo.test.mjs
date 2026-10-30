// Arranjo dos painéis de vidro em volta do sol. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { MARGEM, SOBRE, arranjoRepouso, cruza, holoAtivo, zonaConversa } from '../src/holo/arranjo.js'
import { SOL, solPx } from '../src/cosmos/sol.js'

const TELAS = [[1920, 945], [1440, 789], [2560, 1305], [1280, 680], [1680, 920]]
const SOIS = [SOL, { ...SOL, r: 0.2 }]

test('o vidro só liga em telas largas; o resto fica com o layout plano', () => {
  assert.equal(holoAtivo(1920, 945), true)
  assert.equal(holoAtivo(1280, 680), true)
  assert.equal(holoAtivo(1279, 800), false)
  assert.equal(holoAtivo(1400, 1050), false) // 4:3
  assert.equal(holoAtivo(390, 844), false)
})

for (const [W, H] of TELAS) {
  for (const sol of SOIS) {
    const nome = `${W}x${H}, sol ${sol.r}`
    const a = arranjoRepouso({ W, H, sol })
    const lista = Object.entries(a).filter(([, r]) => r)

    test(`${nome}: todo painel cabe na tela`, () => {
      for (const [id, r] of lista) {
        assert.ok(r.x >= MARGEM - 1 && r.y >= 0 && r.x + r.w <= W - MARGEM + 1 && r.y + r.h <= H - MARGEM + 1, `${id} ${JSON.stringify(r)}`)
        assert.ok(r.w >= 150 && r.h >= 100, `${id} pequeno demais ${JSON.stringify(r)}`)
      }
    })

    test(`${nome}: nenhum painel cobre outro nem a conversa`, () => {
      const conv = zonaConversa(W, H)
      const zona = { x: conv.x0, y: conv.y0, w: conv.x1 - conv.x0, h: H - conv.y0 }
      for (const [i, [id, r]] of lista.entries()) {
        assert.ok(!cruza(r, zona), `${id} cobre a conversa`)
        for (const [id2, r2] of lista.slice(i + 1)) assert.ok(!cruza(r, r2), `${id} cruza ${id2}`)
      }
    })

    test(`${nome}: CPU e modelos entram só ${SOBRE * 100}% do raio no sol; os outros ficam fora`, () => {
      const { cx, cy, rp } = solPx(sol, W, H)
      assert.ok(Math.abs(a.cpu.x + a.cpu.w - (cx - rp + SOBRE * rp)) <= 1)
      assert.ok(Math.abs(a.modelos.x - (cx + rp - SOBRE * rp)) <= 1)
      const disco = { x: cx - rp, y: cy - rp, w: 2 * rp, h: 2 * rp }
      for (const id of ['custo', 'neural', 'turno', 'deco']) if (a[id]) assert.ok(!cruza(a[id], disco), `${id} sobre o sol`)
    })
  }
}

test('1920x945: os seis painéis aparecem', () => {
  const a = arranjoRepouso({ W: 1920, H: 945, sol: { ...SOL, r: 0.2 } })
  assert.deepEqual(Object.keys(a).filter(k => a[k]).sort(), ['cpu', 'custo', 'deco', 'modelos', 'neural', 'turno'])
})

test('sol grande: as chamas continuam calculadas na mesma área absoluta do sol de 0,105', async () => {
  const { CHAMAS_AREA, limiteChamas } = await import('../src/cosmos/sol.js')
  assert.equal(limiteChamas(0.105), 4.5)
  assert.equal(limiteChamas(0.085), 4.5) // sol menor não passa de 4,5 raios
  assert.ok(Math.abs(limiteChamas(0.2) * 0.2 - CHAMAS_AREA) < 1e-12)
})

for (const [W, H] of TELAS) {
  test(`${W}x${H}: modo palco cabe na tela sem cobrir a conversa, o sol ou outro bloco`, async () => {
    const { arranjoPalco, trilho, arranjoRepouso: rep } = await import('../src/holo/arranjo.js')
    const sol = { ...SOL, r: 0.2 }
    const a = arranjoPalco({ W, H, sol })
    const conv = zonaConversa(W, H)
    const zona = { x: conv.x0, y: conv.y0, w: conv.x1 - conv.x0, h: H - conv.y0 }
    const { cx, cy, rp } = solPx(a.sol, W, H)
    const disco = { x: cx - rp, y: cy - rp, w: 2 * rp, h: 2 * rp }
    assert.ok(disco.x >= 0 && disco.y >= 0, 'sol fora da tela')
    const lista = ['cpu', 'custo', 'modelo', 'palco', 'detalhes'].map(id => [id, a[id]])
    for (const [i, [id, r]] of lista.entries()) {
      assert.ok(r.x >= MARGEM - 1 && r.y >= 0 && r.x + r.w <= W - MARGEM + 1 && r.y + r.h <= H - MARGEM + 1, `${id} ${JSON.stringify(r)}`)
      assert.ok(r.w >= 200 && r.h >= 80, `${id} pequeno demais ${JSON.stringify(r)}`)
      assert.ok(!cruza(r, zona), `${id} cobre a conversa`)
      assert.ok(!cruza(r, disco), `${id} cobre o sol`)
      for (const [id2, r2] of lista.slice(i + 1)) assert.ok(!cruza(r, r2), `${id} cruza ${id2}`)
    }
    // trilho: no palco fica dentro do palco; no repouso, entre CPU e modelos, acima do sol
    const tp = trilho({ W, palco: a.palco })
    assert.ok(tp.x >= a.palco.x && tp.x + tp.w <= a.palco.x + a.palco.w && tp.y >= a.palco.y)
    const r0 = rep({ W, H, sol })
    const tr = trilho({ W })
    for (const id of ['cpu', 'modelos']) assert.ok(!cruza(tr, r0[id]), `trilho cruza ${id} no repouso`)
    const s0 = solPx(sol, W, H)
    assert.ok(tr.y + tr.h <= s0.cy - s0.rp, 'trilho sobre o sol no repouso')
  })
}
