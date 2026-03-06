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
                items=(
                    [REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS],
                ),
                label="Representation",
                hide_details=True,
                dense=True,
                outlined=True,
                style="max-width: 150px;",
                classes="mr-2",
            )

            # Edit mode toggle
            vuetify.VBtn(
                "Edit Mode",
                small=True,
                outlined=("!edit_mode",),
                color=("edit_mode ? 'primary' : ''",),
                click="edit_mode = !edit_mode",
                classes="mr-2",
                v_show=("has_boundary",),
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

                # Edit mode side panel
                with vuetify.VNavigationDrawer(
                    v_model=("edit_mode",),
                    right=True,
                    absolute=True,
                    width="260",
                    style="z-index: 5;",
                ):
                    with vuetify.VList(dense=True):

                        vuetify.VSubheader("Interaction Mode")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                with vuetify.VRow(dense=True, classes="px-2"):
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Pick",
                                            small=True,
                                            block=True,
                                            color=("pick_mode ? 'primary' : ''",),
                                            outlined=("!pick_mode",),
                                            click="pick_mode = true",
                                        )
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Rotate",
                                            small=True,
                                            block=True,
                                            color=("!pick_mode ? 'primary' : ''",),
                                            outlined=("pick_mode",),
                                            click="pick_mode = false",
                                        )
                        vuetify.VDivider(classes="my-2")
                        vuetify.VSubheader("Selection")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle(
                                    "{{ selection_count }} cells selected"
                                )

                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                with vuetify.VRow(dense=True, classes="px-2"):
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Clear",
                                            small=True,
                                            outlined=True,
                                            block=True,
                                            click=ctrl.clear_selection,
                                            disabled=("selection_count === 0",),
                                        )
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Select All",
                                            small=True,
                                            outlined=True,
                                            block=True,
                                            click=ctrl.select_all,
                                        )

                        with vuetify.VListItem(
                            dense=True,
                        ):
                            with vuetify.VListItemContent(
                                classes="pt-0",
                            ):
                                vuetify.VSwitch(
                                    v_model=("group_select",),
                                    label="Select Flat Region",
                                    hide_details=True,
                                    dense=True,
                                    classes="pl-2",
                                )
                        with vuetify.VListItem(dense=True):
                            with vuetify.VRow(
                                dense=True,
                                align="center",
                                no_gutters=True,
                                classes="px-2",
                            ):
                                with vuetify.VCol():
                                    vuetify.VSlider(
                                        v_model=("angle_threshold",),
                                        label="Angle",
                                        min=0,
                                        max=90,
                                        step=1,
                                        hide_details=True,
                                        dense=True,
                                        disabled=("!group_select",),
                                    )
                                with vuetify.VCol(cols="auto"):
                                    vuetify.VChip(
                                        "{{ angle_threshold }}°",
                                        x_small=True,
                                        disabled=("!group_select",),
                                    )

                        vuetify.VDivider(classes="my-2")
                        vuetify.VSubheader("Assign Boundary ID")

                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VTextField(
                                    v_model=("assign_id_value",),
                                    label="Value",
                                    type="number",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                )

                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VBtn(
                                    "Assign to Selected",
                                    small=True,
                                    color="primary",
                                    block=True,
                                    click=ctrl.assign_id,
                                    disabled=("selection_count === 0",),
                                )

                        vuetify.VDivider(classes="my-2")
                        vuetify.VSubheader("Save")

                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VTextField(
                                    v_model=("save_filename",),
                                    label="Filename",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    suffix=".vtu",
                                )

                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VBtn(
                                    "Save as .vtu",
                                    small=True,
                                    color="success",
                                    block=True,
                                    click=ctrl.save_vtu,
                                )

                        with vuetify.VListItem(v_show=("save_status",)):
                            with vuetify.VListItemContent():
                                vuetify.VAlert(
                                    type=("save_status_type",),
                                    dense=True,
                                    children=["{{ save_status }}"],
                                    classes="ma-0",
                                )

                # VTK view
                view = vtk.VtkRemoteView(
                    renderWindow,
                    ref="view",
                    style="width: 100%; height: 100%;",
                )
                ctrl.view_update = view.update

    return layout
