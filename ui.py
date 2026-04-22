from trame.ui.vuetify import SinglePageLayout
from trame.widgets import html, vuetify

from constants import REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS


def _build_view_widget(backend, render_target, ctrl=None):
    """Create the correct Trame widget for the selected rendering backend."""
    if backend == "paraview":
        from trame.widgets import paraview as pv_widgets

        return pv_widgets.VtkRemoteLocalView(
            render_target,
            namespace="mainView",
            ref="view",
            mode=("mainViewMode", "remote"),
            disable_auto_switch=True,
            interactive_ratio=("interactive_ratio",),
            still_ratio=("still_ratio",),
            interactive_quality=("interactive_quality",),
            still_quality=("still_quality",),
            enable_picking=("edit_enable_picking",),
            box_selection=("edit_session_active && pick_mode",),
            picking_modes=("edit_picking_modes",),
            interactor_events=("edit_interactor_events",),
            interactor_settings=("edit_interactor_settings",),
            click=(ctrl.pv_edit_click_selection, "[$event]"),
            box_selection_change=(ctrl.pv_edit_box_selection, "[$event]"),
            on_ready=ctrl.view_update,
            classes="coral-main-viewport",
            style=("edit_view_style", "width: 100%; height: 100%; cursor: crosshair; outline: none;"),
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
    vuetify.VAlert(
        v_show=("pv_runtime_message",),
        type=("pv_runtime_type",),
        dense=True,
        dismissible=True,
        v_model=("pv_runtime_message",),
        children=("{{ pv_runtime_message }}",),
        style="position: absolute; top: 184px; left: 10px; right: 10px; z-index: 997; white-space: pre-line;",
    )


def _build_toolbar(ctrl, backend):
    vuetify.VToolbarTitle("Coral VTK Manipulator")
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
    if backend == "paraview":
        vuetify.VBtn(
            "Enter Edit Mode",
            small=True,
            outlined=True,
            click=ctrl.pv_begin_edit_session,
            disabled=("!can_edit_active",),
            v_if="!edit_session_active",
            classes="mr-2",
        )
        vuetify.VBtn(
            "{{ edit_session_active ? 'Save Edit Result' : 'Save Result' }}",
            small=True,
            color="primary",
            click=ctrl.pv_save_active_data,
            disabled=("!active_pipeline_item && !edit_session_active",),
            classes="mr-2",
        )
        vuetify.VTextField(
            v_model=("save_filename",),
            label="Output filename",
            dense=True,
            outlined=True,
            hide_details=True,
            classes="mr-2",
            style="max-width: 260px;",
        )
        vuetify.VBtn(
            "Save And Add To Pipeline",
            small=True,
            outlined=True,
            color="primary",
            click=ctrl.pv_commit_edit_session,
            v_if="edit_session_active",
            classes="mr-2",
        )
        vuetify.VBtn(
            "Discard",
            small=True,
            outlined=True,
            click=ctrl.pv_discard_edit_session,
            v_if="edit_session_active",
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
        with vuetify.VRow(classes="mb-2"):
            with vuetify.VCol(cols=6):
                vuetify.VBtn(
                    "Reset Camera",
                    small=True,
                    block=True,
                    outlined=True,
                    click=ctrl.reset_camera,
                )
            with vuetify.VCol(cols=6):
                vuetify.VBtn(
                    "Reset View",
                    small=True,
                    block=True,
                    outlined=True,
                    click=ctrl.reset_view,
                )
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
            with vuetify.VCol(cols=("edit_session_active ? 3 : 4",)):
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
            with vuetify.VCol(cols=("edit_session_active ? 3 : 4",)):
                with vuetify.VSheet(color="transparent"):
                    vuetify.VBtn(
                        "Properties",
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
            with vuetify.VCol(cols=("edit_session_active ? 3 : 4",)):
                with vuetify.VSheet(color="transparent"):
                    vuetify.VBtn(
                        "Information",
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
            with vuetify.VCol(cols=3, v_if="edit_session_active"):
                with vuetify.VSheet(color="transparent"):
                    vuetify.VBtn(
                        "Edit",
                        block=True,
                        text=True,
                        tile=True,
                        color=("inspector_tab === 3 ? 'primary' : 'grey darken-1'",),
                        click="inspector_tab = 3",
                        style="border-radius: 0; height: 56px; font-size: 0.95rem; letter-spacing: 0; text-transform: none; padding: 0 4px;",
                    )
                    vuetify.VSheet(
                        height="3",
                        color=("inspector_tab === 3 ? 'primary' : 'transparent'",),
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
                            style=("item.depth ? 'margin-left: ' + (item.depth * 16) + 'px;' : ''",),
                        ):
                            with vuetify.VListItemIcon():
                                vuetify.VIcon("{{ item.node_icon || 'mdi-database-outline' }}")
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.text }}")
                            with vuetify.VListItemAction():
                                with vuetify.VBtn(
                                    icon=True,
                                    small=True,
                                    click=(ctrl.pv_toggle_visibility_for, "[item.value]"),
                                ):
                                    vuetify.VIcon(
                                        "{{ item.visibility_icon || 'mdi-eye-outline' }}",
                                        small=True,
                                        color="grey darken-1",
                                    )

            vuetify.VDivider(classes="my-4")
            vuetify.VSubheader(classes="px-0", children=["Selected Pipeline Item"])
            with vuetify.VList(
                dense=True,
                style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
            ):
                with vuetify.VListItem():
                    with vuetify.VListItemContent():
                        vuetify.VListItemSubtitle("Selected")
                        vuetify.VListItemTitle("{{ active_source_label || 'No source loaded' }}")
                with vuetify.VListItem():
                    with vuetify.VListItemContent():
                        vuetify.VListItemSubtitle("{{ active_source_kind }}")
                        vuetify.VListItemTitle("{{ active_source_type || 'N/A' }}")
                with vuetify.VListItem():
                    with vuetify.VListItemContent():
                        with vuetify.VRow(dense=True, classes="px-2"):
                            with vuetify.VCol(cols=12):
                                vuetify.VBtn(
                                    small=True,
                                    block=True,
                                    outlined=True,
                                    click=ctrl.pv_toggle_visibility,
                                    children=["{{ active_visibility ? 'Hide' : 'Show' }}"],
                                    disabled=("!active_pipeline_item",),
                                    classes="mb-2",
                                )
                            with vuetify.VCol(cols=12):
                                with vuetify.VMenu(
                                    v_model=("filter_menu",),
                                    close_on_content_click=False,
                                    offset_y=True,
                                ):
                                    with vuetify.Template(v_slot_activator="{ on, attrs }"):
                                        vuetify.VBtn(
                                            "Filter",
                                            small=True,
                                            block=True,
                                            outlined=True,
                                            disabled=("!active_pipeline_item",),
                                            v_bind="attrs",
                                            v_on="on",
                                            classes="mb-2",
                                        )
                                    with vuetify.VCard(min_width="280"):
                                        with vuetify.VCardText(classes="pb-0"):
                                            vuetify.VTextField(
                                                v_model=("filter_search",),
                                                label="Search filters",
                                                dense=True,
                                                outlined=True,
                                                clearable=True,
                                                hide_details=True,
                                            )
                                        with vuetify.VList(
                                            dense=True,
                                            style="max-height: 360px; overflow-y: auto;",
                                        ):
                                            vuetify.VSubheader(
                                                v_if="filter_supported_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase())).length",
                                                children=["Supported"],
                                            )
                                            with vuetify.Template(
                                                v_for="item in filter_supported_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase()))"
                                            ):
                                                with vuetify.VListItem(
                                                    click=(ctrl.pv_add_filter, "[item.value]")
                                                ):
                                                    with vuetify.VListItemIcon():
                                                        vuetify.VIcon("{{ item.icon }}")
                                                    with vuetify.VListItemContent():
                                                        vuetify.VListItemTitle("{{ item.text }}")
                                            vuetify.VDivider(
                                                v_if="show_experimental_filters && filter_supported_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase())).length && filter_experimental_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase())).length"
                                            )
                                            vuetify.VSubheader(
                                                v_if="show_experimental_filters && filter_experimental_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase())).length",
                                                children=["Experimental"],
                                            )
                                            with vuetify.Template(
                                                v_for="item in filter_experimental_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase()))",
                                                v_if="show_experimental_filters"
                                            ):
                                                with vuetify.VListItem(
                                                    click=(ctrl.pv_add_filter, "[item.value]")
                                                ):
                                                    with vuetify.VListItemIcon():
                                                        vuetify.VIcon("{{ item.icon }}")
                                                    with vuetify.VListItemContent():
                                                        vuetify.VListItemTitle("{{ item.text }}")
                            with vuetify.VCol(cols=12):
                                vuetify.VBtn(
                                    "Delete Selected",
                                    small=True,
                                    block=True,
                                    outlined=True,
                                    click=ctrl.pv_delete_active,
                                    disabled=("!active_pipeline_item",),
                                )
                with vuetify.VListItem():
                    with vuetify.VListItemContent():
                        vuetify.VListItemSubtitle("Save target")
                        vuetify.VListItemTitle("{{ save_target_label }}")
                with vuetify.VListItem(v_if="edit_session_active"):
                    with vuetify.VListItemContent():
                        vuetify.VListItemSubtitle("Edit session")
                        vuetify.VListItemTitle("{{ edit_session_label }}")
                with vuetify.VListItem(v_show=("edit_status",)):
                    with vuetify.VListItemContent():
                        vuetify.VAlert(
                            type=("edit_status_type",),
                            dense=True,
                            children=["{{ edit_status }}"],
                            classes="ma-0",
                        )
                with vuetify.VListItem(v_if="edit_session_active"):
                    with vuetify.VListItemContent():
                        vuetify.VDivider(classes="my-2")
                        vuetify.VListItemSubtitle("Edit Mode")
                        vuetify.VSelect(
                            v_model=("edit_geometry_mode",),
                            items=("edit_geometry_mode_options",),
                            item_text="text",
                            item_value="value",
                            label="Geometry mode",
                            dense=True,
                            outlined=True,
                            hide_details=True,
                            classes="mt-2 mb-2",
                        )
                        vuetify.VTextField(
                            v_model=("edit_field_name",),
                            label="Field name",
                            dense=True,
                            outlined=True,
                            hide_details=True,
                            classes="mb-2",
                        )
                        vuetify.VTextField(
                            v_model=("edit_expression",),
                            label="Calculator",
                            dense=True,
                            outlined=True,
                            hide_details=True,
                            hint="Leave empty to write the default value everywhere",
                            persistent_hint=True,
                            classes="mb-2",
                        )
                        vuetify.VTextField(
                            v_model=("edit_default_value",),
                            label="Default value",
                            dense=True,
                            outlined=True,
                            hide_details=True,
                            classes="mb-2",
                        )
                        with vuetify.VList(
                            dense=True,
                            two_line=True,
                            style="background: rgba(255,255,255,0.7); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                            classes="mb-2",
                        ):
                            with vuetify.VListItem():
                                with vuetify.VListItemContent():
                                    vuetify.VListItemSubtitle("Available cell variables")
                                    vuetify.VAlert(
                                        v_if="edit_available_variables.length === 0",
                                        type="info",
                                        dense=True,
                                        text=True,
                                        children=["No cell-data variables are available on the edit-session dataset."],
                                    )
                                    with vuetify.VChipGroup(column=True, v_if="edit_available_variables.length > 0"):
                                        with vuetify.Template(v_for="item in edit_available_variables"):
                                            vuetify.VChip("{{ item }}", x_small=True, classes="ma-1")
                            with vuetify.VListItem():
                                with vuetify.VListItemContent():
                                    vuetify.VListItemSubtitle("Vector component syntax")
                                    vuetify.VListItemTitle("{{ edit_vector_syntax }}")
                        vuetify.VBtn(
                            "Apply Edit",
                            small=True,
                            block=True,
                            color="primary",
                            outlined=True,
                            click=ctrl.pv_apply_edit_field,
                            classes="mb-2",
                        )
                        with vuetify.VDialog(
                            v_model=("edit_overwrite_dialog",),
                            max_width="560",
                        ):
                            with vuetify.VCard():
                                vuetify.VCardTitle("Overwrite Existing Field?")
                                with vuetify.VCardText():
                                    vuetify.VAlert(
                                        type="warning",
                                        dense=True,
                                        outlined=True,
                                        children=[
                                            "Field '{{ edit_overwrite_field_name }}' already exists. "
                                            "Overwrite will remove the existing field and replace it "
                                            "with the newly generated values."
                                        ],
                                    )
                                with vuetify.VCardActions():
                                    vuetify.VSpacer()
                                    vuetify.VBtn(
                                        "Cancel",
                                        text=True,
                                        click=ctrl.pv_cancel_overwrite_edit_field,
                                    )
                                    vuetify.VBtn(
                                        "Overwrite",
                                        color="warning",
                                        text=True,
                                        click=ctrl.pv_confirm_overwrite_edit_field,
                                    )
                        vuetify.VAlert(
                            v_show=("edit_apply_status",),
                            type=("edit_apply_status_type",),
                            dense=True,
                            children=["{{ edit_apply_status }}"],
                            classes="ma-0",
                        )
                with vuetify.VListItem(v_show=("save_status",)):
                    with vuetify.VListItemContent():
                        vuetify.VAlert(
                            type=("save_status_type",),
                            dense=True,
                            children=["{{ save_status }}"],
                            classes="ma-0",
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
                                vuetify.VListItemSubtitle("{{ active_source_kind }}")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ source_path || 'N/A' }}")
                                vuetify.VListItemSubtitle("Source path")
                        with vuetify.VListItem(v_if="active_parent_label"):
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ active_parent_label }}")
                                vuetify.VListItemSubtitle("Applied to")
                    with vuetify.VList(
                        v_if="show_calculator_help",
                        dense=True,
                        two_line=True,
                        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                        classes="mb-4",
                    ):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ calculator_attribute_type || 'Point Data' }}")
                                vuetify.VListItemSubtitle("Calculator association")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("Coordinate variables")
                                with vuetify.VChipGroup(column=True):
                                    with vuetify.Template(v_for="item in calculator_coordinate_variables"):
                                        vuetify.VChip("{{ item }}", x_small=True, classes="ma-1")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("Vector component syntax")
                                vuetify.VListItemTitle("Use arrayName[0], arrayName[1], arrayName[2]")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("Input array variables")
                                vuetify.VAlert(
                                    v_if="calculator_input_variables.length === 0",
                                    type="info",
                                    dense=True,
                                    text=True,
                                    children=["No arrays available for the current Calculator association."],
                                )
                                with vuetify.VChipGroup(column=True, v_if="calculator_input_variables.length > 0"):
                                    with vuetify.Template(v_for="item in calculator_input_variables"):
                                        vuetify.VChip("{{ item }}", x_small=True, classes="ma-1")
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

                with vuetify.VContainer(fluid=True, classes="pa-4", v_show="inspector_tab === 2"):
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

                with vuetify.VContainer(fluid=True, classes="pa-4", v_show="edit_session_active && inspector_tab === 3"):
                    vuetify.VSubheader(classes="px-0", children=["Edit Tools"])
                    with vuetify.VList(
                        dense=True,
                        two_line=True,
                        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                        classes="mb-4",
                    ):
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
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    v_model=("edit_selection_mode",),
                                    items=("edit_selection_mode_options",),
                                    label="Selection mode",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    disabled=("!pick_mode",),
                                )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    v_model=("selection_behavior",),
                                    items=("selection_behavior_options",),
                                    label="Selection behavior",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    disabled=("!pick_mode",),
                                )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VSwitch(
                                    v_model=("group_select",),
                                    label="Grow selection",
                                    hide_details=True,
                                    dense=True,
                                )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VSlider(
                                    v_model=("angle_threshold",),
                                    label="Grow angle",
                                    min=0,
                                    max=90,
                                    step=1,
                                    hide_details=True,
                                    dense=True,
                                    disabled=("!group_select",),
                                )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ selection_count }} selected")
                                vuetify.VListItemSubtitle("{{ edit_selection_mode }} mode")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                with vuetify.VRow(dense=True):
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Select All",
                                            small=True,
                                            block=True,
                                            outlined=True,
                                            click=ctrl.pv_select_all_edit_cells,
                                        )
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Clear Selection",
                                            small=True,
                                            block=True,
                                            outlined=True,
                                            click=ctrl.pv_clear_edit_preview,
                                        )
                        with vuetify.VListItem(v_show=("edit_selection_status",)):
                            with vuetify.VListItemContent():
                                vuetify.VAlert(
                                    dense=True,
                                    type=("edit_selection_status_type",),
                                    children=["{{ edit_selection_status }}"],
                                    classes="ma-0",
                                )
                        with vuetify.VListItem(v_show=("edit_selection_event",)):
                            with vuetify.VListItemContent():
                                vuetify.VTextarea(
                                    value=("edit_selection_event",),
                                    label="Last selection event",
                                    auto_grow=True,
                                    rows=3,
                                    readonly=True,
                                    outlined=True,
                                    hide_details=True,
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
                        with vuetify.VListItem(v_if="item.editable && item.type === 'BooleanProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSwitch(
                                    input_value=("item.pending_value",),
                                    label="Enabled",
                                    hide_details=True,
                                    dense=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'ProxySelectionProperty'"):
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
                        with vuetify.VListItem(v_if="item.editable && item.type === 'ArraySelectionProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    item_text="text",
                                    item_value="value",
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
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    hint="Use comma-separated values for vectors",
                                    persistent_hint=True,
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
                        with vuetify.VListItem(v_if="item.editable && item.type === 'BooleanProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSwitch(
                                    input_value=("item.pending_value",),
                                    label="Enabled",
                                    hide_details=True,
                                    dense=True,
                                    change=(ctrl.pv_update_property, "[item.scope, item.name, $event]"),
                                )
                        with vuetify.VListItem(v_if="item.editable && item.type === 'ProxySelectionProperty'"):
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
                        with vuetify.VListItem(v_if="item.editable && item.type === 'ArraySelectionProperty'"):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    item_text="text",
                                    item_value="value",
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
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    hint="Use comma-separated values for vectors",
                                    persistent_hint=True,
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

                view = _build_view_widget(backend, render_target, ctrl)
                ctrl.view_update = view.update
                if backend == "paraview":
                    ctrl.view_update_geometry = view.update_geometry
                    ctrl.view_update_image = view.update_image
                    ctrl.view_reset_camera = view.reset_camera
                    ctrl.view_set_local_rendering = view.set_local_rendering
                    ctrl.view_set_remote_rendering = view.set_remote_rendering

    return layout
