from trame.ui.vuetify import SinglePageLayout
from trame.widgets import vtk, vuetify


def build_ui(server, renderWindow):
    """Build the Trame UI layout."""
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
                style="max-width: 400px;",
                classes="mr-4",
            )

            # Toggle tag mode on/off
            vuetify.VBtn(
                click="tag_mode = !tag_mode",
                small=True,
                color=("tag_mode ? 'warning' : ''",),
                classes="mr-2",
                children=["Tag Mode"],
                title="Toggle tag mode — click mesh cells to assign BoundaryID",
            )

            # Current tag ID (integer 1–16)
            vuetify.VTextField(
                v_model=("active_tag_id",),
                label="Tag ID",
                type="number",
                min=1,
                max=16,
                hide_details=True,
                dense=True,
                outlined=True,
                style="max-width: 90px;",
                classes="mr-2",
            )

            # Save the annotated mesh to file
            vuetify.VBtn(
                click=ctrl.save_tags,
                small=True,
                color="success",
                classes="mr-2",
                children=["Save Tags"],
                disabled=("!selected_file",),
                title="Save mesh with BoundaryID array to _tagged.vtp/.vtu",
            )

            # Feedback chip showing save result
            vuetify.VChip(
                v_show=("save_status",),
                small=True,
                classes="mr-2",
                children=("{{ save_status }}",),
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
