# I suoni del rito

Il telefono resta fuori dalla cabina: nel calore il rito parla solo col suono. Tutti i suoni sono
sintetizzati sul telefono (`apps/rito/sound.js`): niente file, niente rete.

## Tappeti — uno per momento (`sound`)

Il tappeto sta sotto tutto il momento e cambia, in dissolvenza, già durante il passaggio verso il
momento successivo.

| Nome | Cos'è | Quando |
|---|---|---|
| `brace` | un fondo basso e fermo, e ogni tanto lo scricchiolio delle pietre | il calore (predefinito) |
| `bordone` | un bordone fermo, come una tanpura lontana | soglia e chiusura (predefinito); un calore più raccolto |
| `aria` | un soffio largo e lento | l'aria (predefinito) |
| `acqua` | acqua che scorre, gocce | il freddo (predefinito) |
| `respiro` | un suono che sale con l'inspiro e scende, più a lungo, con l'espiro (`breath: {in_s, out_s}`) | il riposo (predefinito): guida il respiro lento senza una voce |
| `silenzio` | niente | quando la giornata è stata rumorosa; un riposo lungo dopo i primi minuti guidati; chi in cabina vuole solo il legno |

Comporre:
- **Un rito non ha più di tre tappeti diversi.** Il cambio di suono è il segnale del cambio di momento.
- Il respiro guidato va bene per il riposo breve; per il riposo lungo spesso è meglio `bordone` o
  `silenzio`: il respiro, a quel punto, lo trova da solo.
- Rapporto del respiro: espiro più lungo dell'inspiro (4 e 6 secondi è un buon inizio). È un
  appoggio, non una pratica: se la persona vuole una pratica, è del Kaula.
- Se in cabina il suono non arriva (`setup.sound.heard_inside: false`), nel calore conta solo ciò
  che si sente attraverso la porta: gong e ciotola. Il tappeto del calore è per chi sta fuori.

## Colpi — ai passaggi e nei richiami (`enter_sound`, `cues[].sound`)

| Nome | Cos'è | Uso |
|---|---|---|
| `gong` | profondo, lungo | comincia il calore; il richiamo oltre il massimo (due colpi, ogni 30 secondi); fine del rito |
| `ciotola` | una ciotola che canta | traguardo di un momento; comincia il riposo; «siediti» due minuti prima di uscire |
| `campanella` | chiara, breve | comincia l'acqua |
| `legno` | un tocco asciutto | comincia l'aria |
| `vapore` | acqua sulle pietre | la gettata: «adesso il mestolo» |

Ogni tipo di momento ha il suo colpo d'inizio predefinito; `enter_sound: false` lo toglie. Il colpo
suona quando il momento **comincia davvero**, cioè alla fine del passaggio (o al «Ci sono»).

Il motore suona da solo: la `ciotola` al traguardo (`target_s`) di un momento che finisce col
tocco, e il `gong` doppio al massimo (`max_s`), ripetuto finché non si esce.

## La voce (`cues[].say`)

Il telefono può dire una frase (voce italiana del sistema). Usala poco: una voce in una Spa è un
sussurro all'orecchio, non un annuncio. Va bene per «Siediti: ancora due minuti» a chi non vede lo
schermo; non va bene per spiegare. Con `"voice": false` nella partitura (o se `setup.sound.voice`
è falso) le frasi restano scritte a schermo e non vengono dette.

## Un rito, i suoi suoni: esempio

Soglia `bordone` → calore `brace`, gong all'inizio, ciotola a due minuti dalla fine, ciotola al
traguardo → aria `aria`, legno → acqua `acqua`, campanella → riposo `respiro` 4/6, ciotola → secondo
calore `brace` con `vapore` a metà → aria → riposo lungo `bordone` → chiusura `bordone`, gong.
