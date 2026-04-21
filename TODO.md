# TODO

## Priorita alta

- Stabilizzare le dipendenze runtime in `setup/requirements.txt` con versioni pinnate o un lockfile.
- Verificare e documentare una matrice di versioni supportate per `trame`, `trame-vtk`, `trame-vuetify`, `vtk` e ParaView.
- Aggiungere un test di regressione per il wiring di `interactor_events`, per evitare nuovi errori tipo `this.interactor[l] is not a function`.
- Eliminare workaround client/server non necessari e lasciare un solo punto autorevole per la configurazione del viewer ParaView.
- Allineare README e UI sul supporto reale dell'edit mode nel backend ParaView.

## Priorita media

- Spezzare `app.py` in moduli separati:
  - bootstrap e parsing CLI
  - stato Trame
  - wiring delle dipendenze
  - logica di sincronizzazione edit session
- Ridurre lo stato globale mutabile (`state`, `_pv_backend`, `_edit_session`, `_viz`) introducendo wrapper o service object più chiari.
- Ridurre l'accoppiamento fra `app.py`, `ui.py` e `paraview_backend.py`.
- Evitare accessi a metodi interni del backend come `_find_node` fuori dal modulo che li possiede.
- Rendere più espliciti i confini tra backend `vtk` e backend `paraview`, evitando rami sparsi in tutto il codice.
- Portare fuori da `app.py` anche gli helper backend-specifici di caricamento/colorazione/reset in una facade o service dedicato.
- Ridurre il wiring a lambda sparse in `app.py`, sostituendolo con dependency object piu espliciti.
- Ridurre il numero di alias `_foo = runtime.bar if ... else _noop` in `app.py`, spostando la scelta del backend in un livello piu strutturato.
- Spostare anche gli adapter inline per file ops e salvataggio fuori da `app.py`, idealmente dentro il layer di wiring.

## Test

- Estendere la copertura dai moduli helper/controller/backend gia testati ai runtime principali `paraview_runtime.py` e `vtk_runtime.py`.
- Aggiungere test dedicati per `vtk_controllers.py`, specialmente per edit mode, selezione e salvataggio `.vtu`.
- Aggiungere test per il bootstrap dell'app con `--backend vtk`, `--backend paraview` e `--backend auto`.
- Aggiungere test per il cambio `pick_mode` e per la sincronizzazione di `edit_picking_modes`, `interactor_events` e `interactor_settings`.
- Aggiungere test per il flusso di edit session ParaView: begin, pick, discard, commit.
- Aggiungere test negativi sui fallback quando ParaView non e disponibile.
- Aggiungere test piu alti di livello sul wiring UI/client e sui callback Trame, oltre la nuova copertura unitaria.

## Pulizia codice

- Ridurre la dimensione dei file monolitici `app.py`, `ui.py` e `paraview_backend.py`.
- Rimuovere helper morti o sperimentali rimasti dopo il passaggio a `VtkRemoteLocalView`.
- Centralizzare costanti e mapping UI per rappresentazioni, modalita di interazione ed eventi viewer.
- Valutare type hints o piccole dataclass per i runtime/helper introdotti nel refactor.
- Ripulire commenti temporanei o da debugging che spiegano workaround invece di design stabile.
- Migliorare i nomi delle funzioni che oggi fanno sia sync di stato sia side effect di rendering.
- Separare meglio la logica di serializzazione/debug degli eventi di picking dalla logica di selezione.

## Tooling e sviluppo

- Rendere `dev.sh` meno dipendente dall'ambiente locale hardcoded e piu portabile.
- Documentare chiaramente quando usare `--server`, `--dev` e `--hot-reload`.
- Valutare lint aggiuntivi o type checking leggero sulle parti Python piu instabili.
- Ignorare o gestire meglio artefatti locali e dati generati per mantenere il repository pulito.

## Documentazione

- Aggiornare il README con lo stato reale delle feature supportate su ogni backend.
- Documentare i limiti noti del backend ParaView e i casi ancora sperimentali.
- Aggiungere una sezione "troubleshooting" con errori tipici di startup e relative cause.
