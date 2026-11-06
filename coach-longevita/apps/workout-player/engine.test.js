// node --test apps/workout-player/
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const E = require('./engine.js');

const load = (f) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', f), 'utf8'));
const REAL = load('2026-11-06.player.json');
const DEMO = load('demo.player.json');
const T0 = Date.UTC(2026, 10, 6, 17, 0, 0);

test('timeline della seduta reale', () => {
  const st = E.buildTimeline(REAL);
  const kinds = (b) => st.filter((x) => x.b === b).map((x) => x.kind[0]).join('');
  assert.strictEqual(kinds(0), 'pwww');                 // prep 5s + rower timer + 2 manuali
  assert.strictEqual(st[1].mode, 'timer'); assert.strictEqual(st[1].dur, 300);
  assert.strictEqual(st[2].mode, 'manual');
  assert.strictEqual(kinds(1), 'pwrwrwrwrw');           // rampa + 2 serie, niente recupero finale
  assert.strictEqual(st.find((x) => x.b === 1 && x.kind === 'prep').mode, 'manual');
  assert.deepStrictEqual(st.filter((x) => x.b === 1 && x.kind === 'rest').map((x) => x.dur), [90, 120, 180, 180]);
  assert.strictEqual(kinds(2), 'pwwrwwrww');            // superserie 3 giri, recupero a fine giro
  const emom = st.filter((x) => x.b === 3 && x.kind === 'work');
  assert.strictEqual(emom.length, 10);
  assert.deepStrictEqual(emom.slice(0, 3).map((x) => x.name), ['Row', 'Goblet Squat', 'Row']);
  assert.ok(emom.every((x) => x.dur === 60 && x.mark));
  assert.strictEqual(kinds(4), 'pwrwrwrw');             // 40/20 × 4
  assert.strictEqual(st[0].dur, 5);
});

test('timer reale: catch-up dopo sospensione con flag auto', () => {
  const s = E.createSession(DEMO);
  E.start(s, T0);
  // la pagina "dorme" 50 secondi: prep 5 + timed 30 + prep 3 = 38s → dentro il primo lavoro 20s
  const evs = E.tick(s, T0 + 50000);
  assert.deepStrictEqual(evs.map((e) => [e.e, e.s, e.t - T0, !!e.auto]),
    [['step', 1, 5000, true], ['step', 2, 35000, true], ['step', 3, 38000, true]]);
  const v = E.view(s, T0 + 50000);
  assert.strictEqual(v.step.name, 'Air Squat');
  assert.strictEqual(Math.round(v.remaining), 8);
  // tick puntuale: nessun auto
  const evs2 = E.tick(s, T0 + 58200);
  assert.strictEqual(evs2.length, 1); assert.ok(!evs2[0].auto);
  assert.strictEqual(evs2[0].t, T0 + 58000);
});

test('pausa e ripresa spostano la fine del passo', () => {
  const s = E.createSession(DEMO);
  E.start(s, T0);
  E.tick(s, T0 + 6000);                  // nel timed (inizio 5s, dura 30)
  E.pause(s, T0 + 10000);
  assert.deepStrictEqual(E.tick(s, T0 + 100000), []);
  assert.strictEqual(Math.round(E.view(s, T0 + 100000).remaining), 25);
  E.resume(s, T0 + 100000);
  assert.strictEqual(Math.round(E.view(s, T0 + 110000).remaining), 15);
  const evs = E.tick(s, T0 + 125000);
  assert.strictEqual(evs[0].t, T0 + 125000);  // 5 + 30 + 90 di pausa
});

test('salta, fatto, round, stop', () => {
  const s = E.createSession(REAL);
  E.start(s, T0);
  E.skip(s, T0 + 1000);                         // salta prep → rower
  assert.strictEqual(s.cur, 1);
  E.skip(s, T0 + 2000);                         // salta rower → cat-cow (manuale)
  assert.strictEqual(E.tick(s, T0 + 999999).length, 0);  // manuale: non avanza da solo
  E.done(s, T0 + 1000000);
  assert.strictEqual(s.cur, 3);
  const n = s.events.length;
  E.done(s, T0 + 1001000);                      // WGS → prep stacco (manuale)
  assert.strictEqual(s.steps[s.cur].kind, 'prep');
  E.done(s, T0 + 1002000);                      // prep manuale: niente evento done
  assert.deepStrictEqual(s.events.slice(n).map((e) => e.e), ['done', 'step', 'step']);
  // salto fino all'EMOM e segno "fatto" senza avanzare
  let t = T0 + 1003000;
  while (s.steps[s.cur].b < 3 || s.steps[s.cur].kind !== 'work') { t += 1000; E.skip(s, t); }
  const cur = s.cur;
  E.done(s, t + 5000); E.done(s, t + 6000);
  assert.strictEqual(s.cur, cur);
  assert.strictEqual(s.events.filter((e) => e.e === 'done' && e.s === cur).length, 1);
  E.stop(s, t + 7000);
  assert.ok(s.finished); assert.strictEqual(s.status, 'stop');
  assert.deepStrictEqual(E.skip(s, t + 9000), []);
});

test('fix 1: Salta/Fatto toccati dopo lo scadere agiscono solo sul passo visto', () => {
  const s = E.createSession(REAL);
  E.start(s, T0);
  let t = T0;
  while (!(s.steps[s.cur].kind === 'rest' && s.steps[s.cur].dur === 90)) { t += 1000; E.skip(s, t); }
  const rest = s.cur, endRest = s.stepStart + 90000;
  // recupero da 90": il tap su «Salta» arriva 150 ms dopo la scadenza
  const evs = E.skip(s, endRest + 150, rest);
  assert.deepStrictEqual(evs.map((e) => e.e), ['step']);        // solo la transizione del timer
  assert.strictEqual(s.cur, rest + 1);
  assert.strictEqual(s.steps[s.cur].kind, 'work');                // serie da 80 kg intatta
  assert.ok(!s.events.some((e) => e.e === 'skip' && e.s === rest + 1));
  // EMOM: «Fatto (segna)» del minuto 24 tappato a minuto 25 iniziato → nessun mark
  while (!(s.steps[s.cur].b === 3 && s.steps[s.cur].kind === 'work')) { t = s.changedAt + 1000; E.skip(s, t); }
  const m = s.cur;
  const evs2 = E.done(s, s.stepStart + 60100, m);
  assert.deepStrictEqual(evs2.map((e) => e.e), ['step']);
  assert.ok(!s.marked);
  // con il passo giusto l'azione va
  assert.deepStrictEqual(E.done(s, s.stepStart + 30000, m + 1).map((e) => e.e), ['done']);
});

test('fix 2: doppio tap su Pronto/Fatto chiude un solo passo', () => {
  const s = E.createSession(REAL);
  E.start(s, T0);
  let t = T0;
  while (!(s.steps[s.cur].b === 1 && s.steps[s.cur].kind === 'prep')) { t += 1000; E.skip(s, t); }
  const prep = s.cur;
  t += 5000;
  E.done(s, t, prep);                         // «▶ Pronto»
  E.done(s, t + 150, prep);                   // secondo tap: passo cambiato → no-op
  E.done(s, t + 150, prep + 1);               // anche con l'indice nuovo: guardia 700 ms
  assert.strictEqual(s.cur, prep + 1);
  assert.ok(!s.events.some((e) => e.e === 'done' && e.s === prep + 1));
  E.done(s, t + 40000, prep + 1);             // fine serie vera
  assert.strictEqual(s.steps[s.cur].kind, 'rest');
  // superserie: OHP e negative non si chiudono in 150 ms
  while (!(s.steps[s.cur].b === 2 && s.steps[s.cur].kind === 'work')) { t = s.changedAt + 1000; E.skip(s, t); }
  const ohp = s.cur; t = s.changedAt + 20000;
  E.done(s, t, ohp); E.done(s, t + 150);      // anche senza expected, la guardia ferma il 2° tap
  assert.strictEqual(s.cur, ohp + 1);
  assert.strictEqual(E.skip(s, t + 300).length, 0);
});

test('fix 4: riapertura dopo chiusura, il tempo ad app chiusa non conta', () => {
  const s = E.createSession(REAL);
  E.start(s, T0);
  let t = T0;
  while (!(s.steps[s.cur].b === 3 && s.steps[s.cur].kind === 'work')) { t = s.changedAt + 1000; E.skip(s, t); }
  E.tick(s, s.stepStart + 70000);             // secondo minuto EMOM, poi iOS uccide l'app
  const saved = JSON.parse(JSON.stringify(s.events));
  const last = saved[saved.length - 1], later = last.t + 3 * 3600 * 1000;
  // «Invia quello che c'è» tre ore dopo: stop all'ultimo evento reale, niente minuti auto
  const a = E.replay(REAL, saved);
  const evs = E.abandon(a);
  assert.deepStrictEqual(evs.map((e) => [e.e, e.t]), [['stop', last.t]]);
  assert.strictEqual(a.status, 'stop');
  assert.ok(E.view(a, later).total < 3600);
  // «Riprendi»: in pausa sul passo salvato; la ripresa porta il flag reopen
  const r = E.replay(REAL, saved);
  const lastSeen = last.t + 4000;
  const ev2 = E.reopen(r, lastSeen);
  assert.deepStrictEqual(ev2.map((e) => [e.e, e.t]), [['pause', lastSeen]]);
  assert.strictEqual(r.cur, s.cur);
  assert.deepStrictEqual(E.tick(r, later), []);
  const rem = E.view(r, later).remaining;
  assert.strictEqual(Math.round(rem), 60 - Math.round((lastSeen - r.stepStart) / 1000));
  const res = E.resume(r, later);
  assert.strictEqual(res[0].reopen, 1);
  assert.strictEqual(Math.round(E.view(r, later + 1000).remaining), Math.round(rem) - 1);
  // il flag sopravvive al log compatto
  const d = E.decodeLog(E.encodeLog(r));
  assert.strictEqual(d.events[d.events.length - 1].reopen, 1);
  // seduta già finita: abandon non fa nulla
  assert.deepStrictEqual(E.abandon(a), []);
});

test('demo: il flag finisce nel log', () => {
  const s = E.createSession(DEMO); E.start(s, T0); E.stop(s, T0 + 5000);
  assert.strictEqual(JSON.parse(E.encodeLog(s)).demo, 1);
  assert.strictEqual(E.decodeLog(E.encodeLog(s)).demo, true);
});

test('amrap: contatore giri e fine a tempo', () => {
  const w = { date: '2026-11-06', title: 'a', blocks: [{ type: 'amrap', name: 'A', prep_s: 0, duration_s: 60,
    exercises: [{ name: 'Burpee', reps: 5 }] }] };
  const s = E.createSession(w);
  E.start(s, T0); E.round(s, T0 + 10000); E.round(s, T0 + 20000);
  assert.strictEqual(E.view(s, T0 + 21000).rounds, 2);
  const evs = E.tick(s, T0 + 61000);
  assert.deepStrictEqual(evs.map((e) => e.e), ['end']);
  assert.strictEqual(s.status, 'end');
});

test('replay del log ricostruisce lo stato (ripresa dopo crash)', () => {
  const s = E.createSession(DEMO);
  E.start(s, T0); E.tick(s, T0 + 20000); E.pause(s, T0 + 21000); E.resume(s, T0 + 31000);
  const r = E.replay(DEMO, JSON.parse(JSON.stringify(s.events)));
  assert.strictEqual(r.cur, s.cur); assert.strictEqual(r.stepStart, s.stepStart);
  // anche dal log compatto (risoluzione al secondo)
  const d = E.decodeLog(E.encodeLog(s));
  const r2 = E.replay(DEMO, d.events);
  assert.strictEqual(r2.cur, s.cur);
  assert.ok(Math.abs(r2.stepStart - s.stepStart) <= 1000);
});

function fullSession(w, extra) {
  // seduta completa realistica: manuali chiusi dopo 40s, qualche pausa, "fatto" negli EMOM
  const s = E.createSession(w);
  let now = T0; E.start(s, now);
  let guard = 0;
  while (!s.finished && guard++ < 1000) {
    const st = s.steps[s.cur];
    if (st.mode === 'manual' || st.mode === 'up') { now += 40000; E.tick(s, now); E.done(s, now); continue; }
    if (st.mark && !s.marked) { now = s.stepStart + 35000; E.done(s, now); }
    if (extra && st.kind === 'rest' && guard % 3 === 0) { E.pause(s, now + 2000); now += 30000; E.resume(s, now); }
    now = s.stepStart + st.dur * 1000 + 300; E.tick(s, now);
  }
  return s;
}

test('codifica sendData sotto 4096 byte con la seduta reale', () => {
  const s = fullSession(REAL, true);
  assert.strictEqual(s.status, 'end');
  const out = E.encodeLog(s);
  const bytes = E.byteLen(out);
  console.log(`  seduta reale: ${s.events.length} eventi, ${s.steps.length} passi → ${bytes} byte`);
  assert.ok(bytes < 4096);
  const d = E.decodeLog(out);
  assert.strictEqual(d.events.length, s.events.length);
  assert.deepStrictEqual(d.events.map((e) => e.e), s.events.map((e) => e.e));
  assert.ok(JSON.parse(out).S[0].length === 4, 'etichette presenti');
});

test('codifica sendData degrada ma resta sotto 4096 byte con log enorme', () => {
  const w = { date: '2026-11-06', title: 'x', blocks: [{ type: 'amrap', name: 'A', prep_s: 0, duration_s: 3600,
    exercises: [{ name: 'Burpee' }] }] };
  const s = E.createSession(w); E.start(s, T0);
  for (let i = 1; i < 2000; i++) E.round(s, T0 + i * 1500);
  const out = E.encodeLog(s);
  assert.ok(E.byteLen(out) <= 4096);
  assert.ok(JSON.parse(out).tr > 0);
});

test('fragment: andata e ritorno, anche con parametri tgWebApp e deflate-raw', async () => {
  const frag = E.encodeWorkout(REAL);
  console.log(`  fragment reale w=: ${frag.length} caratteri`);
  assert.deepStrictEqual(await E.parseFragment('#' + frag + '&tgWebAppVersion=8.0'), REAL);
  const raw = new Uint8Array(await new Response(new Blob([JSON.stringify(REAL)]).stream()
    .pipeThrough(new CompressionStream('deflate-raw'))).arrayBuffer());
  const z = 'z=' + E.b64urlEncode(raw);
  console.log(`  fragment reale z=: ${z.length} caratteri`);
  assert.deepStrictEqual(await E.parseFragment('#tgWebAppData=x&' + z), REAL);
  assert.strictEqual(await E.parseFragment('#tgWebAppVersion=8.0'), null);
});

test('validazione', () => {
  assert.deepStrictEqual(E.validateWorkout(REAL), []);
  assert.deepStrictEqual(E.validateWorkout(DEMO), []);
  assert.ok(E.validateWorkout({ blocks: [{ type: 'boh', exercises: [] }] }).length >= 2);
});

test('immagini: slug → frame alternati, slug assente o strano → niente', () => {
  assert.deepStrictEqual(E.imgFrames('deadlift'), ['img/deadlift-frame-1.svg', 'img/deadlift-frame-2.svg']);
  assert.deepStrictEqual(E.imgFrames(null), []);
  assert.deepStrictEqual(E.imgFrames('../x'), []);
  const st = E.buildTimeline(REAL);
  assert.strictEqual(st.find((x) => x.kind === 'work' && x.name === 'Deadlift').img, 'deadlift');
});

test('prossimo esercizio da recupero, prep e fine', () => {
  const s = E.createSession(REAL);
  E.start(s, T0);
  assert.strictEqual(E.nextWork(s).name, 'Row');                 // dal prep del primo blocco
  let t = T0;
  while (!(s.steps[s.cur].kind === 'rest' && s.steps[s.cur].dur === 90)) { t += 1000; E.skip(s, t); }
  const nw = E.nextWork(s);
  assert.strictEqual(nw.detail, '3 rip. · 80 kg');
  assert.strictEqual(nw.img, 'deadlift');
  // recupero della superserie a fine giro → OHP del giro dopo
  while (!(s.steps[s.cur].b === 2 && s.steps[s.cur].kind === 'rest')) { t += 1000; E.skip(s, t); }
  assert.strictEqual(E.nextWork(s).name, 'Strict Press');
  assert.strictEqual(E.nextWork(s, s.steps.length - 1), null);
  // 20/10: il riposo indica la stazione successiva
  const w = { date: 'x', blocks: [{ type: 'interval', name: 'I', prep_s: 0, work_s: 20, rest_s: 10, rounds: 1,
    exercises: [{ name: 'A' }, { name: 'B', img: 'plank' }] }] };
  const s2 = E.createSession(w); E.start(s2, T0); E.tick(s2, T0 + 21000);
  assert.strictEqual(s2.steps[s2.cur].kind, 'rest');
  assert.strictEqual(E.nextWork(s2).img, 'plank');
});

test('scheda: stato dei passi (fatti, saltati, corrente, prossimo)', () => {
  const s = E.createSession(REAL);
  E.start(s, T0);
  E.skip(s, T0 + 1000);                 // prep → rower
  E.skip(s, T0 + 2000);                 // rower saltato → cat-cow
  E.done(s, T0 + 30000);                // cat-cow fatto → WGS
  let sh = E.sheet(s);
  assert.strictEqual(sh.length, 5);
  assert.deepStrictEqual(sh[0].items.map((x) => x.status), ['skipped', 'done', 'current']);
  assert.ok(sh[1].items.every((x) => x.status === 'todo'));
  assert.strictEqual(sh[1].items.length, 5);
  assert.strictEqual(sh[3].items.length, 10);
  assert.ok(sh[4].optional);
  E.done(s, T0 + 60000);                // WGS → prep stacco: il primo stacco è "next"
  sh = E.sheet(s);
  assert.strictEqual(sh[1].items[0].status, 'next');
  assert.strictEqual(sh[0].items[2].status, 'done');
});

test('ripresa dopo stop: continua in pausa dal passo giusto, invio solo della parte nuova', () => {
  const s = E.createSession(REAL);
  E.start(s, T0);
  let t = T0;
  while (!(s.steps[s.cur].kind === 'rest' && s.steps[s.cur].dur === 120)) { t = s.changedAt + 1000; E.skip(s, t); }
  const rest = s.cur;
  E.stop(s, t + 5000);                  // «Termina» per sbaglio durante il recupero
  const sent = s.events.length;
  const saved = JSON.parse(JSON.stringify(s.events));
  // troppo tardi: niente continuazione
  assert.strictEqual(E.continueStep(E.replay(REAL, saved), t + 7 * 3600 * 1000), -1);
  const later = t + 3600 * 1000;
  const r = E.replay(REAL, saved);
  assert.strictEqual(E.continueStep(r, later), rest + 1);          // dal passo dopo: la serie da 90
  const evs = E.continueAt(r, later);
  assert.deepStrictEqual(evs.map((e) => [e.e, e.s, e.t]), [['step', rest + 1, later], ['pause', rest + 1, later]]);
  assert.ok(!r.finished && r.paused);
  assert.deepStrictEqual(E.tick(r, later + 3600000), []);         // in pausa: il tempo chiuso non conta
  const res = E.resume(r, later + 60000);
  assert.strictEqual(res[0].reopen, 1);
  E.done(r, later + 90000);
  E.stop(r, later + 100000);
  // il replay del log intero (stop + continuazione) ricostruisce lo stato
  const rr = E.replay(REAL, r.events);
  assert.strictEqual(rr.cur, r.cur); assert.strictEqual(rr.status, 'stop');
  // invio: solo la continuazione, con cont = t0 originale
  const o = JSON.parse(E.encodeLog(r, 4096, sent));
  assert.strictEqual(o.cont, T0);
  assert.strictEqual(o.E.length, r.events.length - sent);
  assert.strictEqual(o.E[0][3] & 4, 4);                            // flag cont sul primo passo
  assert.strictEqual(E.decodeLog(JSON.stringify(o)).events[0].cont, 1);
  // stop su una serie non chiusa: si riparte da quella stessa serie
  const s3 = E.createSession(REAL); E.start(s3, T0);
  t = T0; while (!(s3.steps[s3.cur].b === 1 && s3.steps[s3.cur].kind === 'work')) { t = s3.changedAt + 1000; E.skip(s3, t); }
  const set1 = s3.cur; E.stop(s3, t + 10000);
  assert.strictEqual(E.continueStep(s3, t + 20000), set1);
  // seduta finita con end sull'ultimo passo: niente da continuare
  const s4 = E.createSession(DEMO); E.start(s4, T0);
  for (let i = 0; i < 100 && !s4.finished; i++) { t = s4.changedAt + 1000; E.skip(s4, t); }
  assert.strictEqual(s4.status, 'end');
  assert.strictEqual(E.continueStep(s4, t + 1000), -1);
});
