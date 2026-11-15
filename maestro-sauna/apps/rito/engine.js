/* Rito — motore del tempo di un rituale (la sauna oggi), puro e testabile (node --test).
 *
 * Un rito è una sequenza di momenti. Ogni momento finisce con un tocco («Sono uscito») o da solo,
 * a tempo. Il tempo è sempre orologio reale: l'inizio del momento è un istante (ms epoch), il resto
 * si calcola. Lo stato si ricava dal log degli eventi (apply/replay): il log è l'unica cosa da
 * salvare per riprendere un rito interrotto, ed è quello che torna a chi ha scritto la partitura.
 *
 * Fra un momento e l'altro c'è un passaggio: i secondi (o il minuto) che servono per arrivare —
 * raggiungere l'acqua, asciugarsi e sdraiarsi. Durante il passaggio il tempo del momento non corre;
 * parte da solo alla fine del passaggio, o prima con un tocco («Ci sono»).
 * Il calore fa eccezione: chi ha toccato «Entro» è già dentro, quindi il suo tempo — e il limite —
 * contano dal tocco. Il suo passaggio è solo il tempo per sistemarsi: il gong d'inizio suona dopo.
 *
 * Sicurezza: caldo e freddo finiscono solo con un tocco (mai da soli), hanno sempre un massimo, non
 * si mettono in pausa, e se la pagina torna dopo una chiusura il loro tempo è continuato. Il
 * telefono resta comunque un aiuto, non un dispositivo di sicurezza: in cabina c'è la clessidra.
 *
 * Il motore non decide niente del rito: durate, limiti e suoni sono nella partitura. Lascia
 * accorciare sempre (il corpo decide), non lascia saltare il riposo senza un secondo tocco, e oltre
 * il massimo di un momento chiama finché non si esce.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RitoEngine = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const EVENTS = ['start', 'enter', 'tap', 'auto', 'skip', 'pause', 'resume', 'undo', 'stop', 'end', 'begin'];
  const TYPES = ['prep', 'heat', 'air', 'cold', 'rest', 'close'];
  const BEDS = ['silenzio', 'brace', 'bordone', 'acqua', 'aria', 'respiro'];
  const SHOTS = ['gong', 'tingsha', 'ciotola', 'campanella', 'legno', 'vapore', 'goccia'];
  const DRINK_AT_S = 60;           // `drink`: un sorso d'acqua un minuto dopo l'inizio del momento
  const DRINK_TEXT = 'Un sorso d\'acqua.';

  const TAP_GUARD_MS = 700;        // tocchi ignorati subito dopo un cambio di momento (doppio tocco)
  const QUICK_EXIT_S = 20;         // uscire dal caldo o dal freddo nei primi secondi vuole un secondo tocco (dita bagnate)
  const UNDO_MS = 15000;           // «ho toccato per sbaglio»: si torna indietro entro 15 s
  const AUTO_LAG_MS = 2000;        // passaggio a tempo registrato in ritardo (pagina sospesa)
  const LATE_MS = 4000;            // un suono dovuto da più di tanto non si suona più (tranne il richiamo)
  const MAX_REPEAT_S = 30;         // oltre il massimo il richiamo torna ogni 30 s
  const REOPEN_GAP_MS = 20 * 60000; // pagina chiusa da più di 20': al ritorno il rito è in pausa da allora

  // lead = il passaggio: secondi per arrivare al momento prima che il suo tempo cominci
  const DEFAULTS = {
    prep:  { sound: 'bordone',  enter: null,         done: 'Entro',          lead: 0,  arrive: '' },
    heat:  { sound: 'brace',    enter: 'tingsha',    done: 'Sono uscito',    lead: 30, arrive: 'Entra, chiudi la porta, stenditi.' },
    air:   { sound: 'aria',     enter: 'legno',      done: 'Avanti',         lead: 15, arrive: 'Esci all\'aria, senza fretta.' },
    cold:  { sound: 'acqua',    enter: 'campanella', done: 'Fatto',          lead: 30, arrive: 'Vai all\'acqua con calma.' },
    rest:  { sound: 'respiro',  enter: 'ciotola',    done: 'Mi alzo',        lead: 60, arrive: 'Asciugati, copriti, stenditi.' },
    close: { sound: 'bordone',  enter: 'ciotola',    done: 'Chiudi il rito', lead: 0,  arrive: '' },
  };
  const NO_HOLD = ['heat', 'cold'];   // dal caldo e dal freddo si esce quando lo dice il corpo; niente pause, niente fine a tempo
  const LEAD_MAX = { heat: 60, cold: 120 };   // gli altri 300

  // --- partitura -------------------------------------------------------------

  function num(v) { return typeof v === 'number' && isFinite(v) ? v : null; }
  function str(v, max) { return typeof v === 'string' && v.length > 0 && v.length <= max; }
  function optStr(v, max) { return v == null || (typeof v === 'string' && v.length <= max); }

  /* Errori della partitura (lista vuota = si può suonare). */
  function validate(r) {
    const errs = [];
    if (!r || typeof r !== 'object') return ['il rito deve essere un oggetto'];
    if (r.v !== 1) errs.push('v deve essere 1');
    if (!Array.isArray(r.moments) || !r.moments.length) return errs.concat('moments mancante o vuoto');
    if (r.moments.length > 40) errs.push('al massimo 40 momenti');
    const ids = new Set();
    r.moments.forEach((m, k) => {
      const p = 'momento ' + (k + 1);
      if (!m || typeof m !== 'object') { errs.push(p + ': deve essere un oggetto'); return; }
      if (typeof m.id !== 'string' || !/^[a-z0-9-]{1,24}$/.test(m.id)) errs.push(p + ': id deve essere uno slug (a-z, 0-9, -)');
      else if (ids.has(m.id)) errs.push(p + ': id ripetuto ' + m.id);
      ids.add(m.id);
      if (!str(m.name, 40)) errs.push(p + ': name mancante o oltre 40 caratteri');
      if (!TYPES.includes(m.type)) errs.push(p + ': type ' + JSON.stringify(m.type) + ' non tra ' + TYPES.join(', '));
      const hot = NO_HOLD.includes(m.type);
      const end = m.end == null ? 'tap' : m.end;
      if (end !== 'tap' && end !== 'time') errs.push(p + ': end deve essere tap o time');
      else if (end === 'time' && hot) errs.push(p + ': caldo e freddo finiscono solo con un tocco (end: tap), mai da soli');
      if (m.optional != null && typeof m.optional !== 'boolean') errs.push(p + ': optional deve essere true o false');
      if (m.optional === true && m.type === 'rest') errs.push(p + ': il riposo non si salta (niente optional)');
      if (m.temp_c != null && !(num(m.temp_c) > 0)) errs.push(p + ': temp_c deve essere un numero');
      if (m.temp_c != null && m.type !== 'heat') errs.push(p + ': temp_c vale solo per il calore');
      if (m.sound === 'brace' && m.type !== 'heat') errs.push(p + ': il tappeto brace è del calore');
      if (m.breath != null) {
        const b = m.breath;
        if (typeof b !== 'object' || Array.isArray(b) || !(num(b.in_s) >= 2 && b.in_s <= 15 && num(b.out_s) >= 2 && b.out_s <= 15))
          errs.push(p + ': breath vuole in_s e out_s fra 2 e 15 secondi');
      }
      for (const k2 of ['where', 'done_label']) if (!optStr(m[k2], 40)) errs.push(p + ': ' + k2 + ' è un testo di al massimo 40 caratteri');
      if (!optStr(m.detail, 160)) errs.push(p + ': detail è un testo di al massimo 160 caratteri');
      if (m.img != null && !(typeof m.img === 'string' && /^[a-z0-9-]{1,40}$/.test(m.img))) errs.push(p + ': img è il nome di una figura (lettere minuscole, cifre, trattini)');
      if (m.checklist != null && !(Array.isArray(m.checklist) && m.checklist.length >= 1 && m.checklist.length <= 8
          && m.checklist.every((x) => str(x, 60)))) errs.push(p + ': checklist è una lista da 1 a 8 voci brevi (60 caratteri)');
      if (m.checklist != null && hot) errs.push(p + ': la checklist non sta nel caldo né nel freddo');
      if (m.drink != null && typeof m.drink !== 'boolean') errs.push(p + ': drink deve essere true o false');
      if (m.drink === true && hot) errs.push(p + ': nel caldo e nel freddo non si beve: drink va nei riposi, nell\'aria, prima o dopo');
      const mn = num(m.min_s), tg = num(m.target_s), mx = num(m.max_s);
      for (const [k2, v] of [['min_s', m.min_s], ['target_s', m.target_s], ['max_s', m.max_s]]) {
        if (v != null && !(num(v) > 0)) errs.push(p + ': ' + k2 + ' deve essere un numero > 0');
      }
      if (end === 'time' && !(tg > 0)) errs.push(p + ': un momento a tempo vuole target_s');
      if ((m.type === 'heat' || m.type === 'cold') && !(mx > 0)) errs.push(p + ': caldo e freddo vogliono max_s (il limite oltre cui si viene richiamati)');
      if (mn && tg && mn > tg) errs.push(p + ': min_s oltre target_s');
      if (tg && mx && tg > mx) errs.push(p + ': target_s oltre max_s');
      if (mn && mx && mn > mx) errs.push(p + ': min_s oltre max_s');
      if (m.sound != null && !BEDS.includes(m.sound)) errs.push(p + ': sound non tra ' + BEDS.join(', '));
      if (m.enter_sound != null && m.enter_sound !== false && !SHOTS.includes(m.enter_sound)) errs.push(p + ': enter_sound non tra ' + SHOTS.join(', '));
      if (m.enter_sound === 'gong') errs.push(p + ': il gong è del richiamo oltre il limite, non apre un momento');
      if (!optStr(m.text, 400)) errs.push(p + ': text è un testo di al massimo 400 caratteri');
      const lmax = LEAD_MAX[m.type] || 300;
      if (m.lead_s != null && !(num(m.lead_s) !== null && m.lead_s >= 0 && m.lead_s <= lmax)) errs.push(p + ': lead_s (il passaggio) va da 0 a ' + lmax + ' secondi');
      if (!optStr(m.lead_text, 200)) errs.push(p + ': lead_text è un testo di al massimo 200 caratteri');
      if (m.cues != null) {
        if (!Array.isArray(m.cues) || m.cues.length > 12) errs.push(p + ': cues è una lista di al massimo 12');
        else m.cues.forEach((c, j) => {
          const q = p + ' richiamo ' + (j + 1);
          if (!c || typeof c !== 'object' || num(c.at_s) === null || c.at_s < 0) { errs.push(q + ': at_s mancante'); return; }
          const lim = mx || tg;
          if (lim && c.at_s >= lim) errs.push(q + ': at_s oltre la fine del momento');
          if (c.sound != null && !SHOTS.includes(c.sound)) errs.push(q + ': sound non tra ' + SHOTS.join(', '));
          if (!optStr(c.say, 200)) errs.push(q + ': say è un testo di al massimo 200 caratteri');
          if (!optStr(c.text, 200)) errs.push(q + ': text è un testo di al massimo 200 caratteri');
          if (c.sound == null && c.say == null && c.text == null) errs.push(q + ': serve sound, say o text');
        });
      }
    });
    if (r.prepare != null && !(Array.isArray(r.prepare) && r.prepare.length >= 1 && r.prepare.length <= 12
        && r.prepare.every((x) => str(x, 60)))) errs.push('prepare è una lista da 1 a 12 cose da preparare (60 caratteri)');
    if (r.closing != null) {
      if (!Array.isArray(r.closing) || r.closing.length > 5) errs.push('closing è una lista di al massimo 5 domande');
      else r.closing.forEach((c, j) => {
        const q = 'domanda ' + (j + 1);
        if (!c || typeof c.id !== 'string' || !/^[a-z0-9_-]{1,20}$/.test(c.id)) errs.push(q + ': id mancante');
        if (!c || !str(c.q, 120)) errs.push(q + ': q mancante o oltre 120 caratteri');
        if (!c || !Array.isArray(c.options) || c.options.length < 2 || c.options.length > 5
            || c.options.some((o) => typeof o !== 'string' || !o || o.length > 30)) errs.push(q + ': da 2 a 5 opzioni brevi');
      });
    }
    return errs;
  }

  /* I momenti con i valori predefiniti del loro tipo. */
  function timeline(r) {
    let round = 0;
    return (r.moments || []).map((m, i) => {
      const d = DEFAULTS[m.type] || DEFAULTS.prep;
      if (m.type === 'heat') round += 1;
      return {
        i, id: m.id, name: String(m.name || ''), type: m.type, where: m.where || '',
        text: m.text || '', detail: m.detail || '', img: m.img || '', end: m.end || 'tap',
        min_s: num(m.min_s), target_s: num(m.target_s), max_s: num(m.max_s),
        optional: !!m.optional, sound: m.sound || d.sound,
        enter_sound: m.enter_sound === false ? null : (m.enter_sound || d.enter),
        done_label: m.done_label || d.done, checklist: Array.isArray(m.checklist) ? m.checklist : [],
        cues: (Array.isArray(m.cues) ? m.cues : []).concat(m.drink === true
          && !(num(m.target_s) && m.end === 'time' && m.target_s <= DRINK_AT_S)
          ? [{ at_s: Math.min(DRINK_AT_S, num(m.target_s) ? m.target_s / 2 : DRINK_AT_S), sound: 'goccia', text: DRINK_TEXT, drink: true }] : []),
        // il calore conta dal tocco: il suo passaggio è solo il tempo per sistemarsi (settle_s), non ferma l'orologio
        lead_s: i === 0 || m.type === 'heat' ? 0 : (num(m.lead_s) != null ? m.lead_s : d.lead),
        settle_s: i === 0 || m.type !== 'heat' ? 0 : (num(m.lead_s) != null ? m.lead_s : d.lead),
        lead_text: m.lead_text || d.arrive,
        breath: m.breath || null, temp_c: num(m.temp_c), round: m.type === 'heat' ? round : 0,
      };
    });
  }

  /* Il rito come è scritto: per la soglia e per chi lo legge prima di cominciare. */
  function planned(r) {
    const tl = timeline(r);
    const sum = (t) => tl.filter((m) => m.type === t).reduce((a, m) => a + (m.target_s || m.max_s || 0), 0);
    // cosa preparare: la lista del Maestro, più quello che il rito chiede da sé (acqua, tinozza)
    const prep = Array.isArray(r.prepare) ? r.prepare.slice() : [];
    const has = (re) => prep.some((x) => re.test(x));
    if (tl.some((m) => m.cues.some((c) => c.drink)) && !has(/acqua|bere|bottiglia|borraccia/i)) prep.push('Acqua da bere a portata di mano');
    if (tl.some((m) => m.type === 'cold') && !has(/tinozza|fredd|doccia/i)) prep.push('L\'acqua fredda pronta');
    return {
      prepare: prep,
      rounds: tl.filter((m) => m.type === 'heat').length,
      heat_s: sum('heat'), cold_s: sum('cold'), rest_s: sum('rest'),
      total_s: tl.reduce((a, m) => a + (m.target_s || m.min_s || 0) + m.lead_s, 0),
      moments: tl.map((m) => ({ id: m.id, name: m.name, type: m.type, target_s: m.target_s, max_s: m.max_s, optional: m.optional })),
    };
  }

  // --- sessione ---------------------------------------------------------------

  function createSession(rito) {
    return { rito, tl: timeline(rito), events: [], t0: 0, cur: -1, mStart: 0, entered: 0,
      paused: false, pausedAt: 0, finished: false, status: null, recs: [], prev: null, lastTapT: 0, fired: {} };
  }

  function closeRec(s, t, how) {
    const rec = s.recs[s.recs.length - 1];
    if (rec && rec.end == null) { rec.end = Math.max(t, rec.start); rec.how = how; }   // chiuso nel passaggio: durata zero
  }

  function apply(s, ev) {
    s.events.push(ev);
    switch (ev.e) {
      case 'start': s.t0 = ev.t; break;
      case 'enter': {
        const lead = ((s.tl[ev.m] || {}).lead_s || 0) * 1000;       // il tempo del momento parte dopo il passaggio
        s.cur = ev.m; s.mStart = ev.t + lead; s.entered = ev.t;
        s.recs.push({ i: ev.m, start: ev.t + lead, paused: 0 });
        break;
      }
      case 'begin': {                                              // «Ci sono»: il passaggio finisce adesso
        s.mStart = ev.t; s.entered = ev.t;
        const rec = s.recs[s.recs.length - 1];
        if (rec && rec.end == null) rec.start = ev.t;
        break;
      }
      case 'tap': case 'skip': case 'auto':
        s.prev = ev.e === 'auto' ? null : { cur: s.cur, mStart: s.mStart };
        if (ev.e !== 'auto') s.lastTapT = ev.t;
        closeRec(s, ev.t, ev.e);
        break;
      case 'undo': {
        if (!s.prev) break;
        const last = s.recs[s.recs.length - 1];
        if (last && last.i !== s.prev.cur) s.recs.pop();          // il momento appena aperto non è mai esistito
        const rec = s.recs[s.recs.length - 1];
        if (rec) { delete rec.end; delete rec.how; }
        s.cur = s.prev.cur; s.mStart = s.prev.mStart; s.entered = ev.t;
        s.prev = null; s.finished = false; s.status = null;
        break;
      }
      case 'pause': s.paused = true; s.pausedAt = ev.t; break;
      case 'resume': {
        const d = ev.t - s.pausedAt;
        const lead = s.pausedAt < s.mStart;                        // pausa nel passaggio: si sposta l'inizio, non è tempo del momento
        s.mStart += d; s.paused = false;
        const rec = s.recs[s.recs.length - 1];
        if (rec && rec.end == null) { if (lead) rec.start += d; else rec.paused += d; }
        break;
      }
      case 'stop': closeRec(s, ev.t, 'stop'); s.finished = true; s.status = 'stop'; s.paused = false; break;
      case 'end': s.finished = true; s.status = 'end'; s.cur = s.tl.length; break;
    }
    return s;
  }

  function emit(s, e, t, m, f) {
    const ev = { t, e };
    if (m != null) ev.m = m;
    if (f) ev.f = f;
    return apply(s, ev);
  }

  function replay(rito, events) {
    const s = createSession(rito);
    for (const ev of events || []) apply(s, ev);
    return s;
  }

  function live(s) { return s.cur >= 0 && !s.finished; }
  function moment(s) { return live(s) ? s.tl[s.cur] : null; }
  function elapsed(s, now) { return live(s) ? ((s.paused ? s.pausedAt : now) - s.mStart) / 1000 : 0; }

  function advance(s, t, how, f) {
    const i = s.cur;
    emit(s, how, t, i, f);
    if (i + 1 < s.tl.length) emit(s, 'enter', t, i + 1, f);
    else emit(s, 'end', t);
  }

  function start(s, now) {
    if (s.cur >= 0 || s.finished || !s.tl.length) return false;
    emit(s, 'start', now);
    emit(s, 'enter', now, 0);
    return true;
  }

  /* Suoni dovuti nel momento corrente e non ancora suonati. */
  function due(s, m, el, out) {
    const key = (x) => m.i + ':' + x;
    m.cues.forEach((c, j) => {
      if (el >= c.at_s && !s.fired[key('c' + j)]) {
        s.fired[key('c' + j)] = 1;
        out.push({ kind: 'cue', m: m.i, cue: c, late: (el - c.at_s) * 1000 > LATE_MS });
      }
    });
    if (m.end === 'tap' && m.target_s && el >= m.target_s && !s.fired[key('t')]) {
      s.fired[key('t')] = 1;
      out.push({ kind: 'target', m: m.i, late: (el - m.target_s) * 1000 > LATE_MS });
    }
    if (m.max_s && el >= m.max_s) {
      const n = Math.floor((el - m.max_s) / MAX_REPEAT_S);
      if (!s.fired[key('x' + n)]) {
        for (let k = 0; k <= n; k++) s.fired[key('x' + k)] = 1;
        out.push({ kind: 'max', m: m.i, n, late: false });   // il richiamo oltre il limite suona sempre
      }
    }
  }

  /* Fa scorrere il tempo fino a `now`: passaggi a tempo e suoni dovuti. Torna ciò che è successo,
     perché la pagina lo suoni. */
  function tick(s, now) {
    const out = [];
    if (!live(s) || s.paused) return out;
    for (let guard = 0; guard < 200; guard++) {
      const m = s.tl[s.cur];
      const el = (now - s.mStart) / 1000;
      if (el < 0) break;                                           // ancora nel passaggio
      if ((m.lead_s || m.settle_s) && el >= m.settle_s && !s.fired[m.i + ':b']) {   // il momento comincia: il suo colpo
        s.fired[m.i + ':b'] = 1;
        out.push({ kind: 'begin', m: m.i, late: (el - m.settle_s) * 1000 > LATE_MS });
      }
      due(s, m, el, out);
      if (m.end === 'time' && el >= m.target_s) {
        const t = s.mStart + m.target_s * 1000;
        const lag = now - t;
        advance(s, t, 'auto', lag > AUTO_LAG_MS ? 1 : 0);
        if (s.finished) { out.push({ kind: 'end', late: lag > LATE_MS }); break; }
        out.push({ kind: 'enter', m: s.cur, late: lag > LATE_MS });
        continue;
      }
      break;
    }
    return out;
  }

  /* Il tocco che chiude il momento. Torna 'ok', oppure perché no:
     'stale' (la pagina mostrava un altro momento), 'guard' (doppio tocco), 'early' (c'è un minimo:
     serve un secondo tocco con force), false (non è il momento di toccare). */
  function tap(s, now, expected, force) {
    if (!live(s) || s.paused) return false;
    if (expected != null && expected !== s.cur) return 'stale';
    if (now - s.entered < TAP_GUARD_MS) return 'guard';
    const m = s.tl[s.cur];
    if (now < s.mStart) {                                          // nel passaggio il tocco vuol dire «ci sono»
      s.fired[m.i + ':b'] = 1;
      emit(s, 'begin', now, s.cur);
      return 'begin';
    }
    const hot = NO_HOLD.includes(m.type), el = elapsed(s, now);
    if (hot && el < QUICK_EXIT_S && !force) return 'early';        // tre tocchi di fila non devono chiudere un calore
    if (m.min_s && el < m.min_s && !hot && !force) return 'early';
    advance(s, now, 'tap');
    return 'ok';
  }

  function skip(s, now, expected) {
    if (!live(s) || s.paused) return false;
    if (expected != null && expected !== s.cur) return 'stale';
    if (!s.tl[s.cur].optional) return false;
    advance(s, now, 'skip');
    return 'ok';
  }

  function canUndo(s, now) { return !!s.prev && now - s.lastTapT <= UNDO_MS && s.status !== 'stop'; }

  function undo(s, now) {
    if (!canUndo(s, now)) return false;
    const left = s.cur;                                            // il momento che si abbandona non è mai cominciato
    emit(s, 'undo', now);
    if (left !== s.cur) for (const k of Object.keys(s.fired)) if (k.indexOf(left + ':') === 0) delete s.fired[k];
    return true;
  }

  function canPause(s) { return live(s) && !s.paused && !NO_HOLD.includes(s.tl[s.cur].type); }

  /* Nel caldo e nel freddo non c'è pausa: il tempo del corpo non si ferma. */
  function pause(s, now) {
    if (!canPause(s)) return false;
    emit(s, 'pause', now, s.cur);
    return true;
  }

  function resume(s, now) {
    if (!live(s) || !s.paused) return false;
    emit(s, 'resume', now, s.cur);
    return true;
  }

  function stop(s, now) {
    if (!live(s)) return false;
    if (s.paused) emit(s, 'resume', now, s.cur);
    emit(s, 'stop', now, s.cur);
    return true;
  }

  /* La pagina è tornata dopo una chiusura lunga: il rito risulta in pausa da quando era stata vista. */
  function reopen(s, lastSeen, now) {
    if (!live(s) || s.paused || !lastSeen || now - lastSeen <= REOPEN_GAP_MS) return false;
    if (NO_HOLD.includes(s.tl[s.cur].type)) return false;          // caldo e freddo: il tempo è continuato, il richiamo suona
    emit(s, 'pause', Math.max(lastSeen, s.mStart), s.cur, 2);
    return true;
  }

  // --- cosa mostrare ----------------------------------------------------------

  function view(s, now) {
    if (s.cur < 0) return { phase: 'intro', n: s.tl.length };
    if (s.finished) return { phase: 'closing', status: s.status, n: s.tl.length, canUndo: canUndo(s, now) };
    const m = s.tl[s.cur];
    const raw = elapsed(s, now), el = Math.max(0, raw);
    const ref = m.target_s || m.max_s || null;
    return {
      phase: 'run', i: s.cur, n: s.tl.length, m, elapsed_s: el, paused: s.paused,
      lead: raw < 0, lead_remain_s: raw < 0 ? -raw : 0,
      settling: !!(m.settle_s && raw >= 0 && el < m.settle_s), can_pause: canPause(s),
      frac: ref ? Math.min(1, el / ref) : null,
      remain_s: m.target_s ? Math.max(0, m.target_s - el) : null,
      over: !!(m.target_s && el >= m.target_s), over_max: !!(m.max_s && el >= m.max_s),
      hold: !!(m.min_s && el < m.min_s && !NO_HOLD.includes(m.type)),
      quick: NO_HOLD.includes(m.type) && raw >= 0 && el < QUICK_EXIT_S,
      can_skip: m.optional, canUndo: canUndo(s, now), next: s.tl[s.cur + 1] || null,
      label: raw < 0 ? 'Ci sono' : m.done_label,
    };
  }

  function minutes(sec) {
    const m = Math.round(sec / 60);
    return m <= 0 ? 'meno di un minuto' : m === 1 ? 'un minuto' : m + ' minuti';
  }

  /* Com'è andata davvero: un rigo per momento, e i totali. */
  function summary(s) {
    const last = {};
    for (const r of s.recs) last[r.i] = r;
    const moments = s.tl.map((m) => {
      const r = last[m.i];
      const actual = r && r.end != null ? Math.max(0, Math.round((r.end - r.start - r.paused) / 1000)) : null;
      return { id: m.id, name: m.name, type: m.type, planned_s: m.target_s || null, max_s: m.max_s || null,
        actual_s: r ? (r.how === 'skip' ? 0 : actual) : null, ended: r ? (r.how || 'open') : 'never' };
    });
    const tot = (t) => moments.filter((x) => x.type === t).reduce((a, x) => a + (x.actual_s || 0), 0);
    const ev = s.events;
    return { status: s.status || (s.cur < 0 ? 'intro' : 'run'), moments,
      rounds: moments.filter((x) => x.type === 'heat' && x.actual_s > 0).length,
      heat_s: tot('heat'), cold_s: tot('cold'), air_s: tot('air'), rest_s: tot('rest'),
      started: ev.length ? ev[0].t : null, ended: ev.length ? ev[ev.length - 1].t : null };
  }

  // --- andata e ritorno -------------------------------------------------------

  function byteLen(str) { return new TextEncoder().encode(str).length; }

  /* Il log che torna al canale (sendData ≤ 4096 byte). */
  function encodeLog(s, answers, note, maxBytes) {
    const max = maxBytes || 4096, t0 = s.t0 || 0, r = s.rito || {};
    const o = { v: 1, k: 'rito', d: r.date || null, n: r.title || '', t0, st: s.status || 'run',
      M: s.tl.map((m) => [m.id, m.type, m.target_s || 0, m.max_s || 0, m.lead_s || 0]),
      E: s.events.map((ev) => [Math.round((ev.t - t0) / 1000), EVENTS.indexOf(ev.e), ev.m == null ? -1 : ev.m].concat(ev.f ? [ev.f] : [])) };
    // A: com'è andato ogni momento (secondi veri, come è finito): vale anche se gli eventi vengono tagliati
    o.A = summary(s).moments.map((m) => [m.actual_s == null ? -1 : m.actual_s, m.ended]);
    if (r.demo) o.demo = 1;
    if (answers && Object.keys(answers).length) o.q = answers;
    if (note) o.nt = String(note).slice(0, 280);
    let out = JSON.stringify(o);
    if (byteLen(out) > max && o.nt) { delete o.nt; out = JSON.stringify(o); }
    if (byteLen(out) > max) { o.n = ''; out = JSON.stringify(o); }
    let tr = 0;
    while (byteLen(out) > max && o.E.length > 2) {                 // via gli eventi dal mezzo: restano primo, ultimo e il riassunto A
      o.E.splice(Math.floor(o.E.length / 2), 1); tr += 1; o.tr = tr; out = JSON.stringify(o);
    }
    return out;
  }

  function decodeLog(str) {
    const o = JSON.parse(str);
    if (o.v !== 1 || o.k !== 'rito') throw new Error('non è il log di un rito');
    return { date: o.d, title: o.n, t0: o.t0, status: o.st, demo: !!o.demo, answers: o.q || {}, note: o.nt || '',
      truncated: o.tr || 0, actual: (o.A || []).map((x) => ({ actual_s: x[0] < 0 ? null : x[0], ended: x[1] })),
      moments: (o.M || []).map((x) => ({ id: x[0], type: x[1], target_s: x[2] || 0, max_s: x[3] || 0, lead_s: x[4] || 0 })),
      events: (o.E || []).map((a) => ({ t: o.t0 + a[0] * 1000, e: EVENTS[a[1]], m: a[2] < 0 ? null : a[2], f: a[3] || 0 })) };
  }

  function b64urlEncode(bytes) {
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function b64urlDecode(str) {
    const b = atob(String(str).replace(/-/g, '+').replace(/_/g, '/'));
    const out = new Uint8Array(b.length);
    for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i);
    return out;
  }

  /* La partitura nel fragment dell'URL: non arriva a nessun server. */
  function encodeRito(r) { return 'r=' + b64urlEncode(new TextEncoder().encode(JSON.stringify(r))); }

  /* `#r=<base64url del JSON>` oppure `#z=<deflate-raw>` → partitura (o null). */
  async function parseFragment(hash) {
    const h = String(hash || '').replace(/^#/, '');
    for (const part of h.split('&')) {
      const k = part.slice(0, 2), v = part.slice(2);
      if (k === 'r=' && v) return JSON.parse(new TextDecoder().decode(b64urlDecode(v)));
      if (k === 'z=' && v) {
        const ds = new DecompressionStream('deflate-raw');
        const stream = new Blob([b64urlDecode(v)]).stream().pipeThrough(ds);
        return JSON.parse(await new Response(stream).text());
      }
    }
    return null;
  }

  /* Chiave stabile del rito, per ritrovarlo salvato sul telefono. */
  function ritoId(r) {
    const str = JSON.stringify(r);
    let h = 5381;
    for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) >>> 0;
    return (r.date || 'rito') + '_' + h.toString(36);
  }

  return { EVENTS, TYPES, BEDS, SHOTS, UNDO_MS, MAX_REPEAT_S, REOPEN_GAP_MS,
    validate, timeline, planned, createSession, apply, replay, live, moment, elapsed,
    start, tick, tap, skip, undo, canUndo, canPause, pause, resume, stop, reopen, view, minutes, summary, QUICK_EXIT_S,
    encodeLog, decodeLog, encodeRito, parseFragment, b64urlEncode, b64urlDecode, ritoId };
});
