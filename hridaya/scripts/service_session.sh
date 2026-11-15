#!/bin/zsh
# La sessione dedicata di Hṛdaya: un Claude interattivo in tmux, solo per il servizio.
#
#   service_session.sh start   [repo-dati]   avvia se non c'è
#   service_session.sh restart [repo-dati]   chiude e riparte pulita (contesto azzerato)
#   service_session.sh tick    [repo-dati]   per launchd, ogni 10': avvia se manca; rinasce nella
#                                            finestra notturna se è di ieri; riparte se l'ascolto della
#                                            coda è fermo da più di 15' (Monitor non riarmato, bloccata
#                                            su un prompt, claude uscito: prima il bot prova a svegliarla);
#                                            riparte se è stata installata una versione nuova del plugin
#                                            dopo la sua nascita e non ha messaggi in lavorazione
#   service_session.sh stop | status | attach
#
# Server tmux privato (-L hridaya): non eredita l'ambiente di chi ha avviato il tmux di tutti
# (una sessione Claude, una shell SSH). La sessione nasce con HRIDAYA_SERVICE=1: l'hook di avvio
# accende il servizio solo lì; le sessioni di lavoro non ascoltano mentre batte la dedicata.
# Repo dati: argomento, o WELLNESS_DATA. Permessi: modalità auto (nessuno davanti allo schermo).
# Sonno del Mac: claude gira sotto `caffeinate -is` (niente sonno da inattività finché vive la sessione;
# -s vale in corrente). Col coperchio chiuso macOS dorme comunque: lì serve `pmset disablesleep`.
set -u
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"
# fuori dall'ambiente di un'eventuale sessione Claude genitore (claude si crederebbe annidato)
for v in ${(k)parameters[(I)CLAUDE*]}; do unset "$v"; done

HERE="${0:A:h}"
NAME="${HRIDAYA_TMUX_SESSION:-hridaya}"
CMD="${1:-status}"
DATA="${2:-${WELLNESS_DATA:-}}"
PROMPT="/hridaya:servizio"
NIGHT_FROM=4 NIGHT_TO=6        # finestra della rinascita (dentro il silenzio notturno)
STALE_S=900                    # ascolto della coda fermo oltre → la sessione non sta servendo
BACKOFF_S=1800                 # al massimo un riavvio per blocco ogni 30'
BUSY_MAX_S=2700                # occupata da più di 45' con l'ascolto fermo: si riavvia comunque
IDLE_MIN=20                    # versione nuova: si riparte solo con il canale fermo da tanto (o di notte)
T=(tmux -L hridaya)

log() { print "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
running() { $T has-session -t "=$NAME" 2>/dev/null; }

need_data() {
  if [[ -z "$DATA" || ! -f "$DATA/data/profile.json" ]]; then
    print -u2 "repo dati mancante o non valido: '$DATA' (serve data/profile.json)"
    exit 2
  fi
}

created_epoch() { $T display-message -p -t "=$NAME:" '#{session_created}' 2>/dev/null; }

created_day() {
  local e; e=$(created_epoch)
  [[ -n "$e" ]] && date -r "$e" '+%Y-%m-%d' || print "sconosciuto"
}

beat_age() {   # secondi dall'ultimo battito, vuoto se mai
  WELLNESS_DATA="$DATA" python3.12 -c '
import sys; sys.path.insert(0, sys.argv[1]); import session_state as s
a = s.age_s(); st = s.read()
print("" if a is None or not st.get("on") else int(a))' "$HERE" 2>/dev/null
}

listen_age() {   # secondi dall'ultimo ascolto vero della coda (watcher del Monitor), vuoto se mai
  WELLNESS_DATA="$DATA" python3.12 -c '
import sys; sys.path.insert(0, sys.argv[1]); import session_state as s
a = s.listen_age_s(); st = s.read()
print("" if a is None or not st.get("on") else int(a))' "$HERE" 2>/dev/null
}

pending() {   # messaggi ed eventi in lavorazione adesso (in coda da meno di 30': i più vecchi sono fermi, non in corso)
  WELLNESS_DATA="$DATA" python3.12 -c '
import sys; sys.path.insert(0, sys.argv[1]); import telegram_queue as tq
from datetime import datetime, timedelta, timezone
cut = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
print(sum(1 for r in tq.list_pending() if r.get("created_at", "") >= cut))' "$HERE" 2>/dev/null
}

working() {   # la sessione sta lavorando a un turno (spinner «… (12s ·» o «esc to interrupt»)
  $T capture-pane -p -t "=$NAME:" 2>/dev/null | tail -30 | grep -qE '… \(|esc to interrupt'
}

busy() {   # lavora, oppure aspetta una risposta a un dialog: non è il momento di riavviarla per una versione
  working || $T capture-pane -p -t "=$NAME:" 2>/dev/null | tail -30 | grep -qE 'Do you want|Esc to cancel'
}

idle_min() {   # minuti dall'ultima attività sul canale (messaggio arrivato o risposta partita); vuoto se ignoto
  WELLNESS_DATA="$DATA" python3.12 -c '
import sys; sys.path.insert(0, sys.argv[1]); import telegram_queue as tq
from datetime import datetime, timezone
ts = [r.get(k) for f in (tq.inbox_path(), tq.outbox_path()) for r in tq.read_jsonl(f)
      if r.get("kind") != "system" for k in ("created_at", "sent_at") if r.get(k)]
print(int((datetime.now(timezone.utc) - datetime.fromisoformat(max(ts))).total_seconds() // 60) if ts else "")' "$HERE" 2>/dev/null
}

installed_epoch() { stat -f %m "$HERE/../.claude-plugin/plugin.json" 2>/dev/null; }

start() {
  need_data
  if running; then
    log "sessione $NAME già attiva"
    return 0
  fi
  # una sessione morta può aver lasciato un watcher orfano (batte per nessuno) e lo stato acceso
  pkill -f "hridaya/.*scripts/service_watch.py" 2>/dev/null && log "watcher orfano fermato"
  WELLNESS_DATA="$DATA" python3.12 "$HERE/session_state.py" off >/dev/null 2>&1
  $T new-session -d -s "$NAME" -c "$DATA" -x 200 -y 50 \
    "exec env HRIDAYA_SERVICE=1 WELLNESS_DATA=${(q)DATA} caffeinate -is claude --permission-mode auto ${(q)PROMPT}"
  log "sessione $NAME avviata in $DATA"
}

stop() {
  if running; then
    # chiudere il pane chiude stdin del server MCP: il suo battito si ferma da solo
    $T kill-session -t "=$NAME"
    log "sessione $NAME chiusa"
  fi
  # un watcher del Monitor rimasto orfano continuerebbe a battere e a consumare i cue
  pkill -f "hridaya/.*scripts/service_watch.py" 2>/dev/null && log "watcher orfano fermato"
  [[ -n "$DATA" ]] && WELLNESS_DATA="$DATA" python3.12 "$HERE/session_state.py" off >/dev/null 2>&1
  return 0
}

restart() { need_data; stop; sleep 3; start; }

tick() {
  need_data
  if ! running; then
    log "tick: sessione assente"; start; return
  fi
  local now hour age e born_age stamp last
  now=$(date +%s); hour=$((10#$(date +%H)))
  e=$(created_epoch); born_age=$(( now - ${e:-$now} ))
  if (( hour >= NIGHT_FROM && hour < NIGHT_TO )) && [[ "$(created_day)" != "$(date '+%Y-%m-%d')" ]]; then
    log "tick: rinascita notturna (nata il $(created_day))"; restart; return
  fi
  local inst pend idle; inst=$(installed_epoch)
  if [[ -n "$inst" && -n "$e" ]] && (( inst > e )); then
    pend=$(pending); idle=$(idle_min)
    if [[ -z "$pend" ]]; then
      log "tick: versione nuova installata, ma non riesco a leggere la coda: non riparto"
    elif [[ "$pend" == "0" ]] && ! busy && { (( hour >= NIGHT_FROM && hour < NIGHT_TO )) || [[ -z "$idle" ]] || (( idle >= IDLE_MIN )); }; then
      log "tick: versione nuova del plugin installata dopo la nascita della sessione (canale fermo da ${idle:-?}′): riparte"
      restart; return
    fi
  fi
  age=$(listen_age)
  local bstamp="$DATA/data/hridaya/.session_busy_since"
  if (( born_age > STALE_S )) && { [[ -z "$age" ]] || (( age > STALE_S )); }; then
    if working; then                   # un turno lungo (Kaula, consiglio): il riarmo arriva a fine turno
      local since; since=$(cat "$bstamp" 2>/dev/null || { print "$now" > "$bstamp"; print "$now"; })
      if (( now - since < BUSY_MAX_S )); then
        log "tick: ascolto fermo (${age:-mai} s) ma la sessione sta lavorando da $(( (now - since) / 60 ))′: aspetto"
        return
      fi
      log "tick: occupata da più di $(( BUSY_MAX_S / 60 ))′ con l'ascolto fermo: riavvio comunque"
    fi
    rm -f "$bstamp"
    stamp="$DATA/data/hridaya/.session_restart"
    last=$(cat "$stamp" 2>/dev/null || print 0)
    if (( now - last < BACKOFF_S )); then
      log "tick: ascolto fermo (${age:-mai}), riavvio già tentato da poco: aspetto"; return
    fi
    mkdir -p "${stamp:h}"; print "$now" > "$stamp"
    log "tick: ascolto della coda fermo (${age:-mai} s): ultime righe dello schermo, poi riavvio"
    $T capture-pane -p -t "=$NAME:" 2>/dev/null | tail -25
    restart; return
  fi
  rm -f "$bstamp"
}

case "$CMD" in
  start)   start ;;
  restart) restart ;;
  tick)    tick ;;
  stop)    stop ;;
  status)
    if running; then
      print "sessione $NAME attiva, nata il $(created_day), battito ${$(beat_age):-assente} s fa, ascolto della coda ${$(listen_age):-assente} s fa"
    else
      print "sessione $NAME non attiva"; exit 1
    fi ;;
  attach)  exec $T attach -t "=$NAME" ;;
  *) print -u2 "uso: $0 start|restart|tick|stop|status|attach [repo-dati]"; exit 2 ;;
esac
