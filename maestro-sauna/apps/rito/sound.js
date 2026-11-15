/* Rito — i suoni, sintetizzati sul telefono (WebAudio): niente file, niente rete, niente diritti.
 *
 *   tappeti (uno alla volta, in dissolvenza): silenzio · brace · bordone · acqua · aria · respiro
 *   colpi (sopra il tappeto):                 gong · ciotola · campanella · legno · vapore
 *
 * Il tappeto sta sotto tutto il momento e cambia con il momento; i colpi segnano i passaggi.
 */
(function (root) {
  'use strict';

  const FADE_S = 4;
  let ctx = null, master = null, bedBus = null, shotBus = null, alarmBus = null, noiseBuf = null;
  let current = null, level = 0.8, silent = null;

  function init() {
    if (ctx) return ctx;
    const AC = root.AudioContext || root.webkitAudioContext;
    if (!AC) return null;
    // iOS: senza questo l'audio di una pagina è «ambiente» e il tasto del silenzioso lo zittisce, gong compreso
    try { if (root.navigator && navigator.audioSession) navigator.audioSession.type = 'playback'; } catch (e) {}
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = level;
    const comp = ctx.createDynamicsCompressor();          // i colpi sopra il tappeto non devono mai gracchiare
    comp.threshold.value = -16; comp.knee.value = 12; comp.ratio.value = 5;
    const limit = ctx.createDynamicsCompressor();         // e un limite duro in fondo
    limit.threshold.value = -3; limit.knee.value = 0; limit.ratio.value = 20; limit.attack.value = 0.003; limit.release.value = 0.1;
    master.connect(comp); comp.connect(limit); limit.connect(ctx.destination);
    bedBus = ctx.createGain(); bedBus.connect(master);
    shotBus = ctx.createGain(); shotBus.connect(master);
    alarmBus = ctx.createGain(); alarmBus.connect(comp);  // il richiamo non passa dal volume scelto
    const len = ctx.sampleRate * 4;
    noiseBuf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return ctx;
  }

  function wake() { try { if (ctx && ctx.state !== 'running') return ctx.resume(); } catch (e) {} return null; }

  /* Da chiamare su un tocco. Un elemento <audio> che suona (anche silenzio) mette la sessione audio di iOS
     in «riproduzione»: così WebAudio si sente anche col tasto del silenzioso, dove audioSession non c'è. */
  function unlock() {
    try {
      if (!silent) {
        const n = 4000, buf = new ArrayBuffer(44 + n), v = new DataView(buf);
        const w = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
        w(0, 'RIFF'); v.setUint32(4, 36 + n, true); w(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
        v.setUint16(22, 1, true); v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true);
        v.setUint16(34, 8, true); w(36, 'data'); v.setUint32(40, n, true);
        for (let i = 0; i < n; i++) v.setUint8(44 + i, 128);             // mezzo secondo di silenzio
        silent = new Audio(URL.createObjectURL(new Blob([buf], { type: 'audio/wav' })));
        silent.loop = true; silent.setAttribute('playsinline', '');
      }
      const p = silent.play();
      if (p && p.catch) p.catch(() => {});
    } catch (e) {}
  }
  function state() { return ctx ? ctx.state : 'nessuno'; }

  function setLevel(v) {
    level = Math.max(0, Math.min(1, v));
    if (master) master.gain.setTargetAtTime(level, ctx.currentTime, 0.2);
  }

  // --- mattoni ---------------------------------------------------------------

  function osc(type, f, detune) {
    const o = ctx.createOscillator();
    o.type = type; o.frequency.value = f;
    if (detune) o.detune.value = detune;
    o.start();
    return o;
  }

  function gain(v) { const g = ctx.createGain(); g.gain.value = v; return g; }

  function filter(type, f, q) {
    const b = ctx.createBiquadFilter();
    b.type = type; b.frequency.value = f;
    if (q != null) b.Q.value = q;
    return b;
  }

  function noise() {
    const s = ctx.createBufferSource();
    s.buffer = noiseBuf; s.loop = true;
    s.start(0, Math.random() * 3);
    return s;
  }

  /* Un'oscillazione lenta su un parametro (volume, frequenza di un filtro). */
  function lfo(rate, depth, param, nodes) {
    const o = osc('sine', rate), g = gain(depth);
    o.connect(g); g.connect(param);
    nodes.push(o);
    return o;
  }

  // --- tappeti ---------------------------------------------------------------

  const BEDS = {
    silenzio() { return { nodes: [], timers: [] }; },

    /* Le pietre calde: un fondo basso e fermo, e ogni tanto uno scricchiolio di brace. */
    brace(out) {
      const nodes = [], timers = [];
      const rumble = noise(), lp = filter('lowpass', 150, 0.4), g = gain(0.55);
      rumble.connect(lp); lp.connect(g); g.connect(out); nodes.push(rumble);
      lfo(0.07, 0.12, g.gain, nodes);
      for (const [f, a, r] of [[55, 0.16, 0.05], [82.4, 0.09, 0.08], [110.3, 0.04, 0.11]]) {
        const o = osc('sine', f), og = gain(a);
        o.connect(og); og.connect(out); nodes.push(o);
        lfo(r, a * 0.6, og.gain, nodes);
      }
      const crackle = () => {
        if (!ctx) return;
        if (ctx.state !== 'running') { timers[0] = setTimeout(crackle, 2000); return; }   // sospeso: niente nodi in coda
        const src = ctx.createBufferSource(), bp = filter('bandpass', 1500 + Math.random() * 4200, 3 + Math.random() * 5), eg = gain(0);
        src.buffer = noiseBuf;
        const t = ctx.currentTime, dur = 0.02 + Math.random() * 0.07, peak = 0.03 + Math.random() * 0.12;
        eg.gain.setValueAtTime(0, t);
        eg.gain.linearRampToValueAtTime(peak, t + 0.002);
        eg.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        src.connect(bp); bp.connect(eg); eg.connect(out);
        src.start(t, Math.random() * 3, dur + 0.02);
        timers[0] = setTimeout(crackle, Math.random() < 0.25 ? 40 + Math.random() * 120 : 500 + Math.random() * 2600);
      };
      timers[0] = setTimeout(crackle, 800);
      return { nodes, timers };
    },

    /* Un bordone fermo, come una tanpura lontana: fondamentale, quinta, ottava che respirano piano. */
    bordone(out) {
      const nodes = [];
      const lp = filter('lowpass', 1100, 0.3);
      lp.connect(out);
      for (const [f, a, r] of [[110, 0.20, 0.06], [164.8, 0.11, 0.09], [220, 0.09, 0.05], [329.6, 0.035, 0.13]]) {
        for (const cents of [-4, 4]) {
          const o = osc(cents < 0 ? 'sine' : 'triangle', f, cents), og = gain(a * 0.5);
          o.connect(og); og.connect(lp); nodes.push(o);
          lfo(r + (cents > 0 ? 0.017 : 0), a * 0.3, og.gain, nodes);
        }
      }
      return { nodes, timers: [] };
    },

    /* Acqua che scorre: il freddo. */
    acqua(out) {
      const nodes = [], timers = [];
      const n1 = noise(), bp = filter('bandpass', 900, 0.6), g1 = gain(0.34);
      n1.connect(bp); bp.connect(g1); g1.connect(out); nodes.push(n1);
      lfo(0.23, 380, bp.frequency, nodes);
      lfo(0.31, 0.1, g1.gain, nodes);
      const n2 = noise(), hp = filter('highpass', 2600), g2 = gain(0.05);
      n2.connect(hp); hp.connect(g2); g2.connect(out); nodes.push(n2);
      lfo(0.9, 0.03, g2.gain, nodes);
      const drop = () => {
        if (!ctx) return;
        if (ctx.state !== 'running') { timers[0] = setTimeout(drop, 2000); return; }
        const t = ctx.currentTime, o = ctx.createOscillator(), eg = gain(0), f = 700 + Math.random() * 900;
        o.frequency.setValueAtTime(f, t);
        o.frequency.exponentialRampToValueAtTime(f * 1.6, t + 0.05);
        eg.gain.setValueAtTime(0, t);
        eg.gain.linearRampToValueAtTime(0.05, t + 0.005);
        eg.gain.exponentialRampToValueAtTime(0.0001, t + 0.09);
        o.connect(eg); eg.connect(out); o.start(t); o.stop(t + 0.12);
        timers[0] = setTimeout(drop, 300 + Math.random() * 1700);
      };
      timers[0] = setTimeout(drop, 600);
      return { nodes, timers };
    },

    /* Aria: un soffio largo e lento. */
    aria(out) {
      const nodes = [];
      const n = noise(), lp = filter('lowpass', 520, 0.5), g = gain(0.24);
      n.connect(lp); lp.connect(g); g.connect(out); nodes.push(n);
      lfo(0.08, 0.13, g.gain, nodes);
      lfo(0.05, 210, lp.frequency, nodes);
      return { nodes, timers: [] };
    },

    /* Il respiro guidato del riposo: un suono che sale (inspiro) e scende più a lungo (espiro). */
    respiro(out, opts) {
      const nodes = [], timers = [];
      const clamp = (x, d) => Math.min(15, Math.max(2, Number(x) || d));
      const tin = clamp(opts && opts.in_s, 4), tout = clamp(opts && opts.out_s, 6);
      const body = gain(0.0001), air = gain(0.0001);
      const lp = filter('lowpass', 700, 0.4);
      lp.connect(body); body.connect(out);
      for (const [f, a] of [[130.8, 0.5], [196, 0.3], [261.6, 0.14]]) {
        const o = osc('sine', f), og = gain(a);
        o.connect(og); og.connect(lp); nodes.push(o);
      }
      const n = noise(), bp = filter('bandpass', 600, 0.7);
      n.connect(bp); bp.connect(air); air.connect(out); nodes.push(n);
      let t = ctx.currentTime + 0.1;
      body.gain.setValueAtTime(0.03, t); air.gain.setValueAtTime(0.01, t); bp.frequency.setValueAtTime(450, t);
      const block = () => {                                  // i respiri si programmano a blocchi: il riposo può durare quanto vuole
        if (!ctx) return;
        const N = 24;
        for (let k = 0; k < N; k++) {
          body.gain.linearRampToValueAtTime(0.42, t + tin);
          air.gain.linearRampToValueAtTime(0.11, t + tin);
          bp.frequency.linearRampToValueAtTime(950, t + tin);
          t += tin;
          body.gain.linearRampToValueAtTime(0.03, t + tout);
          air.gain.linearRampToValueAtTime(0.01, t + tout);
          bp.frequency.linearRampToValueAtTime(450, t + tout);
          t += tout;
        }
        timers[0] = setTimeout(block, Math.max(1000, (t - ctx.currentTime - 20) * 1000));
      };
      block();
      return { nodes, timers };
    },
  };

  function kill(b) {
    if (!b) return;
    for (const t of b.timers) clearTimeout(t);
    b.timers.length = 0;
    for (const n of b.nodes) { try { n.stop(); } catch (e) {} try { n.disconnect(); } catch (e) {} }
    try { b.out.disconnect(); } catch (e) {}
  }

  /* Cambia tappeto in dissolvenza. Lo stesso tappeto con le stesse opzioni non riparte. */
  function bed(name, opts, fade) {
    if (!ctx) return;
    const key = name + ':' + JSON.stringify(opts || {});
    if (current && current.key === key) return;
    const f = fade == null ? FADE_S : fade, t = ctx.currentTime, old = current;
    if (old) {
      old.out.gain.cancelScheduledValues(t);
      old.out.gain.setValueAtTime(old.out.gain.value, t);
      old.out.gain.linearRampToValueAtTime(0, t + f);
      setTimeout(() => kill(old), f * 1000 + 300);
    }
    const out = gain(0);
    out.connect(bedBus);
    const b = (BEDS[name] || BEDS.silenzio)(out, opts);
    b.out = out; b.key = key; b.name = name; b.started = t;
    out.gain.setValueAtTime(0, t);
    out.gain.linearRampToValueAtTime(1, t + f);
    current = b;
  }

  /* Abbassa il tappeto mentre una voce parla. */
  function duck(on) {
    if (!bedBus) return;
    bedBus.gain.setTargetAtTime(on ? 0.3 : 1, ctx.currentTime, 0.25);
  }

  // --- colpi -----------------------------------------------------------------

  /* Parziali che decadono: gong, ciotola, campanella. */
  function partials(list, vol, attack, bus) {
    const t = ctx.currentTime, out = gain(vol);
    out.connect(bus || shotBus);
    let longest = 0;
    for (const [f, a, decay] of list) {
      const o = ctx.createOscillator(), g = gain(0);
      o.frequency.value = f;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(a, t + (attack || 0.004));
      g.gain.exponentialRampToValueAtTime(0.0001, t + decay);
      o.connect(g); g.connect(out); o.start(t); o.stop(t + decay + 0.1);
      longest = Math.max(longest, decay);
    }
    setTimeout(() => { try { out.disconnect(); } catch (e) {} }, (longest + 0.5) * 1000);
    return out;
  }

  function burst(dur, mk, bus) {
    const t = ctx.currentTime, src = ctx.createBufferSource(), g = gain(0);
    src.buffer = noiseBuf;
    const last = mk(src, g, t);
    last.connect(bus || shotBus);
    src.start(t, Math.random() * 2, dur + 0.1);
    setTimeout(() => { try { last.disconnect(); } catch (e) {} }, (dur + 0.5) * 1000);
  }

  const SHOTS = {
    /* Gong profondo: apre e chiude il calore, richiama oltre il limite. */
    gong(bus) {
      const f0 = 73.4, list = [];
      for (const [r, a, d] of [[1, 0.9, 11], [1.48, 0.5, 9], [2.03, 0.42, 7.5], [2.62, 0.3, 6], [3.41, 0.2, 4.5], [4.27, 0.13, 3.2], [5.43, 0.08, 2.2]]) {
        list.push([f0 * r - 0.35, a * 0.5, d], [f0 * r + 0.35, a * 0.5, d]);
      }
      partials(list, 0.5, 0.012, bus);
      burst(0.25, (src, g, t) => {                              // il colpo del mazzuolo
        const lp = filter('lowpass', 420);
        g.gain.setValueAtTime(0.5, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
        src.connect(lp); lp.connect(g);
        return g;
      }, bus);
    },
    /* Ciotola che canta: il traguardo di un momento, l'inizio del riposo. */
    ciotola() {
      const f0 = 214, list = [];
      for (const [r, a, d] of [[1, 1, 9], [2.71, 0.5, 6], [5.15, 0.22, 3.5], [8.4, 0.09, 1.8]]) {
        list.push([f0 * r - 0.45 * r, a * 0.5, d], [f0 * r + 0.45 * r, a * 0.5, d]);
      }
      partials(list, 0.42);
    },
    /* Campanella: l'acqua fredda. */
    campanella() {
      partials([[2093, 0.5, 2.6], [2127, 0.5, 2.6], [4310, 0.2, 1.3], [6230, 0.08, 0.7]], 0.2, 0.002);
    },
    /* Legno: un tocco asciutto, per uscire all'aria. */
    legno() {
      partials([[620, 0.8, 0.12], [930, 0.3, 0.07]], 0.4, 0.001);
      burst(0.05, (src, g, t) => {
        const bp = filter('bandpass', 1900, 2);
        g.gain.setValueAtTime(0.3, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.04);
        src.connect(bp); bp.connect(g);
        return g;
      });
    },
    /* Acqua sulle pietre: lo sfrigolio della gettata di vapore. */
    vapore() {
      burst(4.5, (src, g, t) => {
        const bp = filter('bandpass', 6500, 0.8);
        bp.frequency.setValueAtTime(6500, t);
        bp.frequency.exponentialRampToValueAtTime(1100, t + 4);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(0.5, t + 0.04);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 4.4);
        src.connect(bp); bp.connect(g);
        return g;
      });
      burst(0.6, (src, g, t) => {
        const lp = filter('lowpass', 160);
        g.gain.setValueAtTime(0.6, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.55);
        src.connect(lp); lp.connect(g);
        return g;
      });
    },
  };

  function shot(name) {
    if (!ctx || !SHOTS[name]) return;
    try { SHOTS[name](); } catch (e) {}
  }

  /* Il richiamo oltre il limite: due gong a volume pieno, qualunque sia il volume scelto, col tappeto abbassato. */
  function alarm() {
    if (!ctx) return;
    wake();
    duck(true);
    try { SHOTS.gong(alarmBus); } catch (e) {}
    setTimeout(() => { try { SHOTS.gong(alarmBus); } catch (e) {} }, 2400);
    setTimeout(() => duck(false), 9000);
  }

  function stop(fade) {
    if (ctx) bed('silenzio', null, fade == null ? 2 : fade);
    try { if (silent) silent.pause(); } catch (e) {}
  }
  function bedStarted() { return current ? current.started : 0; }
  function clock() { return ctx ? ctx.currentTime : 0; }

  root.RitoSound = { init, unlock, wake, state, setLevel, bed, duck, shot, alarm, stop, bedStarted, clock,
    beds: Object.keys(BEDS), shots: Object.keys(SHOTS) };
})(typeof self !== 'undefined' ? self : this);
