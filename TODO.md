# TODO

## Priorita alta

- Introdurre una app factory/test harness che costruisca server, state, runtime
  e handler senza side effect di import e senza chiamare `server.start()`.
- Separare `paraview_backend.py` in servizi di dominio più piccoli:
  pipeline/filter, display-colorbar, selection/picking, edit-session I/O,
  salvataggio/export.

## Priorita media

- Ridurre l'accoppiamento fra `app.py`, `ui.py` e `paraview_backend.py`.
- Separare `paraview_controllers.py` in controller per pipeline, display,
  edit-field, edit-selection e file/export.
- Spezzare `ui.py` in moduli/pannelli (`toolbar`, `pipeline_panel`,
  `display_panel`, `edit_panel`, `dialogs`) mantenendo invariato il layout.
- Centralizzare le opzioni UI dichiarative oggi duplicate tra `state_setup.py`,
  `ui.py` e controller.

## Test

- Aggiungere test più alti di livello sul wiring UI/client e sui callback Trame
  dove oggi c'è solo copertura unitaria o e2e specifica.
- Aggiungere un test/script CI per il container Docker che faccia build, version
  probe e HTTP smoke test su porta locale.

## Pulizia codice

- Ridurre la dimensione dei file monolitici `ui.py` (1800 righe) e
  `paraview_backend.py` (3900 righe).
- Rimuovere helper morti o sperimentali rimasti dentro `paraview_backend.py`
  dopo il passaggio a `VtkRemoteLocalView`.
- Estendere type hints/dataclass a `paraview_backend.py` e `paraview_runtime.py`,
  ancora privi di contratto esplicito (parzialmente fatto su `runtime_setup.py`,
  `file_operations.py`, `state_handlers.py`, `common_controllers.py`,
  `handler_registration.py`, `view_controls.py`).
- Migliorare i nomi delle funzioni che oggi fanno sia sync di stato sia side
  effect di rendering (parzialmente fatto: `update_color_state` vs
  `update_ui_state`, `_refresh_color_state`).
- Valutare un componente/helper dedicato per i controlli Display avanzati, ora
  implementati direttamente fra `ui.py`, `paraview_controllers.py` e
  `paraview_backend.py`.

## Tooling e sviluppo

- Rendere `dev.sh` meno dipendente dall'ambiente locale hardcoded e più portabile.
- Valutare lint aggiuntivi o type checking leggero sulle parti Python più instabili.
- Aggiungere un comando unico documentato per `format`, `lint`, `test`,
  `docker-build` e `docker-smoke`.

## Documentazione

- Documentare i limiti noti del backend ParaView e i casi ancora sperimentali.
