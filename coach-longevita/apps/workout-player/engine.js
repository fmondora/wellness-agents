/* Workout player — motore del tempo, puro e testabile (node --test).
 *
 * Il tempo è sempre orologio reale: ogni passo ha un istante d'inizio
 * (stepStart, ms epoch) e la sua fine si calcola, non si contano tick.
 * Lo stato si ricava dal log degli eventi (apply/replay): il log è l'unica
 * cosa da salvare per riprendere una seduta interrotta.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WorkoutEngine = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const EVENTS = ['start', 'step', 'pause', 'resume', 'skip', 'done', 'round', 'stop', 'end'];
  const KINDS = { prep: 'p', work: 'w', rest: 'r' };
  const AUTO_LAG_MS = 2000; // transizione registrata in ritardo (pagina sospesa) → auto
  const TAP_GUARD_MS = 700; // tap ignorati subito dopo un cambio di passo (doppio tap)
  const TYPES = ['timed', 'sets', 'emom', 'interval', 'amrap', 'fortime'];

  // --- esercizi -------------------------------------------------------------

  function fmtTime(sec) {
    sec = Math.max(0, Math.round(sec));
    const m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + String(s).padStart(2, '0');
  }

  function detailOf(ex, set) {
    const pick = (k) => (set && set[k] != null ? set[k] : ex[k]);
    const reps = pick('reps'), kg = pick('kg'), time = pick('time_s');
    const out = [];
    if (reps != null) out.push(typeof reps === 'number' ? reps + ' rip.' : String(reps));
    if (time != null && reps != null) out.push(time + '″');
    if (kg != null) out.push(kg + ' kg');
    return out.join(' · ');
  }

  function exInfo(ex, set) {
    const note = [set && set.note, ex.note].filter(Boolean).join(' · ');
    return { name: ex.name || '', detail: detailOf(ex, set), note, img: ex.img || null };
  }

  // --- timeline -------------------------------------------------------------

  function buildTimeline(w) {
    const steps = [];
    (w.blocks || []).forEach((blk, b) => {
      let bs = 0;
      const push = (o) => steps.push(Object.assign(
        { i: steps.length, b, bs: bs++, kind: 'work', mode: 'timer', dur: 0,
          name: '', detail: '', note: '', img: null, round: 0, rounds: 0, mark: false, list: null }, o));
      const exs = blk.exercises || [];
      const prep = blk.prep_s !== undefined ? blk.prep_s : (b === 0 ? 5 : null);
      if (prep !== 0) {
        push({ kind: 'prep', mode: prep == null ? 'manual' : 'timer', dur: prep || 0,
               name: blk.name, detail: blk.optional ? 'facoltativo' : '' });
      }
      const rest = (dur) => push({ kind: 'rest', mode: 'timer', dur, name: 'Recupero' });

      switch (blk.type) {
        case 'timed':
          exs.forEach((ex) => {
            const d = ex.time_s != null ? ex.time_s : (exs.length === 1 ? blk.duration_s : null);
            push(Object.assign(exInfo(ex), { mode: d ? 'timer' : 'manual', dur: d || 0 }));
          });
          break;
        case 'sets': {
          const rounds = blk.rounds || Math.max(1, ...exs.map((e) => (e.sets || []).length));
          for (let r = 0; r < rounds; r++) {
            exs.forEach((ex, k) => {
              const set = ex.sets ? ex.sets[r] : null;
              if (ex.sets && !set) return;
              push(Object.assign(exInfo(ex, set), { mode: 'manual', round: r + 1, rounds }));
              const lastEx = k === exs.length - 1;
              const d = set && set.rest_s != null ? set.rest_s : (lastEx ? blk.rest_s : blk.rest_between_s);
              if (d && !(lastEx && r === rounds - 1)) rest(d);
            });
          }
          break;
        }
        case 'emom': {
          const iv = blk.interval_s || 60;
          for (let m = 0; m < blk.minutes; m++) {
            push(Object.assign(exInfo(exs[m % exs.length]),
              { dur: iv, mark: true, round: m + 1, rounds: blk.minutes }));
          }
          break;
        }
        case 'interval': {
          const rounds = blk.rounds || 1, n = rounds * exs.length;
          for (let j = 0; j < n; j++) {
            push(Object.assign(exInfo(exs[j % exs.length]),
              { dur: blk.work_s, round: Math.floor(j / exs.length) + 1, rounds }));
            if (blk.rest_s && j < n - 1) rest(blk.rest_s);
          }
          break;
        }
        case 'amrap':
        case 'fortime': {
          const amrap = blk.type === 'amrap';
          push({ mode: amrap ? 'amrap' : 'up', dur: amrap ? blk.duration_s : (blk.cap_s || 0),
                 name: blk.name, detail: blk.rounds ? blk.rounds + ' giri' : (amrap ? 'AMRAP' : 'for time'),
                 note: blk.note || '', list: exs.map((e) => exInfo(e)) });
          break;
        }
      }
      if (blk.rest_after_s) rest(blk.rest_after_s);
    });
    return steps;
  }

  function stepLabel(st) {
    if (st.kind === 'prep') return 'Prep ' + st.name;
    return st.name + (st.detail ? ' ' + st.detail : '') + (st.rounds > 1 ? ' [' + st.round + '/' + st.rounds + ']' : '');
  }

  // --- sessione -------------------------------------------------------------

  function createSession(workout) {
    return { workout, steps: buildTimeline(workout), events: [], t0: 0, cur: -1, stepStart: 0,
             paused: false, pausedAt: 0, finished: false, status: null, rounds: 0, marked: false,
             changedAt: 0, reopened: false };
  }

  /* Aggiorna lo stato derivato da UN evento. Unica fonte di verità: il log. */
  function apply(s, ev) {
    switch (ev.e) {
      case 'start': s.t0 = ev.t; s.cur = ev.s; s.stepStart = s.changedAt = ev.t; s.rounds = 0; s.marked = false; break;
      case 'step':
        if (ev.cont) { s.finished = false; s.status = null; s.paused = false; } // continuazione dopo uno stop
        s.cur = ev.s; s.stepStart = s.changedAt = ev.t; s.rounds = 0; s.marked = false; break;
      case 'pause': if (!s.paused) { s.paused = true; s.pausedAt = ev.t; } break;
      case 'resume': if (s.paused) { s.stepStart += ev.t - s.pausedAt; s.paused = false; } break;
      case 'round': s.rounds++; break;
      case 'done': s.marked = true; break;
      case 'stop': case 'end':
        if (s.paused) { s.stepStart += ev.t - s.pausedAt; s.paused = false; }
        s.finished = true; s.status = ev.e; break;
    }
    return s;
  }

  function emit(s, e, t, idx, auto, flags) {
    const ev = Object.assign({ t: Math.round(t), e, s: idx }, flags);
    if (auto) ev.auto = 1;
    s.events.push(ev);
    apply(s, ev);
    return ev;
  }

  function replay(workout, events) {
    const s = createSession(workout);
    for (const ev of events) { s.events.push(ev); apply(s, ev); }
    return s;
  }

  function advance(s, t, auto) {
    if (s.cur + 1 >= s.steps.length) return [emit(s, 'end', t, s.cur, auto)];
    return [emit(s, 'step', t, s.cur + 1, auto)];
  }

  function stepEnd(s) {
    const st = s.steps[s.cur];
    if (!st || st.mode === 'manual' || (st.mode === 'up' && !st.dur)) return Infinity;
    return s.stepStart + st.dur * 1000;
  }

  /* Recupera tutte le transizioni scadute fino a `now`, ognuna all'istante calcolato. */
  function tick(s, now) {
    const out = [];
    if (s.cur < 0 || s.finished || s.paused) return out;
    for (let guard = 0; guard < 100000 && !s.finished; guard++) {
      const end = stepEnd(s);
      if (now < end) break;
      out.push(...advance(s, end, now - end > AUTO_LAG_MS));
    }
    return out;
  }

  function live(s) { return s.cur >= 0 && !s.finished; }

  function start(s, now) {
    if (s.cur >= 0 || !s.steps.length) return [];
    return [emit(s, 'start', now, 0)];
  }

  function pause(s, now) {
    if (!live(s) || s.paused) return [];
    const out = tick(s, now);
    if (live(s)) out.push(emit(s, 'pause', now, s.cur));
    return out;
  }

  function resume(s, now) {
    if (!live(s) || !s.paused) return [];
    const flags = s.reopened ? { reopen: 1 } : null;
    s.reopened = false;
    return [emit(s, 'resume', now, s.cur, false, flags)];
  }

  /* Prima di ogni azione dell'utente: recupera il tempo, poi agisce solo se il passo
     è ancora quello che l'utente vedeva (expected) e non è appena cambiato. */
  function gate(s, now, expected) {
    if (!live(s)) return { out: [], ok: false };
    const out = s.paused ? [] : tick(s, now);
    const ok = live(s) && (expected == null || s.cur === expected) && now - s.changedAt >= TAP_GUARD_MS;
    if (ok && s.paused) out.push(...resume(s, now));
    return { out, ok };
  }

  function skip(s, now, expected) {
    const { out, ok } = gate(s, now, expected);
    if (!ok) return out;
    out.push(emit(s, 'skip', now, s.cur));
    return out.concat(advance(s, now, false));
  }

  /* "Fatto": chiude un passo manuale / for time; in EMOM segna solo l'istante. */
  function done(s, now, expected) {
    const { out, ok } = gate(s, now, expected);
    if (!ok) return out;
    const st = s.steps[s.cur];
    if (st.mark) {
      if (!s.marked) out.push(emit(s, 'done', now, s.cur));
      return out;
    }
    if (st.mode !== 'manual' && st.mode !== 'up') return out;
    if (st.kind !== 'prep') out.push(emit(s, 'done', now, s.cur));
    return out.concat(advance(s, now, false));
  }

  function round(s, now, expected) {
    if (!live(s)) return [];
    const out = s.paused ? [] : tick(s, now);
    if (!live(s) || (expected != null && s.cur !== expected) || s.steps[s.cur].mode !== 'amrap') return out;
    if (s.paused) out.push(...resume(s, now));
    out.push(emit(s, 'round', now, s.cur));
    return out;
  }

  function stop(s, now) {
    if (!live(s)) return [];
    const out = s.paused ? [] : tick(s, now);
    if (!live(s)) return out;
    out.push(emit(s, 'stop', now, s.cur));
    return out;
  }

  /* Seduta ripresa dopo una chiusura dell'app: il tempo ad app chiusa non conta.
     abandon: chiude all'ultimo evento reale, senza catch-up.
     reopen: torna in pausa sul passo salvato (all'ultimo istante visto vivo); la
     ripresa successiva porta il flag reopen. */
  function abandon(s) {
    if (!live(s)) return [];
    return [emit(s, 'stop', lastT(s), s.cur)];
  }

  const CONTINUE_MAX_MS = 6 * 3600 * 1000;

  /* Dopo uno stop (o end) recente: da quale passo si può continuare? -1 se non si può.
     Se lo stop è caduto su una serie non chiusa si riparte da quella, altrimenti dal passo dopo. */
  function continueStep(s, now, maxMs) {
    if (!s.finished || !s.events.length) return -1;
    if (now - lastT(s) > (maxMs || CONTINUE_MAX_MS)) return -1;
    const st = s.steps[s.cur];
    if (s.status === 'stop' && st && st.kind === 'work' && !s.marked && st.mode !== 'timer') return s.cur;
    return s.cur + 1 < s.steps.length ? s.cur + 1 : -1;
  }

  /* Riapre la seduta finita: nuovo passo (flag cont) subito in pausa; la ripresa porta reopen. */
  function continueAt(s, now, maxMs) {
    const i = continueStep(s, now, maxMs);
    if (i < 0) return [];
    const out = [emit(s, 'step', now, i, false, { cont: 1 }), emit(s, 'pause', now, i)];
    s.reopened = true;
    return out;
  }

  function reopen(s, lastSeen) {
    if (!live(s)) return [];
    const t = Math.max(lastT(s), lastSeen || 0);
    const out = s.paused ? [] : tick(s, t);
    if (live(s) && !s.paused) out.push(emit(s, 'pause', t, s.cur));
    if (live(s)) s.reopened = true;
    return out;
  }

  /* Il prossimo passo di lavoro dopo `from` (default: il corrente): per recuperi e prep. */
  function nextWork(s, from) {
    for (let i = (from == null ? s.cur : from) + 1; i < s.steps.length; i++) {
      if (s.steps[i].kind === 'work') return s.steps[i];
    }
    return null;
  }

  /* Clip vocali pre-registrate: stesso slug di apps/workout-player/make_voice.py. */
  function voiceSlug(text) {
    return String(text || '').toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }

  /* Immagini dell'illustrazione: slug del catalogo coach → frame alternati. */
  function imgFrames(slug) {
    if (!slug || !/^[a-z0-9-]+$/.test(slug)) return [];
    return ['img/' + slug + '-frame-1.svg', 'img/' + slug + '-frame-2.svg'];
  }

  /* L'intera seduta per la vista "Scheda": blocchi → passi di lavoro con stato
     done | skipped | current | next | todo. */
  function sheet(s) {
    const skipped = new Set(s.events.filter((e) => e.e === 'skip').map((e) => e.s));
    const cur = s.steps[s.cur];
    const nw = cur && cur.kind !== 'work' && !s.finished ? nextWork(s) : null;
    const blocks = (s.workout.blocks || []).map((b, i) => ({ b: i, name: b.name, optional: !!b.optional, items: [] }));
    for (const st of s.steps) {
      if (st.kind !== 'work' || !blocks[st.b]) continue;
      let status = 'todo';
      if (skipped.has(st.i)) status = 'skipped';
      else if (st.i < s.cur || (s.finished && s.status === 'end' && st.i <= s.cur)) status = 'done';
      else if (st.i === s.cur && !s.finished) status = 'current';
      else if (nw && st.i === nw.i) status = 'next';
      blocks[st.b].items.push({ i: st.i, name: st.name, detail: st.detail, round: st.round, rounds: st.rounds,
                                img: st.img, status });
    }
    return blocks;
  }

  function view(s, now) {
    const st = s.steps[s.cur] || null;
    const eff = s.paused ? s.pausedAt : now;
    const elapsed = st ? Math.max(0, (eff - s.stepStart) / 1000) : 0;
    const blocks = s.workout.blocks || [];
    let remaining = null;
    if (st && (st.mode === 'timer' || st.mode === 'amrap')) remaining = Math.max(0, st.dur - elapsed);
    if (st && st.mode === 'up' && st.dur) remaining = Math.max(0, st.dur - elapsed);
    const inBlock = st ? s.steps.filter((x) => x.b === st.b) : [];
    return {
      step: st, next: s.steps[s.cur + 1] || null, block: st ? blocks[st.b] : null,
      blockIdx: st ? st.b : -1, nBlocks: blocks.length,
      stepInBlock: st ? st.bs : -1, stepsInBlock: inBlock.length,
      elapsed, remaining, total: s.t0 ? Math.max(0, ((s.finished ? lastT(s) : eff) - s.t0) / 1000) : 0,
      rounds: s.rounds, marked: s.marked, paused: s.paused, finished: s.finished,
      progress: s.steps.length ? Math.max(0, s.cur) / s.steps.length : 0,
    };
  }

  function lastT(s) { return s.events.length ? s.events[s.events.length - 1].t : 0; }

  // --- debrief a fine seduta --------------------------------------------------
  /* Domande del coach (w.debrief: [{id, q, options:[...]}]); se mancano, le tre fisse.
     Le domande sull'alzata principale le scrive il coach nella scheda del giorno. */
  const WOD_TYPES = ['emom', 'interval', 'amrap', 'fortime'];
  function debriefQuestions(w) {
    const ok = (x) => x && typeof x.id === 'string' && typeof x.q === 'string' && Array.isArray(x.options) && x.options.length;
    if (Array.isArray(w.debrief) && w.debrief.length) return w.debrief.filter(ok).slice(0, 8);
    const qs = [];
    if ((w.blocks || []).some((b) => WOD_TYPES.includes(b.type))) qs.push({ id: 'wod', q: 'Il WOD?', options: ['love', 'ok', 'meh', 'no'] });
    qs.push({ id: 'energy', q: 'Energia adesso?', options: ['bassa', 'ok', 'alta'] });
    qs.push({ id: 'tomorrow', q: 'Domani?', options: ['come da piano', 'più facile', 'off'] });
    return qs;
  }

  // --- log compatto per sendData (limite 4096 byte) --------------------------

  function byteLen(str) { return new TextEncoder().encode(str).length; }

  /* from > 0: manda solo gli eventi da `from` in poi (continuazione di una seduta già inviata);
     il bot la riconosce da `cont` = t0 della seduta originale e la unisce. */
  function encodeLog(s, maxBytes, from) {
    maxBytes = maxBytes || 4096; from = from > 0 && from < s.events.length ? from : 0;
    const evs = s.events.slice(from);
    const w = s.workout, t0 = evs.length ? evs[0].t : 0;
    const used = [...new Set(evs.map((e) => e.s))].sort((a, b) => a - b);
    const E = evs.map((ev) => {
      const a = [Math.round((ev.t - t0) / 1000), EVENTS.indexOf(ev.e), ev.s];
      const f = (ev.auto ? 1 : 0) | (ev.reopen ? 2 : 0) | (ev.cont ? 4 : 0);
      if (f) a.push(f);
      return a;
    });
    const build = (labelLen, events, trunc) => {
      const S = used.map((i) => {
        const st = s.steps[i], row = [i, st.b, KINDS[st.kind]];
        if (labelLen) row.push(stepLabel(st).slice(0, labelLen));
        return row;
      });
      const o = { v: 1, d: w.date, n: (w.title || '').slice(0, 60), t0,
                  st: s.status || 'open', B: (w.blocks || []).map((b) => (b.name || '').slice(0, 30)), S, E: events };
      if (trunc) o.tr = trunc;
      if (w.demo) o.demo = 1;
      if (from) o.cont = s.events[0].t;
      if (s.debrief && s.debrief.answers && Object.keys(s.debrief.answers).length) o.q = s.debrief.answers;
      if (s.debrief && s.debrief.note) o.nt = String(s.debrief.note).slice(0, 280);
      return JSON.stringify(o);
    };
    for (const len of [48, 24, 12, 0]) {
      const out = build(len, E);
      if (byteLen(out) <= maxBytes) return out;
    }
    // ultima difesa: tieni gli eventi più recenti (il primo resta: è t0)
    let keep = E.length;
    while (keep > 2) {
      keep = Math.floor(keep * 0.8);
      const ev = [E[0]].concat(E.slice(E.length - keep + 1));
      const out = build(0, ev, E.length - ev.length);
      if (byteLen(out) <= maxBytes) return out;
    }
    return build(0, [E[0], E[E.length - 1]], E.length - 2);
  }

  function decodeLog(str) {
    const o = JSON.parse(str);
    return { date: o.d, title: o.n, t0: o.t0, status: o.st, demo: !!o.demo, cont: o.cont || 0,
             debrief: o.q || o.nt ? { answers: o.q || {}, note: o.nt || '' } : null,
             events: o.E.map((a) => {
               const ev = { t: o.t0 + a[0] * 1000, e: EVENTS[a[1]], s: a[2] };
               if (a[3] & 1) ev.auto = 1;
               if (a[3] & 2) ev.reopen = 1;
               if (a[3] & 4) ev.cont = 1;
               return ev;
             }) };
  }

  // --- workout nel fragment ---------------------------------------------------

  function b64urlEncode(bytes) {
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function b64urlDecode(str) {
    str = str.replace(/-/g, '+').replace(/_/g, '/');
    while (str.length % 4) str += '=';
    const bin = atob(str), out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function encodeWorkout(w) {
    return 'w=' + b64urlEncode(new TextEncoder().encode(JSON.stringify(w)));
  }

  async function inflateRaw(bytes) {
    if (typeof DecompressionStream === 'undefined') throw new Error('DecompressionStream assente');
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  /* hash "#w=…" o "#z=…" (deflate-raw), anche mescolato ai parametri tgWebApp*. */
  async function parseFragment(hash) {
    const params = {};
    String(hash || '').replace(/^#/, '').split('&').forEach((kv) => {
      const k = kv.split('=')[0];
      if (k) params[k] = kv.slice(k.length + 1);
    });
    let bytes;
    if (params.z) bytes = await inflateRaw(b64urlDecode(params.z));
    else if (params.w) bytes = b64urlDecode(params.w);
    else return null;
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  function workoutId(w) {
    const str = JSON.stringify(w);
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 0x01000193); }
    return (h >>> 0).toString(36);
  }

  function validateWorkout(w) {
    const errs = [];
    if (!w || typeof w !== 'object') return ['workout non è un oggetto'];
    if (!Array.isArray(w.blocks) || !w.blocks.length) errs.push('blocks mancante o vuoto');
    (w.blocks || []).forEach((b, i) => {
      const p = 'blocco ' + (i + 1);
      if (!TYPES.includes(b.type)) errs.push(p + ': type sconosciuto ' + b.type);
      if (!Array.isArray(b.exercises) || !b.exercises.length) errs.push(p + ': exercises vuoto');
      if (b.type === 'emom' && !(b.minutes > 0)) errs.push(p + ': minutes');
      if (b.type === 'interval' && !(b.work_s > 0)) errs.push(p + ': work_s');
      if (b.type === 'amrap' && !(b.duration_s > 0)) errs.push(p + ': duration_s');
    });
    return errs;
  }

  return { debriefQuestions, voiceSlug, EVENTS, KINDS, AUTO_LAG_MS, TAP_GUARD_MS, abandon, reopen, continueStep, continueAt, CONTINUE_MAX_MS, lastT, nextWork, imgFrames, sheet, fmtTime, buildTimeline, stepLabel, createSession, apply, replay,
           tick, start, pause, resume, skip, done, round, stop, view, encodeLog, decodeLog, byteLen,
           b64urlEncode, b64urlDecode, encodeWorkout, parseFragment, workoutId, validateWorkout };
});
