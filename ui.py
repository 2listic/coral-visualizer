from pathlib import Path
from urllib.parse import quote

from trame.ui.vuetify import SinglePageLayout
from trame.widgets import html, vuetify

from constants import REPR_SURFACE, REPR_SURFACE_EDGES, REPR_WIREFRAME, REPR_POINTS


def _load_logo_data_uri():
    logo_path = Path(__file__).with_name("assets") / "logo_no_dual.svg"
    if not logo_path.exists():
        return ""
    return f"data:image/svg+xml;utf8,{quote(logo_path.read_text(encoding='utf-8'))}"


LOGO_DATA_URI = _load_logo_data_uri()


def _build_view_widget(render_target, ctrl):
    """Create the ParaView remote/local view widget."""
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
        style=(
            "edit_view_style",
            "width: 100%; height: 100%; cursor: crosshair; outline: none;",
        ),
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
        v_show=("upload_status",),
        type=("upload_status_type",),
        dense=True,
        dismissible=True,
        v_model=("upload_status",),
        children=("{{ upload_status }}",),
        style="position: absolute; top: 68px; left: 10px; right: 10px; z-index: 999;",
    )
    vuetify.VAlert(
        v_show=("pv_runtime_message",),
        type=("pv_runtime_type",),
        dense=True,
        dismissible=True,
        v_model=("pv_runtime_message",),
        children=("{{ pv_runtime_message }}",),
        style="position: absolute; top: 126px; left: 10px; right: 10px; z-index: 998; white-space: pre-line;",
    )


def _build_toolbar(ctrl):
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
        click=ctrl.open_remote_browser,
        classes="mr-2",
    )
    vuetify.VBtn(
        "Download",
        small=True,
        outlined=True,
        disabled=("!selected_file",),
        click="window.open('/api/download?file=' + encodeURIComponent(selected_file), '_blank')",
        classes="mr-2",
    )
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
        click=(
            ctrl.pv_save_active_data,
            "[((($refs.saveFilenameField && ($refs.saveFilenameField.lazyValue || $refs.saveFilenameField.internalValue || $refs.saveFilenameField.value)) || save_filename || '').toString())]",
        ),
        disabled=("!active_pipeline_item && !edit_session_active",),
        classes="mr-2",
    )
    vuetify.VTextField(
        v_model=("save_filename",),
        ref="saveFilenameField",
        label="Output filename",
        dense=True,
        outlined=True,
        hide_details=True,
        classes="mr-2",
        style="max-width: 260px;",
    )
    with vuetify.VRow(
        v_if="is_time_dependent",
        dense=True,
        align="center",
        classes="ma-0 mr-4",
        style="max-width: 640px; flex: 1;",
    ):
        with vuetify.VBtn(
            icon=True,
            small=True,
            click=ctrl.pv_first_time_step,
        ):
            vuetify.VIcon("mdi-skip-backward")
        with vuetify.VBtn(
            icon=True,
            small=True,
            click=ctrl.pv_prev_time_step,
        ):
            vuetify.VIcon("mdi-skip-previous")
        with vuetify.VBtn(
            icon=True,
            small=True,
            click=ctrl.pv_play_pause_time,
        ):
            vuetify.VIcon("{{ time_playing ? 'mdi-pause' : 'mdi-play' }}")
        with vuetify.VBtn(
            icon=True,
            small=True,
            click=ctrl.pv_next_time_step,
        ):
            vuetify.VIcon("mdi-skip-next")
        with vuetify.VBtn(
            icon=True,
            small=True,
            click=ctrl.pv_last_time_step,
        ):
            vuetify.VIcon("mdi-skip-forward")
        with vuetify.VBtn(
            icon=True,
            small=True,
            click=ctrl.pv_toggle_time_loop,
            color=("time_loop ? 'primary' : ''",),
        ):
            vuetify.VIcon("mdi-repeat")
        html.Div(
            "{{ current_time.toFixed(4) }} ({{ time_index + 1 }}/{{ total_timesteps }})",
            classes="ml-2 grey--text text--darken-2",
            style="font-size: 0.85rem; font-family: monospace; white-space: nowrap;",
        )
        vuetify.VSlider(
            v_model=("time_index",),
            min=0,
            max=("total_timesteps - 1",),
            step=1,
            dense=True,
            hide_details=True,
            classes="ml-2 flex-grow-1",
            change="pv_set_time(time_values[$event])",
        )
    vuetify.VBtn(
        "Save And Add To Pipeline",
        small=True,
        outlined=True,
        color="primary",
        click=(
            ctrl.pv_commit_edit_session,
            "[((($refs.saveFilenameField && ($refs.saveFilenameField.lazyValue || $refs.saveFilenameField.internalValue || $refs.saveFilenameField.value)) || save_filename || '').toString())]",
        ),
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
    vuetify.VSpacer()


def _build_state_browser_dialog(ctrl):
    with vuetify.VDialog(v_model=("state_browser_dialog",), max_width="720"):
        with vuetify.VCard():
            vuetify.VCardTitle("Load State File")
            with vuetify.VCardText():
                vuetify.VTextField(
                    v_model=("state_browser_search_term",),
                    placeholder="Search state files...",
                    clearable=True,
                    dense=True,
                    outlined=True,
                    prepend_inner_icon="mdi-magnify",
                    classes="mb-2",
                    autofocus=True,
                )
                vuetify.VAlert(
                    dense=True,
                    text=True,
                    type="info",
                    children=[
                        "Browse saved state files available on the server under --data-directory."
                    ],
                )
                with vuetify.VList(
                    dense=True,
                    style="max-height: 420px; overflow-y: auto; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                ):
                    with vuetify.Template(v_for="item in filtered_state_files"):
                        with vuetify.VListItem(
                            v_if="item.value",
                            click=(ctrl.pv_load_state, "[item.value]"),
                        ):
                            with vuetify.VListItemIcon():
                                vuetify.VIcon("mdi-file-cog-outline")
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.text }}")
            with vuetify.VCardActions():
                vuetify.VSpacer()
                vuetify.VBtn(
                    "Close",
                    text=True,
                    click="state_browser_dialog = false",
                )


def _build_remote_browser_dialog(ctrl):
    with vuetify.VDialog(v_model=("remote_browser_dialog",), max_width="720"):
        with vuetify.VCard():
            vuetify.VCardTitle("Open Remote Data")
            with vuetify.VCardText():
                vuetify.VTextField(
                    v_model=("remote_search_term",),
                    placeholder="Search files...",
                    clearable=True,
                    dense=True,
                    outlined=True,
                    prepend_inner_icon="mdi-magnify",
                    classes="mb-2",
                    autofocus=True,
                )
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
                    with vuetify.Template(v_for="item in filtered_available_files"):
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


def _build_selection_tools_panel(ctrl):
    """Pick/rotate mode, selection options, grow controls, and status for edit sessions."""
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
                            click=ctrl.pv_set_pick_mode,
                        )
                    with vuetify.VCol(cols=6):
                        vuetify.VBtn(
                            "Rotate",
                            small=True,
                            block=True,
                            color=("!pick_mode ? 'primary' : ''",),
                            outlined=("pick_mode",),
                            click=ctrl.pv_set_rotate_mode,
                        )
        with vuetify.VListItem():
            with vuetify.VListItemContent():
                with vuetify.VRow(
                    dense=True,
                    no_gutters=True,
                    classes="mx-0",
                ):
                    with vuetify.VCol(cols=12, sm=6, classes="pa-1"):
                        vuetify.VBtn(
                            "Select All",
                            small=True,
                            block=True,
                            outlined=True,
                            click=ctrl.pv_select_all_edit_cells,
                        )
                    with vuetify.VCol(cols=12, sm=6, classes="pa-1"):
                        vuetify.VBtn(
                            "Clear All",
                            small=True,
                            block=True,
                            outlined=True,
                            click=ctrl.pv_clear_edit_preview,
                        )
        with vuetify.VListItem():
            with vuetify.VListItemContent():
                vuetify.VListItemTitle("{{ selection_count }} selected")
                vuetify.VListItemSubtitle("{{ edit_selection_mode }} mode")
        with vuetify.VListItem():
            with vuetify.VListItemContent():
                vuetify.VSelect(
                    v_model=("edit_geometry_mode",),
                    items=("edit_geometry_mode_options",),
                    item_text="text",
                    item_value="value",
                    label="Geometry mode",
                    dense=True,
                    outlined=True,
                    hide_details=True,
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
                with vuetify.VRow(
                    dense=True,
                    align="center",
                    no_gutters=True,
                    classes="mb-1",
                ):
                    with vuetify.VCol(cols=8):
                        vuetify.VListItemTitle("Grow angle")
                    with vuetify.VCol(cols=4, classes="text-right"):
                        vuetify.VChip(
                            "{{ angle_threshold }}°",
                            small=True,
                            outlined=True,
                            label=True,
                        )
                vuetify.VSlider(
                    v_model=("angle_threshold",),
                    label="",
                    min=0,
                    max=90,
                    step=1,
                    hide_details=True,
                    dense=True,
                    disabled=("!group_select",),
                )
        with vuetify.VListItem(v_show=("edit_selection_status",)):
            with vuetify.VListItemContent():
                vuetify.VAlert(
                    dense=True,
                    type=("edit_selection_status_type",),
                    children=["{{ edit_selection_status }}"],
                    classes="ma-0",
                )
        with vuetify.VListItem(v_show=("selection_timing_last",)):
            with vuetify.VListItemContent():
                vuetify.VListItemSubtitle("Last selection timing")
                vuetify.VListItemTitle(
                    "{{ selection_timing_last }}",
                    style="font-family: monospace; white-space: normal; font-size: 0.78rem;",
                )


def _build_edit_assign_panel(ctrl):
    """Field selection and value assignment controls for the active edit session."""
    vuetify.VSubheader(classes="px-0", children=["Field Assignment"])
    with vuetify.VList(
        dense=True,
        two_line=True,
        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
        classes="mb-2",
    ):
        with vuetify.VListItem():
            with vuetify.VListItemContent():
                vuetify.VSelect(
                    v_model=("edit_field_choice",),
                    items=("edit_field_options",),
                    item_text="text",
                    item_value="value",
                    label="Select field",
                    dense=True,
                    outlined=True,
                    hide_details=True,
                    classes="mb-2",
                    change=(ctrl.pv_on_edit_field_choice, "[$event]"),
                )
                vuetify.VTextField(
                    v_model=("edit_expression",),
                    label="Value / Calculator",
                    dense=True,
                    outlined=True,
                    hide_details=True,
                    hint="Use a scalar expression like 1, A, or A*2",
                    persistent_hint=True,
                    classes="mb-2",
                )
        with vuetify.VListItem():
            with vuetify.VListItemContent():
                vuetify.VListItemSubtitle("Available cell variables")
                vuetify.VAlert(
                    v_if="edit_available_variables.length === 0",
                    type="info",
                    dense=True,
                    text=True,
                    children=[
                        "No cell-data variables are available on the edit-session dataset."
                    ],
                )
                with vuetify.VChipGroup(
                    column=True,
                    v_if="edit_available_variables.length > 0",
                ):
                    with vuetify.Template(v_for="item in edit_available_variables"):
                        vuetify.VChip(
                            "{{ item }}",
                            x_small=True,
                            classes="ma-1",
                        )
        with vuetify.VListItem():
            with vuetify.VListItemContent():
                vuetify.VListItemSubtitle("Vector component syntax")
                vuetify.VListItemTitle("{{ edit_vector_syntax }}")
    vuetify.VBtn(
        "Assign to Selected",
        small=True,
        block=True,
        color="primary",
        outlined=True,
        click=ctrl.pv_apply_edit_field,
        classes="mb-2",
    )
    with vuetify.VDialog(
        v_model=("edit_create_field_dialog",),
        max_width="560",
    ):
        with vuetify.VCard():
            vuetify.VCardTitle("Create New Field")
            with vuetify.VCardText():
                vuetify.VSelect(
                    v_model=("edit_new_field_association",),
                    items=("edit_new_field_association_options",),
                    item_text="text",
                    item_value="value",
                    label="Array type",
                    dense=True,
                    outlined=True,
                    hide_details=True,
                    classes="mb-2",
                )
                vuetify.VTextField(
                    v_model=("edit_new_field_name",),
                    label="Field name",
                    dense=True,
                    outlined=True,
                    hide_details=True,
                    classes="mb-2",
                )
                vuetify.VTextField(
                    v_model=("edit_new_field_default_value",),
                    label="Default value",
                    dense=True,
                    outlined=True,
                    hide_details=True,
                    classes="mb-2",
                )
            with vuetify.VCardActions():
                vuetify.VSpacer()
                vuetify.VBtn(
                    "Cancel",
                    text=True,
                    click=ctrl.pv_cancel_create_edit_field,
                )
                vuetify.VBtn(
                    "Create",
                    color="primary",
                    text=True,
                    click=ctrl.pv_create_edit_field,
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
        classes="mb-4",
    )


def _build_paraview_pipeline_panel(ctrl):
    with vuetify.VNavigationDrawer(
        app=True,
        clipped=False,
        permanent=True,
        width=280,
        style="border-right: 1px solid rgba(0,0,0,0.08);",
    ):
        with vuetify.VSheet(
            classes="px-4 pb-4 pt-0",
            style="height: 100%; background: #f5f5f7; overflow-y: auto;",
        ):
            if LOGO_DATA_URI:
                with vuetify.VSheet(
                    color="#f5f5f7",
                    classes="mb-2",
                    style="position: sticky; top: 0; z-index: 5; padding-top: 8px; padding-bottom: 4px;",
                ):
                    with vuetify.VRow(
                        no_gutters=True,
                        align="center",
                        style="min-height: 64px;",
                    ):
                        with vuetify.VCol(cols="auto"):
                            html.Img(
                                src=LOGO_DATA_URI,
                                alt="Company logo",
                                style="height: 48px; width: auto; display: block; margin-right: 10px;",
                            )
                        with vuetify.VCol():
                            html.Div(
                                "VTK Manipulator",
                                style="font-size: 1.1rem; font-weight: 600; letter-spacing: 0.02em; color: rgba(0,0,0,0.82); line-height: 1;",
                            )
            with vuetify.VRow(
                no_gutters=True,
                align="center",
                classes="mb-1",
            ):
                with vuetify.VCol():
                    vuetify.VSubheader(classes="px-0", children=["Pipeline Browser"])
                with vuetify.VCol(cols="auto"):
                    with vuetify.VTooltip(bottom=True):
                        with vuetify.Template(v_slot_activator="{ on, attrs }"):
                            with vuetify.VBtn(
                                icon=True,
                                small=True,
                                disabled=("!active_pipeline_item",),
                                click=ctrl.pv_reload_active_file,
                                v_bind="attrs",
                                v_on="on",
                            ):
                                vuetify.VIcon("mdi-refresh", small=True)
                        html.Span("Reload selected pipeline file")
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
                            style=(
                                "item.depth ? 'margin-left: ' + (item.depth * 16) + 'px;' : ''",
                            ),
                        ):
                            with vuetify.VListItemIcon():
                                vuetify.VIcon(
                                    "{{ item.node_icon || 'mdi-database-outline' }}"
                                )
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.text }}")
                            with vuetify.VListItemAction():
                                with vuetify.VBtn(
                                    icon=True,
                                    small=True,
                                    click=(
                                        ctrl.pv_toggle_visibility_for,
                                        "[item.value]",
                                    ),
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
                        vuetify.VListItemTitle(
                            "{{ active_source_label || 'No source loaded' }}"
                        )
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
                                    children=[
                                        "{{ active_visibility ? 'Hide' : 'Show' }}"
                                    ],
                                    disabled=("!active_pipeline_item",),
                                    classes="mb-2",
                                )
                            with vuetify.VCol(cols=12):
                                with vuetify.VMenu(
                                    v_model=("filter_menu",),
                                    close_on_content_click=False,
                                    offset_y=True,
                                ):
                                    with vuetify.Template(
                                        v_slot_activator="{ on, attrs }"
                                    ):
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
                                                    click=(
                                                        ctrl.pv_add_filter,
                                                        "[item.value]",
                                                    )
                                                ):
                                                    with vuetify.VListItemIcon():
                                                        vuetify.VIcon("{{ item.icon }}")
                                                    with vuetify.VListItemContent():
                                                        vuetify.VListItemTitle(
                                                            "{{ item.text }}"
                                                        )
                                            vuetify.VDivider(
                                                v_if="show_experimental_filters && filter_supported_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase())).length && filter_experimental_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase())).length"
                                            )
                                            vuetify.VSubheader(
                                                v_if="show_experimental_filters && filter_experimental_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase())).length",
                                                children=["Experimental"],
                                            )
                                            with vuetify.Template(
                                                v_for="item in filter_experimental_options.filter((entry) => !filter_search || entry.text.toLowerCase().includes(filter_search.toLowerCase()))",
                                                v_if="show_experimental_filters",
                                            ):
                                                with vuetify.VListItem(
                                                    click=(
                                                        ctrl.pv_add_filter,
                                                        "[item.value]",
                                                    )
                                                ):
                                                    with vuetify.VListItemIcon():
                                                        vuetify.VIcon("{{ item.icon }}")
                                                    with vuetify.VListItemContent():
                                                        vuetify.VListItemTitle(
                                                            "{{ item.text }}"
                                                        )
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
                with vuetify.VListItem(v_show=("save_status",)):
                    with vuetify.VListItemContent():
                        vuetify.VAlert(
                            type=("save_status_type",),
                            dense=True,
                            children=["{{ save_status }}"],
                            classes="ma-0",
                        )

            vuetify.VDivider(classes="my-4")
            vuetify.VSubheader(classes="px-0", children=["State"])
            with vuetify.VSheet(
                classes="pa-3",
                style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
            ):
                html.Input(
                    ref="stateFilePicker",
                    type="file",
                    accept=".json",
                    style="display: none;",
                    change=(ctrl.upload_state_file, "[$event.target.files]"),
                    __events=["change"],
                )
                vuetify.VCombobox(
                    v_model=("state_filename",),
                    items=("state_files",),
                    label="State file",
                    dense=True,
                    outlined=True,
                    clearable=True,
                    hide_details=True,
                    classes="mb-3",
                )
                with vuetify.VRow(dense=True):
                    with vuetify.VCol(cols=12):
                        vuetify.VBtn(
                            "Save State",
                            small=True,
                            block=True,
                            outlined=True,
                            click=ctrl.pv_save_state,
                            disabled=("!pipeline_items.length || !state_filename",),
                            classes="mb-2",
                        )
                    with vuetify.VCol(cols=12):
                        vuetify.VBtn(
                            "Load State",
                            small=True,
                            block=True,
                            outlined=True,
                            click=ctrl.open_remote_state_browser,
                            classes="mb-2",
                        )
                    with vuetify.VCol(cols=12):
                        vuetify.VBtn(
                            "Upload State File",
                            small=True,
                            block=True,
                            outlined=True,
                            click="$refs.stateFilePicker.value = null; $refs.stateFilePicker.click()",
                            classes="mb-2",
                        )
                    with vuetify.VCol(cols=12):
                        vuetify.VBtn(
                            "Download State",
                            small=True,
                            block=True,
                            outlined=True,
                            disabled=("!state_filename",),
                            click="window.open('/api/download?file=' + encodeURIComponent(state_filename), '_blank')",
                        )
                vuetify.VAlert(
                    v_if="state_status",
                    type=("state_status_type",),
                    dense=True,
                    text=True,
                    classes="mt-3 mb-0",
                    children=["{{ state_status }}"],
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
        clipped=False,
        right=True,
        permanent=True,
        width=340,
        style="border-left: 1px solid rgba(0,0,0,0.08);",
    ):
        with vuetify.VSheet(
            style="background: #fafafa; min-height: 100%; display: flex; flex-direction: column;"
        ):
            with vuetify.VSheet(
                style="position: sticky; top: 0; z-index: 6; background: #fafafa; flex: 0 0 auto;"
            ):
                _build_property_action_bar(ctrl)
                _build_inspector_tab_selector()
            with vuetify.VSheet(
                style="flex: 1 1 auto; overflow-y: auto; background: #fafafa;"
            ):
                with vuetify.VContainer(
                    fluid=True, classes="pa-4", v_show="inspector_tab === 0"
                ):
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
                        items=(
                            [
                                REPR_SURFACE,
                                REPR_SURFACE_EDGES,
                                REPR_WIREFRAME,
                                REPR_POINTS,
                            ],
                        ),
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
                    with vuetify.VList(
                        dense=True,
                        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                        classes="mb-4",
                    ):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VCheckbox(
                                    v_model=("show_cells",),
                                    label="Show cells",
                                    dense=True,
                                    hide_details=True,
                                    classes="mt-0",
                                    change=(
                                        ctrl.pv_set_cell_face_visibility,
                                        "[show_cells, show_faces]",
                                    ),
                                )
                                vuetify.VCheckbox(
                                    v_model=("show_faces",),
                                    label="Show faces",
                                    dense=True,
                                    hide_details=True,
                                    classes="mt-0",
                                    change=(
                                        ctrl.pv_set_cell_face_visibility,
                                        "[show_cells, show_faces]",
                                    ),
                                )
                    vuetify.VDivider(classes="my-4")
                    vuetify.VSubheader(
                        classes="px-0", children=["Advanced Display Controls"]
                    )
                    vuetify.VSubheader(classes="px-0", children=["Color Bar"])
                    with vuetify.VList(
                        dense=True,
                        two_line=True,
                        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                        classes="mb-4",
                    ):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    v_model=("color_map_preset",),
                                    items=("color_map_preset_options",),
                                    item_text="text",
                                    item_value="value",
                                    label="Color map",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    disabled=("!color_controls_enabled",),
                                    change=(ctrl.pv_apply_color_map_preset, "[$event]"),
                                )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                with vuetify.VRow(dense=True):
                                    with vuetify.VCol(cols=6):
                                        vuetify.VTextField(
                                            v_model=("color_range_min",),
                                            label="Min",
                                            dense=True,
                                            outlined=True,
                                            hide_details=True,
                                            disabled=("!color_controls_enabled",),
                                        )
                                    with vuetify.VCol(cols=6):
                                        vuetify.VTextField(
                                            v_model=("color_range_max",),
                                            label="Max",
                                            dense=True,
                                            outlined=True,
                                            hide_details=True,
                                            disabled=("!color_controls_enabled",),
                                        )
                                with vuetify.VRow(dense=True, classes="mt-1"):
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Apply Range",
                                            small=True,
                                            block=True,
                                            outlined=True,
                                            disabled=("!color_controls_enabled",),
                                            click=ctrl.pv_apply_color_range,
                                        )
                                    with vuetify.VCol(cols=6):
                                        vuetify.VBtn(
                                            "Rescale Data",
                                            small=True,
                                            block=True,
                                            outlined=True,
                                            disabled=("!color_controls_enabled",),
                                            click=ctrl.pv_rescale_color_range_to_data,
                                        )
                                with vuetify.VRow(
                                    dense=True, classes="mt-1", v_if="is_time_dependent"
                                ):
                                    with vuetify.VCol(cols=12):
                                        vuetify.VBtn(
                                            "Rescale over Time",
                                            small=True,
                                            block=True,
                                            outlined=True,
                                            color="warning",
                                            disabled=("!color_controls_enabled",),
                                            click="rescale_over_time_dialog = true",
                                        )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VSwitch(
                                    v_model=("color_bar_visible",),
                                    label="Show color scale",
                                    dense=True,
                                    hide_details=True,
                                    disabled=("!color_controls_enabled",),
                                    change=(ctrl.pv_set_scalar_bar_visible, "[$event]"),
                                )
                                vuetify.VSwitch(
                                    v_model=("orientation_axes_visible",),
                                    label="Show orientation axes",
                                    dense=True,
                                    hide_details=True,
                                    change=(
                                        ctrl.pv_set_orientation_axes_visible,
                                        "[$event]",
                                    ),
                                )
                                vuetify.VSwitch(
                                    v_model=("categorical_coloring",),
                                    label="Interpret values as categories",
                                    dense=True,
                                    hide_details=True,
                                    disabled=("!color_controls_enabled",),
                                    change=(
                                        ctrl.pv_set_categorical_coloring,
                                        "[$event]",
                                    ),
                                )
                        with vuetify.VListItem(v_show=("color_controls_status",)):
                            with vuetify.VListItemContent():
                                vuetify.VAlert(
                                    type=("color_controls_status_type",),
                                    dense=True,
                                    text=True,
                                    classes="ma-0",
                                    children=["{{ color_controls_status }}"],
                                )
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

                with vuetify.VContainer(
                    fluid=True, classes="pa-4", v_show="inspector_tab === 1"
                ):
                    vuetify.VSubheader(classes="px-0", children=["Properties"])
                    with vuetify.VList(
                        dense=True,
                        two_line=True,
                        style="background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;",
                        classes="mb-4",
                    ):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle(
                                    "{{ active_source_label || 'No source selected' }}"
                                )
                                vuetify.VListItemSubtitle("Active source")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle(
                                    "{{ active_source_type || 'N/A' }}"
                                )
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
                                vuetify.VListItemTitle(
                                    "{{ calculator_attribute_type || 'Point Data' }}"
                                )
                                vuetify.VListItemSubtitle("Calculator association")
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("Coordinate variables")
                                with vuetify.VChipGroup(column=True):
                                    with vuetify.Template(
                                        v_for="item in calculator_coordinate_variables"
                                    ):
                                        vuetify.VChip(
                                            "{{ item }}", x_small=True, classes="ma-1"
                                        )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("Vector component syntax")
                                vuetify.VListItemTitle(
                                    "Use arrayName[0], arrayName[1], arrayName[2]"
                                )
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("Input array variables")
                                vuetify.VAlert(
                                    v_if="calculator_input_variables.length === 0",
                                    type="info",
                                    dense=True,
                                    text=True,
                                    children=[
                                        "No arrays available for the current Calculator association."
                                    ],
                                )
                                with vuetify.VChipGroup(
                                    column=True,
                                    v_if="calculator_input_variables.length > 0",
                                ):
                                    with vuetify.Template(
                                        v_for="item in calculator_input_variables"
                                    ):
                                        vuetify.VChip(
                                            "{{ item }}", x_small=True, classes="ma-1"
                                        )
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

                with vuetify.VContainer(
                    fluid=True, classes="pa-4", v_show="inspector_tab === 2"
                ):
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

                with vuetify.VContainer(
                    fluid=True,
                    classes="pa-4",
                    v_show="edit_session_active && inspector_tab === 3",
                ):
                    _build_selection_tools_panel(ctrl)
                    vuetify.VDivider(classes="my-4")
                    _build_edit_assign_panel(ctrl)


def _build_property_list(ctrl, state_key):
    with vuetify.VExpansionPanels(
        accordion=True, flat=True, style="background: transparent;"
    ):
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
                    with vuetify.Template(
                        v_for=f"item in {state_key}.filter((entry) => entry.visibility === 'default')"
                    ):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.label }}")
                                vuetify.VListItemSubtitle("{{ item.type }}")
                            with vuetify.VListItemAction(v_if="item.type"):
                                vuetify.VChip(
                                    "{{ item.type }}", x_small=True, label=True
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'StringListProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'BooleanProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSwitch(
                                    input_value=("item.pending_value",),
                                    label="Enabled",
                                    hide_details=True,
                                    dense=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'ProxySelectionProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'EnumerationProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'ArraySelectionProperty'"
                        ):
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
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'ArrayListProperty'"
                        ):
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
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'VectorProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VTextField(
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    hint="Use comma-separated values for vectors",
                                    persistent_hint=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
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
                    with vuetify.Template(
                        v_for=f"item in {state_key}.filter((entry) => entry.visibility === 'advanced')"
                    ):
                        with vuetify.VListItem():
                            with vuetify.VListItemContent():
                                vuetify.VListItemTitle("{{ item.label }}")
                                vuetify.VListItemSubtitle("{{ item.type }}")
                            with vuetify.VListItemAction(v_if="item.type"):
                                vuetify.VChip(
                                    "{{ item.type }}", x_small=True, label=True
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'StringListProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'BooleanProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSwitch(
                                    input_value=("item.pending_value",),
                                    label="Enabled",
                                    hide_details=True,
                                    dense=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'ProxySelectionProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'EnumerationProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VSelect(
                                    items=("item.options",),
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'ArraySelectionProperty'"
                        ):
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
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'ArrayListProperty'"
                        ):
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
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(
                            v_if="item.editable && item.type === 'VectorProperty'"
                        ):
                            with vuetify.VListItemContent():
                                vuetify.VTextField(
                                    value=("item.pending_value",),
                                    label="Value",
                                    dense=True,
                                    outlined=True,
                                    hide_details=True,
                                    hint="Use comma-separated values for vectors",
                                    persistent_hint=True,
                                    change=(
                                        ctrl.pv_update_property,
                                        "[item.scope, item.name, $event]",
                                    ),
                                )
                        with vuetify.VListItem(v_if="!item.editable"):
                            with vuetify.VListItemContent():
                                vuetify.VListItemSubtitle("{{ item.value || ' ' }}")


def build_ui(server, render_target):
    """Build the Trame UI layout."""
    ctrl = server.controller
    server.state.trame__title = "Coral VTK Manipulator"
    if LOGO_DATA_URI:
        server.state.trame__favicon = LOGO_DATA_URI

    with SinglePageLayout(server) as layout:
        layout.title.set_text("Coral VTK Manipulator")
        layout.title.hide()
        layout.icon.hide()
        html.Script("document.title = 'Coral VTK Manipulator';")

        # Rescale over time confirmation dialog
        with vuetify.VDialog(v_model=("rescale_over_time_dialog",), max_width=450):
            with vuetify.VCard():
                vuetify.VCardTitle("Rescale Range over Time", classes="headline")
                with vuetify.VCardText():
                    html.Div(
                        "Rescaling the color range over all timesteps may take a significant amount of time as ParaView must process every frame of the simulation.",
                        classes="mb-4",
                    )
                    html.Div("Do you want to proceed?")
                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn(
                        "Cancel", click="rescale_over_time_dialog = false", text=True
                    )
                    vuetify.VBtn(
                        "Rescale",
                        click=ctrl.pv_rescale_color_range_over_time,
                        color="warning",
                        text=True,
                    )

        with vuetify.VDialog(v_model=("save_overwrite_dialog",), max_width=560):
            with vuetify.VCard():
                vuetify.VCardTitle("Overwrite Existing File?")
                with vuetify.VCardText():
                    vuetify.VAlert(
                        type="warning",
                        dense=True,
                        outlined=True,
                        children=[
                            "{{ save_overwrite_action === 'state_save' ? ('The state file ' + save_overwrite_target + ' already exists. Overwrite it with the current application state?') : ('The file ' + save_overwrite_target + ' already exists. Overwrite it with the newly saved result?') }}"
                        ],
                    )
                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn(
                        "Cancel", click=ctrl.pv_cancel_save_overwrite, text=True
                    )
                    vuetify.VBtn(
                        "Overwrite",
                        click=ctrl.pv_confirm_save_overwrite,
                        color="warning",
                        text=True,
                    )

        with layout.toolbar:
            _build_toolbar(ctrl)

        with layout.content:
            with vuetify.VContainer(
                fluid=True,
                classes="pa-0 fill-height",
                style="position: relative; max-width: none;",
            ):
                # Busy indicator
                with vuetify.VCard(
                    v_show=("trame__busy",),
                    style="position: absolute; top: 20px; right: 20px; z-index: 1001; background: rgba(255,255,255,0.8); border-radius: 50%; padding: 8px;",
                    flat=True,
                ):
                    with vuetify.VProgressCircular(
                        indeterminate=True,
                        color="primary",
                        size=64,
                        width=4,
                    ):
                        if LOGO_DATA_URI:
                            html.Img(
                                src=LOGO_DATA_URI,
                                style="height: 40px; width: 40px;",
                            )
                _build_alerts()
                _build_remote_browser_dialog(ctrl)
                _build_state_browser_dialog(ctrl)
                _build_paraview_pipeline_panel(ctrl)
                _build_paraview_inspector_panel(ctrl)

                view = _build_view_widget(render_target, ctrl)
                ctrl.view_update = view.update
                ctrl.view_update_geometry = view.update_geometry
                ctrl.view_update_image = view.update_image
                ctrl.view_reset_camera = view.reset_camera
                ctrl.view_set_local_rendering = view.set_local_rendering
                ctrl.view_set_remote_rendering = view.set_remote_rendering

    return layout
