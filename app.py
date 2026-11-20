from app_config import enable_paraview_web_venv_if_requested

enable_paraview_web_venv_if_requested()

from factory import (  # noqa: E402
    create_app,
    make_download_handler,
    make_open_file_handler,
)

if __name__ == "__main__":
    app = create_app()
    ctrl = app.ctrl

    @ctrl.add("on_server_bind")
    def _(wslink_server):
        wslink_server.app.router.add_route(
            "GET", "/api/download", make_download_handler(app.config.data_directory)
        )
        wslink_server.app.router.add_route(
            "GET",
            "/api/open",
            make_open_file_handler(app.config.data_directory, app.state),
        )

    app.server.start()
