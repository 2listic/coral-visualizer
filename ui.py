from trame.ui.vuetify import SinglePageLayout
from trame.widgets import html, vuetify

from constants import REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS


def _build_view_widget(backend, render_target):
    """Create the correct Trame widget for the selected rendering backend."""
    if backend == "paraview":
        from trame.widgets import paraview as pv_widgets

        return pv_widgets.VtkRemoteView(
            render_target,
            ref="view",
            interactive_ratio=("interactive_ratio",),
            still_ratio=("still_ratio",),
            interactive_quality=("interactive_quality",),
            still_quality=("still_quality",),
            style="width: 100%; height: 100%;",
        )

    from trame.widgets import vtk

    return vtk.VtkRemoteView(
        render_target,
        ref="view",
        interactive_ratio=("interactive_ratio",),
        still_ratio=("still_ratio",),
        interactive_quality=("interactive_quality",),
        still_quality=("still_quality",),
        style="width: 100%; height: 100%;",
    )


def _build_alerts():
    vuetify.VAlert(
        v_show=("error_message",),
        type="error",
        dense=True,
        dismissible=True,
        v_model=("error_message",),
        children=("{{ error_message }}",),
        style="position: absolute; top: 10px; left: 10px; right: 10px; z-index: 1000;",
    )
    vuetify.VAlert(
        v_show=("backend_message",),
        type="info",
        dense=True,
        dismissible=True,
        v_model=("backend_message",),
        children=("{{ backend_message }}",),
        style="position: absolute; top: 68px; left: 10px; right: 10px; z-index: 999;",
    )
    vuetify.VAlert(
        v_show=("upload_status",),
        type=("upload_status_type",),
        dense=True,
        dismissible=True,
        v_model=("upload_status",),
        children=("{{ upload_status }}",),
        style="position: absolute; top: 126px; left: 10px; right: 10px; z-index: 998;",
    )


def _build_toolbar(ctrl, backend):
    vuetify.VToolbarTitle("Coral Visualizer")
    vuetify.VDivider(vertical=True, classes="mx-4")
    html.Input(
        ref="filePicker",
        type="file",
        accept=".vtk,.vtu,.pvtu",
        style="display: none;",
        change=(ctrl.upload_dataset, "[$event.target.files]"),
        __events=["change"],
    )
    vuetify.VBtn(
        "Upload",
        small=True,
        outlined=True,
        click="$refs.filePicker.value = null; $refs.filePicker.click()",
        classes="mr-2",
    )
    vuetify.VBtn(
        "Open Remote",
        small=True,
        outlined=True,
        click="remote_browser_dialog = true",
        classes="mr-2",
    )
    if backend == "vtk":
        vuetify.VSelect(
            v_model=("selected_file",),
            items=("available_files",),
            label="Loaded Files",
            hide_details=True,
            dense=True,
            outlined=True,
            style="max-width: 240px;",
            classes="mr-2",
        )
        vuetify.VSelect(
            v_model=("selected_array",),
            items=("available_arrays",),
            label="Color by",
            hide_details=True,
            dense=True,
            outlined=True,
            style="max-width: 170px;",
            classes="mr-2",
            disabled=("edit_mode",),
        )
        vuetify.VSelect(
            v_model=("representation",),
            items=([REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS],),
            label="Representation",
            hide_details=True,
            dense=True,
            outlined=True,
            style="max-width: 180px;",
            classes="mr-2",
        )
    vuetify.VSpacer()


def _build_remote_browser_dialog(ctrl):
    with vuetify.VDialog(v_model=("remote_browser_dialog",), max_width="720"):
        with vuetify.VCard():
            vuetify.VCardTitle("Open Remote Data")
            with vuetify.VCardText():
                vuetify.VAlert(
                    dense=True,
                    text=True,
                    type="info",
                    children=[
                        "Browse files already available on the server under --data-directory."
                    ],
                )
                with vuetify.VList(
                    dense=True,
                    style="max-height: 420px; overflow-y: auto; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                ):
                    with vuetify.Template(v_for="item in available_files"):
                        vuetify.VSubheader(
                            "{{ item.header }}",
                            v_if="item.header",
                        )
                        vuetify.VDivider(v_if="item.divider")
                        with vuetify.VListItem(
                            v_if="item.value",
                            click=(ctrl.open_remote_file, "[item.value]"),
                        ):
                            with vuetify.VListItemIcon():
                                vuetify.VIcon("mdi-file-outline")
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.text }}")
                                vuetify.VListItemSubtitle("{{ item.path }}")
            with vuetify.VCardActions():
                vuetify.VSpacer()
                vuetify.VBtn(
                    "Close",
                    text=True,
                    click="remote_browser_dialog = false",
                )


def _build_property_action_row(ctrl, classes="mb-2"):
    with vuetify.VRow(classes=classes):
        with vuetify.VCol(cols=6):
            vuetify.VBtn(
                "Apply",
                small=True,
                block=True,
                color="primary",
                click=ctrl.pv_apply_properties,
                disabled=("!pv_properties_dirty",),
            )
        with vuetify.VCol(cols=6):
            vuetify.VBtn(
                "Cancel",
                small=True,
                block=True,
                outlined=True,
                click=ctrl.pv_reset_properties,
                disabled=("!pv_properties_dirty",),
            )


def _build_property_action_bar(ctrl):
    with vuetify.VSheet(
        classes="px-4 py-2",
        style="background: #fafafa; border-bottom: 1px solid rgba(0,0,0,0.08); flex: 0 0 auto;",
    ):
        _build_property_action_row(ctrl, classes="mb-0")
        vuetify.VAlert(
            v_if="pv_properties_dirty",
            type="info",
            dense=True,
            text=True,
            classes="mt-1 mb-0",
            children=[
                "You have unapplied property changes for the active pipeline item."
            ],
        )


def _build_inspector_tab_selector():
    with vuetify.VSheet(
        classes="px-4 pt-3",
        style="background: #fafafa; border-bottom: 1px solid rgba(0,0,0,0.08); flex: 0 0 auto;",
    ):
        with vuetify.VRow(no_gutters=True, classes="align-center"):
            with vuetify.VCol(cols=4):
                with vuetify.VSheet(color="transparent"):
                    vuetify.VBtn(
                        "Display",
                        block=True,
                        text=True,
                        tile=True,
                        color=("inspector_tab === 0 ? 'primary' : 'grey darken-1'",),
                        click="inspector_tab = 0",
                        style="border-radius: 0; height: 56px; font-size: 0.95rem; letter-spacing: 0; text-transform: none; padding: 0 4px;",
                    )
                    vuetify.VSheet(
                        height="3",
                        color=("inspector_tab === 0 ? 'primary' : 'transparent'",),
                    )
            with vuetify.VCol(cols=4):
                with vuetify.VSheet(color="transparent"):
                    vuetify.VBtn(
                        "Information",
                        block=True,
                        text=True,
                        tile=True,
                        color=("inspector_tab === 1 ? 'primary' : 'grey darken-1'",),
                        click="inspector_tab = 1",
                        style="border-radius: 0; height: 56px; font-size: 0.95rem; letter-spacing: 0; text-transform: none; padding: 0 4px;",
                    )
                    vuetify.VSheet(
                        height="3",
                        color=("inspector_tab === 1 ? 'primary' : 'transparent'",),
                    )
            with vuetify.VCol(cols=4):
                with vuetify.VSheet(color="transparent"):
                    vuetify.VBtn(
                        "Properties",
                        block=True,
                        text=True,
                        tile=True,
                        color=("inspector_tab === 2 ? 'primary' : 'grey darken-1'",),
                        click="inspector_tab = 2",
                        style="border-radius: 0; height: 56px; font-size: 0.95rem; letter-spacing: 0; text-transform: none; padding: 0 4px;",
                    )
                    vuetify.VSheet(
                        height="3",
                        color=("inspector_tab === 2 ? 'primary' : 'transparent'",),
                    )


def _build_paraview_pipeline_panel(ctrl):
    with vuetify.VNavigationDrawer(
        app=True,
        clipped=True,
        permanent=True,
        width=280,
        style="border-right: 1px solid rgba(0,0,0,0.08);",
    ):
        with vuetify.VSheet(classes="pa-4", style="height: 100%; background: #f5f5f7;"):
            vuetify.VSubheader(classes="px-0", children=["Pipeline Browser"])
            with vuetify.VList(
                dense=True,
                nav=True,
                style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
            ):
                with vuetify.VListItemGroup(
                    v_model=("active_pipeline_item",),
                    mandatory=False,
                    color="primary",
                ):
                    with vuetify.Template(v_for="item in pipeline_items"):
                        with vuetify.VListItem(
                            key=("item.value",),
                            value=("item.value",),
                        ):
                            with vuetify.VListItemIcon():
                                vuetify.VIcon("{{ item.icon || 'mdi-database-outline' }}")
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.text }}")

            vuetify.VDivider(classes="my-4")
            vuetify.VSubheader(classes="px-0", children=["Source"])
            with vuetify.VList(
                dense=True,
                style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
            ):
                with vuetify.VListItem():
                    with vuetify.VListItemContent():
                        vuetify.VListItemSubtitle("Active")
                        vuetify.VListItemTitle("{{ active_source_label || 'No source loaded' }}")
                with vuetify.VListItem():
                    with vuetify.VListItemContent():
                        vuetify.VListItemSubtitle("Reader Type")
                        vuetify.VListItemTitle("{{ active_source_type || 'N/A' }}")
                with vuetify.VListItem():
                    with vuetify.VListItemContent():
                        with vuetify.VRow(dense=True):
                            with vuetify.VCol(cols=6):
                                vuetify.VBtn(
                                    small=True,
                                    block=True,
                                    outlined=True,
                                    click=ctrl.pv_toggle_visibility,
                                    children=["{{ active_visibility ? 'Hide' : 'Show' }}"],
                                    disabled=("!active_pipeline_item",),
                                )
                            with vuetify.VCol(cols=6):
                                vuetify.VBtn(
                                    "Delete",
                                    small=True,
                                    block=True,
                                    outlined=True,
                                    click=ctrl.pv_delete_active,
                                    disabled=("!active_pipeline_item",),
                                )

            vuetify.VDivider(classes="my-4")
            vuetify.VSubheader(classes="px-0", children=["Workflow"])
            vuetify.VAlert(
                type="info",
                dense=True,
                outlined=True,
                children=[
                    "Loading a file adds a new pipeline source. Selecting a node drives the inspector and display controls."
                ],
            )


def _build_paraview_inspector_panel(ctrl):
    with vuetify.VNavigationDrawer(
        app=True,
        clipped=True,
        right=True,
        permanent=True,
        width=340,
        style="border-left: 1px solid rgba(0,0,0,0.08);",
    ):
        with vuetify.VSheet(
            style="background: #fafafa; min-height: 100%; display: flex; flex-direction: column;"
        ):
            _build_property_action_bar(ctrl)
            _build_inspector_tab_selector()
            with vuetify.VSheet(
                style="flex: 1 1 auto; overflow-y: auto; background: #fafafa;"
            ):
                with vuetify.VContainer(fluid=True, classes="pa-4", v_show="inspector_tab === 0"):
                    vuetify.VSubheader(classes="px-0", children=["Display"])
                    vuetify.VSelect(
                        v_model=("selected_array",),
                        items=("available_arrays",),
                        label="Color by",
                        dense=True,
                        outlined=True,
                        hide_details=True,
                        classes="mb-3",
                    )
                    vuetify.VSelect(
                        v_model=("representation",),
                        items=([REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS],),
                        label="Representation",
                        dense=True,
                        outlined=True,
                        hide_details=True,
                        classes="mb-3",
                    )
                    vuetify.VSelect(
                        v_model=("interaction_quality",),
                        items=("interaction_quality_options",),
                        label="Interaction quality",
                        dense=True,
                        outlined=True,
                        hide_details=True,
                        classes="mb-3",
                    )
                    vuetify.VBtn(
                        "Reset Camera",
                        small=True,
                        outlined=True,
                        click=ctrl.reset_camera,
                    )
                    vuetify.VDivider(classes="my-4")
                    vuetify.VSubheader(classes="px-0", children=["Advanced Display Controls"])
                    vuetify.VAlert(
                        v_if="display_default_property_count + display_advanced_property_count === 0",
                        type="info",
                        dense=True,
                        outlined=True,
                        classes="mb-4",
                        children=[
                            "No additional display controls are exposed for the active representation."
                        ],
                    )
                    _build_property_list(ctrl, "display_properties")

                with vuetify.VContainer(fluid=True, classes="pa-4", v_show="inspector_tab === 1"):
                    vuetify.VSubheader(classes="px-0", children=["Information"])
                    with vuetify.VList(
                        dense=True,
                        two_line=True,
                        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                    ):
                        with vuetify.Template(v_for="item in data_stats"):
                            with vuetify.VListItem():
                                with vuetify.VListItemContent():
                                    vuetify.VListItemTitle("{{ item.value }}")
                                    vuetify.VListItemSubtitle("{{ item.label }}")

                    vuetify.VDivider(classes="my-4")
                    vuetify.VSubheader(classes="px-0", children=["Point Arrays"])
                    with vuetify.VChipGroup(column=True):
                        with vuetify.Template(v_for="item in point_arrays"):
                            vuetify.VChip(
                                "{{ item.text }}",
                                x_small=True,
                                classes="ma-1",
                            )
                    vuetify.VDivider(classes="my-4")
                    vuetify.VSubheader(classes="px-0", children=["Cell Arrays"])
                    with vuetify.VChipGroup(column=True):
                        with vuetify.Template(v_for="item in cell_arrays"):
                            vuetify.VChip(
                                "{{ item.text }}",
                                x_small=True,
                                classes="ma-1",
                            )

                with vuetify.VContainer(fluid=True, classes="pa-4", v_show="inspector_tab === 2"):
                    vuetify.VSubheader(classes="px-0", children=["Properties"])
                    with vuetify.VList(
                        dense=True,
                        two_line=True,
                        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                        classes="mb-4",
                    ):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ active_source_label || 'No source selected' }}")
                                vuetify.VListItemSubtitle("Active source")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ active_source_type || 'N/A' }}")
                                vuetify.VListItemSubtitle("Reader / proxy type")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ source_path || 'N/A' }}")
                                vuetify.VListItemSubtitle("Source path")
                    vuetify.VAlert(
                        v_if="source_default_property_count + source_advanced_property_count === 0",
                        type="info",
                        dense=True,
                        outlined=True,
                        classes="mb-4",
                        children=[
                            "This reader does not expose configurable source properties for the current dataset."
                        ],
                    )
                    _build_property_list(ctrl, "source_properties")
                    vuetify.VAlert(
                        type="info",
                        dense=True,
                        text=True,
                        children=[
                            "This tab shows reader/source controls for the active pipeline item. Display styling belongs in the Display tab."
                        ],
                    )


def _build_property_list(ctrl, state_key):
    with vuetify.VExpansionPanels(accordion=True, flat=True, style="background: transparent;"):
        with vuetify.VExpansionPanel():
            with vuetify.VExpansionPanelHeader(children=["Default"]):
                pass
            with vuetify.VExpansionPanelContent():
                vuetify.VAlert(
                    v_if=f"{state_key}.filter((entry) => entry.visibility === 'default').length === 0",
                    type="info",
                    dense=True,
                    text=True,
                    children=["No default properties available."],
                )
                with vuetify.VList(
                    dense=True,
                    v_if=f"{state_key}.filter((entry) => entry.visibility === 'default').length > 0",
                    style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                ):
                    with vuetify.Template(v_for=f"item in {state_key}.filter((entry) => entry.visibility === 'default')"):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.label }}")
                                vuetify.VListItemSubtitle("{{ item.type }}")
                            with vuetify.VListItemAction(v_if="item.type"):
                                vuetify.VChip("{{ item.type }}", x_small=True, label=True)
                        with vuetify.VListItem(v_if="item.editable && item.type === 'StringListProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'EnumerationProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'ArrayListProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VCombobox(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Selected Arrays",
                                    multiple=True,
                                    chips=True,
                                    deletable_chips=True,
                                    small_chips=True,
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'VectorProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VTextField(
                                    value=("item.pending_value",),
                                    label="Value",
                                    type="number",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="!item.editable"):
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("{{ item.value || ' ' }}")

        with vuetify.VExpansionPanel():
            with vuetify.VExpansionPanelHeader(children=["Advanced"]):
                pass
            with vuetify.VExpansionPanelContent():
                vuetify.VAlert(
                    v_if=f"{state_key}.filter((entry) => entry.visibility === 'advanced').length === 0",
                    type="info",
                    dense=True,
                    text=True,
                    children=["No advanced properties available."],
                )
                with vuetify.VList(
                    dense=True,
                    v_if=f"{state_key}.filter((entry) => entry.visibility === 'advanced').length > 0",
                    style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                ):
                    with vuetify.Template(v_for=f"item in {state_key}.filter((entry) => entry.visibility === 'advanced')"):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.label }}")
                                vuetify.VListItemSubtitle("{{ item.type }}")
                            with vuetify.VListItemAction(v_if="item.type"):
                                vuetify.VChip("{{ item.type }}", x_small=True, label=True)
                        with vuetify.VListItem(v_if="item.editable && item.type === 'StringListProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'EnumerationProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'ArrayListProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VCombobox(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Selected Arrays",
                                    multiple=True,
                                    chips=True,
                                    deletable_chips=True,
                                    small_chips=True,
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'VectorProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VTextField(
                                    value=("item.pending_value",),
                                    label="Value",
                                    type="number",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="!item.editable"):
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("{{ item.value || ' ' }}")


def _build_vtk_edit_panel(ctrl):
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
            vuetify.VSubheader("Edit Target")
            with vuetify.VListItem():
                with vuetify.VListItemContent():
                    with vuetify.VRow(dense=True, classes="px-2"):
                        with vuetify.VCol(cols=6):
                            vuetify.VBtn(
                                "Boundary",
                                small=True,
                                block=True,
                                color=("edit_target === 'boundary' ? 'primary' : ''",),
                                outlined=("edit_target !== 'boundary'",),
                                click="edit_target = 'boundary'",
                            )
                        with vuetify.VCol(cols=6):
                            vuetify.VBtn(
                                "Volume",
                                small=True,
                                block=True,
                                color=("edit_target === 'volume' ? 'primary' : ''",),
                                outlined=("edit_target !== 'volume'",),
                                click="edit_target = 'volume'",
                            )
            vuetify.VSubheader("Selection")
            with vuetify.VListItem():
                with vuetify.VListItemContent():
                    vuetify.VListItemTitle("{{ selection_count }} cells selected")
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
            with vuetify.VListItem(dense=True):
                with vuetify.VListItemContent(classes="pt-0"):
                    vuetify.VSwitch(
                        v_model=("group_select",),
                        label="Select Flat Region",
                        hide_details=True,
                        dense=True,
                        classes="pl-2",
                        disabled=("edit_target === 'volume'",),
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
                            disabled=("!group_select || edit_target === 'volume'",),
                        )
                    with vuetify.VCol(cols="auto"):
                        vuetify.VChip(
                            "{{ angle_threshold }}°",
                            x_small=True,
                            disabled=("!group_select || edit_target === 'volume'",),
                        )

            vuetify.VSubheader(
                "{{ edit_target === 'volume' ? 'Assign Material ID' : 'Assign Boundary ID' }}"
            )
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


def build_ui(server, render_target, backend):
    """Build the Trame UI layout."""
    ctrl = server.controller

    with SinglePageLayout(server) as layout:
        layout.title.set_text("")
        layout.icon.hide()

        with layout.toolbar:
            _build_toolbar(ctrl, backend)
            if backend == "vtk":
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
                style="position: relative; max-width: none;",
            ):
                _build_alerts()
                _build_remote_browser_dialog(ctrl)

                if backend == "paraview":
                    _build_paraview_pipeline_panel(ctrl)
                    _build_paraview_inspector_panel(ctrl)
                else:
                    _build_vtk_edit_panel(ctrl)

                view = _build_view_widget(backend, render_target)
                ctrl.view_update = view.update

    return layout
