// node --test maestro-sauna/apps/rito/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const E = require('./engine.js');

const DEMO = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'demo.rito.json'), 'utf8'));
const T0 = Date.UTC(2026, 10, 19, 17, 0, 0);
const at = (sec) => T0 + sec * 1000;

function rito(moments, extra) { return Object.assign({ v: 1, kind: 'sauna', date: '2026-11-19', title: 'Prova', moments }, extra || {}); }
// lead_s: 0 = senza passaggio, per provare il resto; i passaggi hanno i loro test più sotto
const HEAT = { id: 'calore', name: 'Calore', type: 'heat', target_s: 600, max_s: 780, lead_s: 0 };
const AIR = { id: 'aria', name: 'Aria', type: 'air', end: 'time', target_s: 120, lead_s: 0 };
const COLD = { id: 'acqua', name: 'Acqua', type: 'cold', optional: true, target_s: 60, max_s: 180, lead_s: 0 };
const REST = { id: 'riposo', name: 'Riposo', type: 'rest', min_s: 480, target_s: 600, lead_s: 0 };
const lead = (m, sec) => Object.assign({}, m, sec == null ? { lead_s: undefined } : { lead_s: sec });

test('la partitura di esempio è valida e si legge prima di cominciare', () => {
  assert.deepEqual(E.validate(DEMO), []);
  const p = E.planned(DEMO);
  assert.equal(p.rounds, 2);
  assert.equal(p.heat_s, 1200);
  assert.equal(p.moments.length, 9);
});

test('partiture sbagliate: dice cosa non va', () => {
  const bad = (m, re) => assert.match(E.validate(rito([m])).join('; '), re);
  bad({ id: 'x', name: 'X', type: 'heat', target_s: 600 }, /max_s/);                 // il caldo vuole un limite
  bad({ id: 'x', name: 'X', type: 'cold' }, /max_s/);
  bad({ id: 'x', name: 'X', type: 'air', end: 'time' }, /target_s/);
  bad({ id: 'X y', name: 'X', type: 'rest' }, /slug/);
  bad({ id: 'x', name: 'X', type: 'sauna' }, /type/);
  bad({ id: 'x', name: 'X', type: 'rest', min_s: 900, target_s: 600 }, /min_s oltre/);
  bad({ id: 'x', name: 'X', type: 'heat', target_s: 900, max_s: 600 }, /target_s oltre/);
  bad({ id: 'x', name: 'X', type: 'rest', sound: 'rock' }, /sound/);
  bad({ id: 'x', name: 'X', type: 'heat', max_s: 600, cues: [{ at_s: 700, sound: 'gong' }] }, /oltre la fine/);
  bad({ id: 'x', name: 'X', type: 'rest', cues: [{ at_s: 10 }] }, /sound, say o text/);
  bad({ id: 'x', name: 'X', type: 'heat', end: 'time', target_s: 600, max_s: 780 }, /solo con un tocco/);
  bad({ id: 'x', name: 'X', type: 'cold', end: 'time', target_s: 60, max_s: 90 }, /solo con un tocco/);
  bad({ id: 'x', name: 'X', type: 'rest', optional: true }, /non si salta/);
  bad({ id: 'x', name: 'X', type: 'rest', breath: { in_s: -5, out_s: 6 } }, /breath/);
  bad({ id: 'x', name: 'X', type: 'rest', temp_c: 65 }, /solo per il calore/);
  bad({ id: 'x', name: 'X', type: 'heat', max_s: 600, temp_c: '95' }, /temp_c/);
  bad({ id: 'x', name: 'X', type: 'rest', sound: 'brace' }, /brace/);
  bad({ id: true, name: 'X', type: 'rest' }, /slug/);
  bad({ id: 'x', name: ['X'], type: 'rest' }, /name/);
  bad({ id: 'x', name: 'X', type: 'rest', lead_s: '30' }, /lead_s/);
  bad({ id: 'x', name: 'X', type: 'rest', cues: [{ at_s: null, sound: 'gong' }] }, /at_s/);
  assert.match(E.validate(rito([HEAT, Object.assign({}, HEAT)])).join(), /ripetuto/);
  assert.match(E.validate(rito([REST], { closing: [{ id: 'a', q: '?', options: ['uno'] }] })).join(), /opzioni/);
  assert.deepEqual(E.validate({ v: 1, moments: [] }), ['moments mancante o vuoto']);
});

test('il rito scorre: tocchi, passaggi a tempo, fine', () => {
  const s = E.createSession(rito([HEAT, AIR, REST]));
  assert.equal(E.view(s, at(0)).phase, 'intro');
  assert.equal(E.start(s, at(0)), true);
  assert.equal(E.view(s, at(1)).m.id, 'calore');
  assert.equal(E.tap(s, at(0.2), 0), 'guard');                 // doppio tocco
  assert.equal(E.tap(s, at(540), 1), 'stale');                 // la pagina mostrava altro
  assert.equal(E.tap(s, at(540), 0), 'ok');                    // esco a 9 minuti: decide il corpo
  assert.equal(E.view(s, at(541)).m.id, 'aria');
  assert.deepEqual(E.tick(s, at(600)), []);                    // l'aria non è finita
  const h = E.tick(s, at(661));                                // 120 s dopo l'uscita: passa da sola
  assert.deepEqual(h.map((x) => x.kind), ['enter']);
  assert.equal(E.view(s, at(661)).m.id, 'riposo');
  assert.equal(s.events[s.events.length - 2].t, at(660));      // registrato all'istante giusto
  assert.equal(E.tap(s, at(1270), 2), 'ok');                   // oltre il minimo
  assert.equal(E.view(s, at(1271)).phase, 'closing');
  const sum = E.summary(s);
  assert.equal(sum.status, 'end');
  assert.deepEqual(sum.moments.map((m) => [m.id, m.actual_s, m.ended]),
    [['calore', 540, 'tap'], ['aria', 120, 'auto'], ['riposo', 610, 'tap']]);
  assert.equal(sum.heat_s, 540);
  assert.equal(sum.rounds, 1);
});

test('il riposo non si salta con un tocco solo; dal caldo si esce subito', () => {
  const s = E.createSession(rito([Object.assign({}, HEAT, { min_s: 480 }), REST]));
  E.start(s, at(0));
  assert.equal(E.tap(s, at(60), 0), 'ok');                     // caldo: nessuna conferma, anche col minimo
  assert.equal(E.view(s, at(120)).hold, true);
  assert.equal(E.tap(s, at(120), 1), 'early');
  assert.equal(E.view(s, at(121)).m.id, 'riposo');
  assert.equal(E.tap(s, at(125), 1, true), 'ok');              // secondo tocco: ha deciso
  assert.equal(E.summary(s).moments[1].actual_s, 65);
});

test('suoni dovuti: richiami, traguardo, limite che richiama finché non si esce', () => {
  const m = Object.assign({}, HEAT, { cues: [{ at_s: 300, sound: 'vapore' }, { at_s: 480, sound: 'ciotola', text: 'Siediti' }] });
  const s = E.createSession(rito([m, REST]));
  E.start(s, at(0));
  assert.deepEqual(E.tick(s, at(299)), []);
  assert.deepEqual(E.tick(s, at(301)).map((x) => [x.kind, x.cue.sound, x.late]), [['cue', 'vapore', false]]);
  assert.deepEqual(E.tick(s, at(302)), []);                    // una volta sola
  assert.deepEqual(E.tick(s, at(481)).map((x) => x.kind), ['cue']);
  assert.deepEqual(E.tick(s, at(600)).map((x) => x.kind), ['target']);
  assert.equal(E.view(s, at(601)).over, true);
  assert.deepEqual(E.tick(s, at(780)).map((x) => [x.kind, x.n]), [['max', 0]]);
  assert.deepEqual(E.tick(s, at(790)), []);
  assert.deepEqual(E.tick(s, at(811)).map((x) => [x.kind, x.n]), [['max', 1]]);   // torna ogni 30 s
  assert.equal(E.view(s, at(811)).over_max, true);
  assert.equal(E.tap(s, at(815), 0), 'ok');
  assert.deepEqual(E.tick(s, at(900)), []);
});

test('pagina sospesa: i suoni vecchi non si suonano, il richiamo sì; i passaggi restano giusti', () => {
  const s = E.createSession(rito([Object.assign({}, HEAT, { cues: [{ at_s: 300, sound: 'vapore' }] }), AIR, REST]));
  E.start(s, at(0));
  const h = E.tick(s, at(900));                                // rientra dopo 15 minuti di buio
  assert.deepEqual(h.map((x) => [x.kind, x.late]), [['cue', true], ['target', true], ['max', false]]);
  E.tap(s, at(905), 0);
  const h2 = E.tick(s, at(2000));                              // aria passata da un pezzo
  assert.deepEqual(h2.map((x) => [x.kind, x.late]), [['enter', true], ['target', true]]);
  assert.equal(s.events.find((e) => e.e === 'auto').f, 1);
  assert.equal(E.summary(s).moments[1].actual_s, 120);
});

test('il freddo si può saltare; un momento non facoltativo no', () => {
  const s = E.createSession(rito([HEAT, COLD, REST]));
  E.start(s, at(0));
  assert.equal(E.skip(s, at(10), 0), false);
  E.tap(s, at(600), 0);
  assert.equal(E.view(s, at(601)).can_skip, true);
  assert.equal(E.skip(s, at(605), 1), 'ok');
  assert.equal(E.view(s, at(606)).m.id, 'riposo');
  const m = E.summary(s).moments[1];
  assert.deepEqual([m.actual_s, m.ended], [0, 'skip']);
  assert.equal(E.summary(s).cold_s, 0);
});

test('tocco per sbaglio: si torna indietro entro 15 secondi, il tempo non si perde', () => {
  const s = E.createSession(rito([HEAT, REST]));
  E.start(s, at(0));
  E.tap(s, at(300), 0);                                        // uscito? no: dito bagnato
  assert.equal(E.canUndo(s, at(305)), true);
  assert.equal(E.undo(s, at(305)), true);
  assert.equal(E.view(s, at(306)).m.id, 'calore');
  assert.equal(Math.round(E.view(s, at(306)).elapsed_s), 306); // il calore è continuato
  E.tap(s, at(600), 0);
  assert.equal(E.undo(s, at(620)), false);                     // troppo tardi
  assert.equal(E.summary(s).moments[0].actual_s, 600);
  assert.equal(E.summary(s).moments.length, 2);
});

test('si torna indietro anche dall\'ultimo tocco del rito', () => {
  const s = E.createSession(rito([REST]));
  E.start(s, at(0));
  E.tap(s, at(500), 0);
  assert.equal(E.view(s, at(501)).phase, 'closing');
  assert.equal(E.undo(s, at(505)), true);
  assert.equal(E.view(s, at(506)).phase, 'run');
  E.tap(s, at(700), 0);
  assert.equal(E.summary(s).moments[0].actual_s, 700);
});

test('pausa: il tempo del riposo si ferma; interrompere chiude il rito', () => {
  const s = E.createSession(rito([REST, HEAT]));
  E.start(s, at(0));
  assert.equal(E.pause(s, at(100)), true);
  assert.deepEqual(E.tick(s, at(2000)), []);
  assert.equal(Math.round(E.view(s, at(2000)).elapsed_s), 100);
  assert.equal(E.tap(s, at(2000), 0), false);
  E.resume(s, at(400));
  assert.equal(Math.round(E.view(s, at(500)).elapsed_s), 200);
  E.tap(s, at(1100), 0);
  assert.equal(E.summary(s).moments[0].actual_s, 800);
  assert.equal(E.stop(s, at(1200)), true);
  const sum = E.summary(s);
  assert.deepEqual([sum.status, sum.moments[1].ended, sum.moments[1].actual_s], ['stop', 'stop', 100]);
  assert.equal(E.undo(s, at(1201)), false);
});

test('nel caldo e nel freddo non c\'è pausa: il tempo del corpo non si ferma', () => {
  const s = E.createSession(rito([HEAT, COLD, REST]));
  E.start(s, at(0));
  assert.equal(E.view(s, at(50)).can_pause, false);
  assert.equal(E.pause(s, at(100)), false);
  assert.deepEqual(E.tick(s, at(781)).map((x) => x.kind), ['target', 'max']);   // il richiamo arriva comunque
  E.tap(s, at(800), 0);
  assert.equal(E.pause(s, at(830)), false);                    // nemmeno nell'acqua
  E.tap(s, at(860), 1);
  assert.equal(E.view(s, at(900)).can_pause, true);            // nel riposo sì
});

test('lo stato si ricostruisce dal log', () => {
  const r = rito([HEAT, AIR, COLD, REST]);
  const s = E.createSession(r);
  E.start(s, at(0)); E.tap(s, at(600), 0); E.tick(s, at(730)); E.skip(s, at(735), 2);
  E.pause(s, at(800)); E.resume(s, at(900)); E.tap(s, at(1100), 3); E.undo(s, at(1105));
  const s2 = E.replay(r, s.events);
  assert.deepEqual(E.summary(s2), E.summary(s));
  assert.equal(s2.cur, s.cur);
  assert.equal(s2.mStart, s.mStart);
});

test('riaperta dopo molto: il riposo è in pausa da quando era stato visto; il calore è continuato', () => {
  const s = E.createSession(rito([REST, HEAT]));
  E.start(s, at(0));
  assert.equal(E.reopen(s, at(300), at(600)), false);          // cinque minuti: il tempo è continuato
  assert.equal(E.reopen(s, at(300), at(300 + 3600)), true);
  assert.equal(E.view(s, at(4000)).paused, true);
  assert.equal(Math.round(E.view(s, at(4000)).elapsed_s), 300);
  const h = E.createSession(rito([HEAT, REST]));
  E.start(h, at(0));
  assert.equal(E.reopen(h, at(200), at(1700)), false);         // pagina morta durante il calore: niente pausa
  assert.equal(E.view(h, at(1700)).over_max, true);
  assert.ok(E.tick(h, at(1700)).some((x) => x.kind === 'max' && !x.late));   // e il richiamo suona subito
  E.tap(h, at(1710), 0);
  assert.equal(E.summary(h).moments[0].actual_s, 1710);        // il calore registrato è quello vero
});

test('il log che torna: andata, ritorno, e sta nei limiti di sendData', () => {
  const s = E.createSession(DEMO);
  E.start(s, at(0));
  let t = 0;
  for (let k = 0; k < 60 && !s.finished; k++) {
    t += 700;
    E.tick(s, at(t));
    if (!s.finished && E.moment(s).end === 'tap') E.tap(s, at(t + 2), s.cur, true);
  }
  assert.equal(s.status, 'end');
  const str = E.encodeLog(s, { corpo: '🌊 Sciolto', testa: '🌙 Quieta' }, 'bene');
  assert.ok(new TextEncoder().encode(str).length <= 4096);
  const d = E.decodeLog(str);
  assert.equal(d.status, 'end');
  assert.equal(d.demo, true);
  assert.equal(d.answers.corpo, '🌊 Sciolto');
  assert.equal(d.moments.length, 9);
  assert.equal(d.events.length, s.events.length);
  assert.deepEqual(d.events.map((e) => e.e), s.events.map((e) => e.e));
  const small = E.encodeLog(s, {}, 'x'.repeat(280), 700);
  assert.ok(new TextEncoder().encode(small).length <= 700);
  assert.throws(() => E.decodeLog('{"v":1}'), /rito/);
});

test('la partitura viaggia nel fragment', async () => {
  const frag = E.encodeRito(DEMO);
  assert.match(frag, /^r=[A-Za-z0-9_-]+$/);
  assert.deepEqual(await E.parseFragment('#' + frag), DEMO);
  assert.deepEqual(await E.parseFragment('#tgWebAppData=x&' + frag), DEMO);
  assert.equal(await E.parseFragment('#niente'), null);
  const zlib = require('node:zlib');
  const z = 'z=' + E.b64urlEncode(zlib.deflateRawSync(Buffer.from(JSON.stringify(DEMO))));
  assert.deepEqual(await E.parseFragment('#' + z), DEMO);
  assert.notEqual(E.ritoId(DEMO), E.ritoId(Object.assign({}, DEMO, { title: 'Altro' })));
});

test('il passaggio: fra un momento e l\'altro servono secondi, e il tempo non corre', () => {
  const s = E.createSession(rito([HEAT, lead(COLD, 30), lead(REST, 60)]));
  E.start(s, at(0));
  assert.equal(E.view(s, at(1)).lead, false);                  // il primo momento comincia subito
  E.tap(s, at(600), 0);                                        // uscito dal calore: ora va all'acqua
  const v = E.view(s, at(610));
  assert.deepEqual([v.m.id, v.lead, Math.round(v.lead_remain_s), v.label, Math.round(v.elapsed_s)], ['acqua', true, 20, 'Ci sono', 0]);
  assert.deepEqual(E.tick(s, at(620)), []);                    // nel passaggio niente suona
  assert.deepEqual(E.tick(s, at(631)).map((x) => [x.kind, x.late]), [['begin', false]]);   // ora comincia
  assert.equal(Math.round(E.view(s, at(650)).elapsed_s), 20);
  assert.deepEqual(E.tick(s, at(690)).map((x) => x.kind), ['target']);            // 60 s dall'inizio vero
  E.tap(s, at(700), 1);
  assert.equal(E.summary(s).moments[1].actual_s, 70);          // il passaggio non è tempo in acqua
  assert.equal(E.view(s, at(701)).lead, true);
});

test('«Ci sono»: un tocco nel passaggio fa cominciare il momento adesso', () => {
  const s = E.createSession(rito([HEAT, lead(REST, 60)]));
  E.start(s, at(0));
  E.tap(s, at(600), 0);
  assert.equal(E.tap(s, at(620), 1), 'begin');                 // già sdraiato dopo 20 secondi
  assert.equal(E.view(s, at(621)).lead, false);
  assert.deepEqual(E.tick(s, at(700)), []);                    // l'inizio non risuona
  assert.equal(E.tap(s, at(800), 1), 'early');                 // e il minimo vale dall'inizio vero
  E.tap(s, at(1200), 1);
  assert.equal(E.summary(s).moments[1].actual_s, 580);
  const s2 = E.replay(s.rito, s.events);
  assert.deepEqual(E.summary(s2), E.summary(s));
});

test('passaggi: momenti a tempo, salti, pause e valori di tipo', () => {
  const r = rito([HEAT, lead(AIR, 15), lead(COLD, 30), lead(REST, 60)]);
  const s = E.createSession(r);
  E.start(s, at(0));
  E.tap(s, at(600), 0);
  assert.deepEqual(E.tick(s, at(700)).map((x) => x.kind), ['begin']);
  assert.deepEqual(E.tick(s, at(736)).map((x) => x.kind), ['enter']);             // 600 + 15 + 120 = 735
  assert.equal(s.events.find((e) => e.e === 'auto').t, at(735));
  assert.equal(E.skip(s, at(740), 2), 'ok');                   // saltata mentre ci andava
  assert.deepEqual(E.summary(s).moments[2].actual_s, 0);
  E.pause(s, at(750)); E.resume(s, at(850));                   // pausa nel passaggio verso il riposo
  assert.equal(Math.round(E.view(s, at(860)).lead_remain_s), 40);
  E.tick(s, at(905));
  E.tap(s, at(1500), 3);
  assert.equal(E.summary(s).moments[3].actual_s, 600);
  const tl = E.timeline(rito([lead(REST, null), lead(HEAT, null), lead(COLD, null), lead(REST, null)]));
  assert.deepEqual(tl.map((m) => m.lead_s), [0, 0, 30, 60]);   // il primo mai; il calore conta dal tocco
  assert.deepEqual(tl.map((m) => m.settle_s), [0, 30, 0, 0]);
  assert.match(tl[1].lead_text, /stenditi/);
  assert.match(E.validate(rito([lead(REST, 900)])).join(), /lead_s/);
  assert.match(E.validate(rito([lead(HEAT, 120)])).join(), /da 0 a 60/);
  assert.equal(E.planned(DEMO).total_s, 600 + 120 + 60 + 600 + 600 + 120 + 900 + 15 + 30 + 60 + 15 + 60);
});

test('il calore conta dal tocco: il passaggio è solo il tempo per sistemarsi', () => {
  const s = E.createSession(rito([REST, lead(HEAT, 30), REST]));
  E.start(s, at(0));
  E.tap(s, at(600), 0);                                        // «Entro»: da qui è in cabina
  const v = E.view(s, at(610));
  assert.deepEqual([v.lead, v.settling, Math.round(v.elapsed_s), v.label], [false, true, 10, 'Sono uscito']);
  assert.deepEqual(E.tick(s, at(625)), []);
  assert.deepEqual(E.tick(s, at(631)).map((x) => x.kind), ['begin']);   // il gong d'inizio, dopo essersi stesi
  assert.equal(E.view(s, at(640)).settling, false);
  assert.deepEqual(E.tick(s, at(1200)).map((x) => x.kind), ['target']);  // 600 s dal tocco, non dal gong
  assert.deepEqual(E.tick(s, at(1380)).map((x) => x.kind), ['max']);     // 780 s dal tocco: il limite è onesto
  E.tap(s, at(1390), 1);
  assert.equal(E.summary(s).moments[1].actual_s, 790);
});

test('uscita lampo: nei primi secondi di caldo o freddo serve un secondo tocco', () => {
  const s = E.createSession(rito([REST, HEAT, lead(COLD, 30), REST]));
  E.start(s, at(0));
  assert.equal(E.tap(s, at(600), 0), 'ok');
  assert.equal(E.tap(s, at(601), 1), 'early');                 // tre tocchi di fila non chiudono il calore
  assert.equal(E.view(s, at(602)).quick, true);
  assert.equal(E.view(s, at(602)).m.id, 'calore');
  assert.equal(E.tap(s, at(603), 1, true), 'ok');              // ma chi vuole uscire subito esce
  assert.equal(E.tap(s, at(610), 2), 'begin');                 // «Ci sono» nell'acqua
  assert.equal(E.tap(s, at(612), 2), 'early');
  assert.equal(E.tap(s, at(640), 2), 'ok');
});

test('indietro da un «Ci sono»: rientrando il colpo d\'inizio torna a suonare', () => {
  const s = E.createSession(rito([HEAT, lead(REST, 60), HEAT]));
  E.start(s, at(0));
  E.tap(s, at(600), 0);
  assert.equal(E.tap(s, at(605), 1), 'begin');
  assert.equal(E.undo(s, at(608)), true);                      // era ancora nel calore
  E.tap(s, at(700), 0);
  assert.deepEqual(E.tick(s, at(761)).map((x) => x.kind), ['begin']);
});

test('il log che torna porta anche il riassunto: se viene tagliato i calori non si perdono', () => {
  const ms = [];
  for (let k = 0; k < 12; k++) ms.push(Object.assign({}, HEAT, { id: 'c' + k }), Object.assign({}, REST, { id: 'r' + k, min_s: undefined }));
  const s = E.createSession(rito(ms));
  E.start(s, at(0));
  let t = 0;
  while (!s.finished) { t += 300; E.pause(s, at(t)); E.resume(s, at(t + 5)); t += 300; E.tap(s, at(t), s.cur, true); }
  const sum = E.summary(s);
  const d = E.decodeLog(E.encodeLog(s, {}, '', 900));
  assert.ok(d.truncated > 0);
  assert.deepEqual(d.actual.map((x) => x.actual_s), sum.moments.map((x) => x.actual_s));
  assert.deepEqual(d.actual.map((x) => x.ended), sum.moments.map((x) => x.ended));
  assert.equal(d.events[0].e, 'start');
  assert.equal(d.events[d.events.length - 1].e, 'end');
});

test('le parole del tempo non sono cronometri', () => {
  assert.equal(E.minutes(20), 'meno di un minuto');
  assert.equal(E.minutes(70), 'un minuto');
  assert.equal(E.minutes(600), '10 minuti');
});

test('i due validatori dicono la stessa cosa: casi condivisi con la soglia in Python', () => {
  const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'cases.json'), 'utf8'));
  for (const [why, r] of cases.invalid) assert.ok(E.validate(r).length > 0, 'doveva essere rifiutato: ' + why);
  for (const [why, r] of cases.valid) assert.deepEqual(E.validate(r), [], 'doveva passare: ' + why);
});
