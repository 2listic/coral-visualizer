# TODO

## Priorita alta

- Stabilizzare le dipendenze runtime in `setup/requirements.txt` con versioni pinnate o un lockfile.
- Eliminare workaround client/server non necessari e lasciare un solo punto autorevole per la configurazione del viewer ParaView.

## Priorita media

- Completare la separazione di `app.py`, che ora delega stato/wiring/runtime ma contiene ancora:
  - parsing CLI e scelta backend
  - bootstrap del server Trame
  - costruzione diretta di backend/runtime/edit state
  - helper `_debug_view` / `_call_view_*`
- Ridurre lo stato globale mutabile rimasto in `app.py` (`state`, `_pv_backend`, `_edit_session`, `_edit`, runtime) introducendo wrapper o service object più chiari.
- Ridurre l'accoppiamento fra `app.py`, `ui.py` e `paraview_backend.py`.
- Evitare accessi a metodi interni del backend come `_find_node` fuori dal modulo che li possiede.
- Rendere più espliciti i confini tra backend `vtk` e backend `paraview`, evitando rami sparsi in tutto il codice.
- Sostituire le lambda rimaste in `register_app_handlers(...)` con dependency object piu espliciti, soprattutto per file ops e salvataggio.

## Test

- Aggiungere test per il bootstrap dell'app con `--backend vtk`, `--backend paraview` e `--backend auto`.
- Aggiungere test app-level per il fallback quando `--backend paraview` viene richiesto ma ParaView non e disponibile.
- Aggiungere test piu alti di livello sul wiring UI/client e sui callback Trame dove oggi c'e solo copertura unitaria o e2e specifica.

## Pulizia codice

- Ridurre la dimensione dei file monolitici `app.py`, `ui.py` e `paraview_backend.py`.
- Rimuovere helper morti o sperimentali rimasti dopo il passaggio a `VtkRemoteLocalView`.
- Centralizzare costanti e mapping UI per rappresentazioni, modalita di interazione ed eventi viewer.
- Valutare type hints o piccole dataclass per i runtime/helper introdotti nel refactor.
- Ripulire commenti temporanei o da debugging che spiegano workaround invece di design stabile.
- Migliorare i nomi delle funzioni che oggi fanno sia sync di stato sia side effect di rendering.
- Separare meglio la logica di serializzazione/debug degli eventi di picking dalla logica di selezione.
- Valutare un componente/helper dedicato per i controlli Display avanzati, ora implementati direttamente fra `ui.py`, `paraview_controllers.py` e `paraview_backend.py`.

## Tooling e sviluppo

- Rendere `dev.sh` meno dipendente dall'ambiente locale hardcoded e piu portabile.
- Documentare chiaramente quando usare `--server`, `--dev` e `--hot-reload`.
- Valutare lint aggiuntivi o type checking leggero sulle parti Python piu instabili.
- Ignorare o gestire meglio artefatti locali e dati generati per mantenere il repository pulito.

## Documentazione

- Aggiornare il README con lo stato reale delle feature supportate su ogni backend.
- Documentare i limiti noti del backend ParaView e i casi ancora sperimentali.
- Aggiungere una sezione "troubleshooting" con errori tipici di startup e relative cause.
