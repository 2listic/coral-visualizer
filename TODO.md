# TODO

## Priorita alta

- **Performance selezione su dataset grandi** — bottleneck documentati in
  `docs/logic_flows.md` §5a e §6. Piano a step progressivi in [issue #34](https://github.com/2listic/coral-visualizer/issues/34); ogni step
  è indipendente e lascia i test esistenti verdi. Step 1 può essere fatto direttamente
  su `paraview_backend.py` senza refactor preventivo.

- Separare `paraview_backend.py` in servizi di dominio più piccoli (3900 righe).
  Iniziare da moduli con dipendenze unidirezionali (`backend/display.py`,
  `backend/coloring.py`, `backend/pipeline.py`) — più self-contained e a minor rischio
  di regressione rispetto alla selezione, che dipende trasversalmente dallo stato del
  backend. La selezione segue dopo. Vedi [docs/backend_refactor.md](docs/backend_refactor.md)
  per strategia, layout moduli e firme.

## Priorita media

- Ridurre l'accoppiamento fra `ui.py` e `paraview_backend.py` (accoppiamento
  con `app.py` risolto — ora è un wrapper di 16 righe).
- Separare `paraview_controllers.py` in controller per pipeline, display,
  edit-field, edit-selection e file/export.
- Spezzare `ui.py` in moduli/pannelli (`toolbar`, `pipeline_panel`,
  `display_panel`, `edit_panel`, `dialogs`) mantenendo invariato il layout.
  Low regression risk. Prerequisito per il lavoro di UX.
- Centralizzare le opzioni UI dichiarative oggi duplicate tra `state_setup.py`,
  `ui.py` e controller.

## Miglioramenti futuri

- **Riorganizzazione UI/UX**: migliorare l'esperienza utente eventualmente dopo aver spezzato
  `ui.py` in moduli navigabili.

## Riorganizzazione cartelle

Cosmetic — does not block any other work. Do one group at a time, update imports
atomically per move, run tests after each step.

`factory.py` e `make_download_handler` già esistono alla root; si spostano in
`core/` come parte di questo step.

Recommended order: `io/` first (no inward imports), then `domain/`, `controllers/`,
`core/`, `backend/` last (highest risk).

    trame-simple-visualizer/
    ├── app.py, app_config.py, constants.py, diagnostics.py   (root)
    ├── core/        handler_registration, runtime_setup, state_setup,
    │                state_handlers, view_controls, factory
    ├── backend/     pipeline, display, colorbar, selection, export,
    │                paraview_runtime, paraview_event_utils,
    │                paraview_filter_catalog, paraview_property_inspector,
    │                selection_debug, selection_timing
    ├── domain/      edit_session
    ├── controllers/ paraview_controllers, common_controllers
    ├── io/          file_operations, file_utils, vtk_metadata
    └── ui/          ui (then panels after split)

## Test

- Aggiungere un test/script CI per il container Docker che faccia build, version
  probe e HTTP smoke test su porta locale.
- I Trame `@state.change` callback non sono testabili in modo sincrono senza
  event loop: rimane il gap tra test unitari (mock) e e2e (Playwright). Da
  valutare se vale la pena introdurre un harness asincrono o se i test factory
  attuali coprono abbastanza.

## Pulizia codice

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
