"""Standalone menu frontend for the simulator."""
from ursina import *
from ursina.shaders import unlit_shader


RETURN_TARGET_PRESETS = {
    "clear": {
        "Center deep (x=0.00, y=-6.50)": {"x": 0.0, "y": -6.5},
        "Center deep safe (x=0.00, y=-6.35)": {"x": 0.0, "y": -6.35},
        "Left deep (x=-2.35, y=-6.50)": {"x": -2.35, "y": -6.5},
        "Right deep (x=2.35, y=-6.50)": {"x": 2.35, "y": -6.5},
        "Left back line (x=-2.35, y=-6.55)": {"x": -2.35, "y": -6.55},
        "Right back line (x=2.35, y=-6.55)": {"x": 2.35, "y": -6.55},
    },
    "drive": {
        "Center deep drive (x=0.00, y=-6.50)": {"x": 0.0, "y": -6.5},
        "Left drive (x=-2.35, y=-5.80)": {"x": -2.35, "y": -5.8},
        "Right drive (x=2.35, y=-5.80)": {"x": 2.35, "y": -5.8},
    },
    "lift": {
        "Left deep lift (x=-2.35, y=-6.50)": {"x": -2.35, "y": -6.5},
        "Right deep lift (x=2.35, y=-6.50)": {"x": 2.35, "y": -6.5},
    },
    "drop": {
        "Left front drop (x=-2.35, y=-1.00)": {"x": -2.35, "y": -1.0},
        "Right front drop (x=2.35, y=-1.00)": {"x": 2.35, "y": -1.0},
    },
    "block": {
        "Left block (x=-2.35, y=-3.30)": {"x": -2.35, "y": -3.3},
        "Right block (x=2.35, y=-3.30)": {"x": 2.35, "y": -3.3},
    },
    "net_soft": {
        "Left soft net (x=-2.20, y=-1.60)": {"x": -2.2, "y": -1.6},
        "Right soft net (x=2.20, y=-1.60)": {"x": 2.2, "y": -1.6},
    },
    "smash": {
        "Left deep smash (x=-2.35, y=-6.50)": {"x": -2.35, "y": -6.5},
        "Right deep smash (x=2.35, y=-6.50)": {"x": 2.35, "y": -6.5},
    },
}

RETURN_PROFILES = ("clear", "drive", "lift", "drop", "block", "net_soft", "smash")


class MenuFrontend:
    """Esc-opened full screen menu editor/queue UI.

    The class is presentation-only. Main program code owns callbacks and state.
    """

    def __init__(self):
        self.callbacks = {}
        self.dynamic_entities = []
        self.open_dropdown = None
        self.is_open = False

        self.root = self._ui_entity(parent=camera.ui, enabled=False, always_on_top=True)

        self._text(
            parent=self.root,
            text="Menu Frontend",
            position=(-0.78, 0.43),
            origin=(-0.5, 0),
            scale=1.25,
            color=color.azure,
        )
        self._text(
            parent=self.root,
            text="Press Esc to return to simulator",
            position=(0.40, 0.44),
            origin=(-0.5, 0),
            scale=0.65,
            color=color.light_gray,
        )

        self.status_text = self._text(
            parent=self.root,
            text="",
            position=(-0.78, -0.44),
            origin=(-0.5, 0),
            scale=0.62,
            color=color.light_gray,
        )
        self.selected_text = self._text(
            parent=self.root,
            text="Selected: none",
            position=(-0.78, 0.22),
            origin=(-0.5, 0),
            scale=0.68,
            color=color.white,
        )
        self.menu_list_text = self._text(
            parent=self.root,
            text="Menus: none",
            position=(0.25, -0.04),
            origin=(-0.5, 0),
            scale=0.54,
            color=color.light_gray,
        )
        self.queue_text = self._text(
            parent=self.root,
            text="Queue: empty",
            position=(0.25, 0.22),
            origin=(-0.5, 0),
            scale=0.66,
            color=color.white,
        )
        self.policy_text = self._text(
            parent=self.root,
            text="Return policy: none",
            position=(-0.78, -0.10),
            origin=(-0.5, 0),
            scale=0.66,
            color=color.white,
        )

        self.queue_button = self._button("Queue", (-0.77, 0.09), "enqueue")
        self.delete_button = self._button("Delete", (-0.55, 0.09), "delete", button_color=color.rgb(232, 115, 115))
        self.run_button = self._button("Run Next", (-0.33, 0.09), "run_next", button_color=color.rgb(104, 195, 139))
        self.clear_button = self._button("Clear Queue", (0.25, 0.09), "clear_queue")
        self.returns_button = self._button("Returns", (0.49, 0.09), "toggle_returns")
        self.reload_button = self._button("Reload", (0.70, 0.09), "reload")
        self.close_button = self._button("Back", (0.72, -0.42), "close")

    def _ui_entity(self, **kwargs):
        entity = Entity(shader=unlit_shader, **kwargs)
        self._force_ui_rendering(entity)
        return entity

    def _text(self, **kwargs):
        text = Text(**kwargs)
        self._force_ui_rendering(text)
        return text

    def _force_ui_rendering(self, entity, render_queue=110):
        entity.unlit = True
        entity.always_on_top = True
        entity.render_queue = render_queue
        if getattr(entity, "text_entity", None):
            self._force_ui_rendering(entity.text_entity, render_queue + 1)
        return entity

    def _button(self, text, position, action, button_color=color.rgb(35, 42, 52)):
        button = Button(
            parent=self.root,
            text=text,
            position=position,
            z=0.0,
            scale=(0.19, 0.045),
            color=button_color,
            text_color=color.black,
            text_size=0.72,
            highlight_scale=1,
            pressed_scale=0.98,
            on_click=Func(self._fire, action),
        )
        button.highlight_color = color.rgb(96, 163, 230)
        button.pressed_color = color.rgb(54, 111, 176)
        return self._force_ui_rendering(button, render_queue=120)

    def _dropdown(self, text, options, position, width=0.42):
        dropdown_id = f"dropdown-{len(self.dynamic_entities)}"
        header = Button(
            parent=self.root,
            text=text,
            position=position,
            z=0.0,
            scale=(width, 0.045),
            color=color.rgb(64, 135, 210),
            text_color=color.black,
            text_size=0.66,
            highlight_scale=1,
            pressed_scale=0.98,
            on_click=Func(self._toggle_dropdown, dropdown_id),
        )
        header.highlight_color = color.rgb(104, 172, 235)
        header.pressed_color = color.rgb(48, 105, 170)
        self._force_ui_rendering(header, render_queue=130)
        self.dynamic_entities.append(header)

        for index, option in enumerate(options):
            label = option["label"]
            if len(label) > 46:
                label = f"{label[:43]}..."
            button = Button(
                parent=self.root,
                text=label,
                position=(position[0], position[1] - ((index + 1) * 0.048), -0.01),
                scale=(width, 0.043),
                color=color.rgb(226, 232, 240),
                text_color=color.black,
                text_size=0.54,
                highlight_scale=1,
                pressed_scale=0.98,
                enabled=False,
                on_click=Func(self._choose_dropdown_option, dropdown_id, option["action"], option["value"]),
            )
            button.highlight_color = color.rgb(194, 215, 238)
            button.pressed_color = color.rgb(162, 194, 228)
            button.dropdown_id = dropdown_id
            self._force_ui_rendering(button, render_queue=145 + index)
            self.dynamic_entities.append(button)

        return header

    def _toggle_dropdown(self, dropdown_id):
        next_open = None if self.open_dropdown == dropdown_id else dropdown_id
        self.open_dropdown = next_open
        for entity in self.dynamic_entities:
            if getattr(entity, "dropdown_id", None):
                entity.enabled = entity.dropdown_id == self.open_dropdown

    def _choose_dropdown_option(self, dropdown_id, action, value):
        self.open_dropdown = None
        for entity in self.dynamic_entities:
            if getattr(entity, "dropdown_id", None):
                entity.enabled = False
        self._fire(action, value)

    def _clear_dynamic_entities(self):
        for entity in self.dynamic_entities:
            destroy(entity)
        self.dynamic_entities.clear()
        self.open_dropdown = None

    def _fire(self, action, value=None):
        callback = self.callbacks.get(action)
        if not callback:
            return
        if value is None:
            callback()
        else:
            callback(value)

    def set_callbacks(self, callbacks):
        self.callbacks = callbacks or {}

    def open(self):
        self.is_open = True
        self.root.enabled = True

    def close(self):
        self.is_open = False
        self.root.enabled = False

    def toggle(self):
        if self.is_open:
            self.close()
        else:
            self.open()

    def update_state(self, menus, selected_menu=None, selected_scope="default",
                     queue_items=None, policy=None, target_options=None, target_label="unset",
                     returns_enabled=False, status=""):
        self._clear_dynamic_entities()
        queue_items = queue_items or []
        target_options = target_options or RETURN_TARGET_PRESETS["clear"]
        selected_menu_id = selected_menu.get("id") if selected_menu else None

        menu_buttons = []
        if menus:
            for index, menu in enumerate(menus):
                label = f"{index + 1}. {menu.get('menuName', 'Untitled')}"
                menu_buttons.append({"label": label, "action": "select_menu", "value": menu.get("id")})
        else:
            menu_buttons.append({"label": "(no menus in menus.json)", "action": "noop", "value": ""})

        menu_label = "Choose Menu"
        if selected_menu:
            menu_name = selected_menu.get("menuName", "Untitled")
            menu_label = menu_name if len(menu_name) <= 24 else f"{menu_name[:21]}..."
        self._dropdown(menu_label, menu_buttons, (-0.64, 0.32), width=0.54)

        drills = []
        if selected_menu:
            drills = ((selected_menu.get("payload") or {}).get("menu") or {}).get("drills") or []
        scope_buttons = [{"label": "Default policy", "action": "select_scope", "value": "default"}]
        for index, _drill in enumerate(drills):
            scope_buttons.append({"label": f"Drill {index + 1}", "action": "select_scope", "value": str(index)})
        scope_label = "Default policy" if selected_scope == "default" else f"Drill {int(selected_scope) + 1}"
        self._dropdown(scope_label, scope_buttons, (-0.18, 0.32), width=0.30)

        profile_buttons = [
            {"label": profile, "action": "profile", "value": profile}
            for profile in RETURN_PROFILES
        ]
        profile_label = (policy or {}).get("profile") or "Profile"
        self._dropdown(f"Profile: {profile_label}", profile_buttons, (-0.64, -0.23), width=0.34)

        target_buttons = [
            {"label": label, "action": "target", "value": label}
            for label in target_options
        ]
        self._dropdown(f"Target: {target_label}", target_buttons, (-0.18, -0.23), width=0.58)

        if selected_menu:
            menu_name = selected_menu.get("menuName", "Untitled")
            drill_count = len(drills)
            self.selected_text.text = (
                f"Selected: {menu_name}\n"
                f"ID: {selected_menu_id}\n"
                f"Drills: {drill_count}"
            )
        else:
            self.selected_text.text = "Selected: none"

        if menus:
            menu_lines = ["Menus in menus.json:"]
            for index, menu in enumerate(menus[:6]):
                name = menu.get("menuName", "Untitled")
                if len(name) > 34:
                    name = f"{name[:31]}..."
                marker = "*" if menu.get("id") == selected_menu_id else " "
                menu_lines.append(f"{marker} {index + 1}. {name}")
            if len(menus) > 6:
                menu_lines.append(f"... +{len(menus) - 6}")
            self.menu_list_text.text = "\n".join(menu_lines)
        else:
            self.menu_list_text.text = "Menus in menus.json: none"

        if queue_items:
            lines = ["Queue:"]
            for index, item in enumerate(queue_items[:8]):
                name = item.get("menuName") or item.get("id") or "unknown"
                if len(name) > 28:
                    name = f"{name[:25]}..."
                lines.append(f"{index + 1}. {name}")
            if len(queue_items) > 8:
                lines.append(f"... +{len(queue_items) - 8}")
            self.queue_text.text = "\n".join(lines)
        else:
            self.queue_text.text = "Queue: empty"

        target = (policy or {}).get("target") or {}
        if target.get("x") is not None and target.get("y") is not None:
            try:
                target_text = f"x={float(target.get('x')):.2f}, y={float(target.get('y')):.2f}"
            except (TypeError, ValueError):
                target_text = "target invalid"
        else:
            target_text = "target unset"

        scope_text = "Default" if selected_scope == "default" else f"Drill {int(selected_scope) + 1}"
        self.policy_text.text = (
            f"Editing: {scope_text}\n"
            f"Return policy: {(policy or {}).get('profile') or 'unset'} | {target_text}"
        )
        self.returns_button.text = "Returns ON" if returns_enabled else "Returns OFF"
        self.status_text.text = status or ""
