from trame.ui.vuetify import SinglePageLayout
from trame.widgets import vtk, vuetify

from constants import REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS


def build_ui(server, renderWindow):
    """Build the Trame UI layout."""
    state = server.state
    ctrl = server.controller

    with SinglePageLayout(server) as layout:
        layout.title.set_text("Coral Visualizer")
        layout.icon.hide()

        with layout.toolbar:
            vuetify.VSpacer()
            vuetify.VSelect(
                v_model=("selected_file",),
                items=("available_files",),
                label="Select VTK File",
                hide_details=True,
                dense=True,
                outlined=True,
                style="max-width: 200px;",
                classes="mr-2",
            )
            # with vuetify.Template(v_slot_extension=""):
            #     vuetify.VSpacer()
            vuetify.VSelect(
                v_model=("selected_array",),
                items=("available_arrays",),
                label="Color by",
                hide_details=True,
                dense=True,
                outlined=True,
                style="max-width: 150px;",
                classes="mr-2",
            )
            # vuetify.VSwitch(
            #     v_model=("show_boundary",),
            #     label="Boundaries",
            #     hide_details=True,
            #     dense=True,
            #     v_show=("has_boundary",),
            #     classes="mr-4 mt-1",
            # )
            # vuetify.VSwitch(
            #     v_model=("show_scalar_bars",),
            #     label="Legend",
            #     hide_details=True,
            #     dense=True,
            #     classes="mr-4 mt-1",
            # )
            vuetify.VSelect(
                v_model=("representation",),
                items=([REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS],),
                label="Representation",
                hide_details=True,
                dense=True,
                outlined=True,
                style="max-width: 150px;",
                classes="mr-2",
            )

        with layout.content:
            with vuetify.VContainer(
                fluid=True,
                classes="pa-0 fill-height",
                style="position: relative;",
            ):
                # Error message as overlay
                vuetify.VAlert(
                    v_show=("error_message",),
                    type="error",
                    dense=True,
                    dismissible=True,
                    v_model=("error_message",),
                    children=("{{ error_message }}",),
                    style="position: absolute; top: 10px; left: 10px; right: 10px; z-index: 1000;",
                )

                # VTK view
                view = vtk.VtkRemoteView(
                    renderWindow,
                    ref="view",
                    style="width: 100%; height: 100%;",
                )
                ctrl.view_update = view.update

    return layout
