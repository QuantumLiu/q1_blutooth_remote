from dataclasses import dataclass
import time

A_KEY = 353
B_KEY = 158
GROUND_ACTIONS = {
    "PASSIVE_DEFAULT",
    "LYING_DEFAULT",
    "LIE_FACE_UP",
    "LIE_FACE_DOWN",
    "BIPED_GROUND_POSE",
}
STANDING_ACTIONS = {
    "BIPED_WALK_RUN",
    "BIPED_WALK_RUN_DEFAULT",
    "BIPED_STAND_DEFAULT",
    "BIPED_WHOLE_BODY_CTRL",
}


@dataclass(frozen=True)
class ActionPrompt:
    action: str
    text: str


class LongPressActionState:
    def __init__(
        self,
        hold_seconds=5.0,
        confirmation_timeout=15.0,
        combo_window=0.1,
        action_keys=(A_KEY, B_KEY),
        key_labels=("A", "B"),
    ):
        self.hold_seconds = hold_seconds
        self.confirmation_timeout = confirmation_timeout
        self.combo_window = combo_window
        self.action_keys = frozenset(action_keys)
        self.key_labels = tuple(key_labels)
        self.last_pressed = {}
        self.last_released = {}
        self.combo_active = False
        self.combo_started = None
        self.combo_released = set()
        self.combo_handled = False
        self.prompt = None
        self.waiting_for_release = False
        self.released_keys = set()
        self.confirmation_pressed = set()
        self.confirmation_deadline = None

    @property
    def pending(self):
        return self.prompt is not None

    def reset(self):
        self.last_pressed.clear()
        self.last_released.clear()
        self.combo_active = False
        self.combo_started = None
        self.combo_released.clear()
        self.combo_handled = False
        self.prompt = None
        self.waiting_for_release = False
        self.released_keys.clear()
        self.confirmation_pressed.clear()
        self.confirmation_deadline = None

    def handle_event(self, code, value, now=None):
        now = time.monotonic() if now is None else now
        if self.pending:
            if code not in self.action_keys:
                return None
            if value == 0:
                self.released_keys.add(code)
                if self.released_keys == self.action_keys:
                    self.waiting_for_release = False
                return None
            if self.waiting_for_release:
                return None
            self.confirmation_pressed.add(code)
            if self.confirmation_pressed != self.action_keys:
                return None
            action = self.prompt.action
            self.reset()
            return action

        if code not in self.action_keys:
            return None
        if value != 0:
            self.last_pressed[code] = now
        else:
            self.last_released[code] = now

        if not self.combo_active:
            if not self.action_keys.issubset(self.last_pressed):
                return None
            first_press = min(self.last_pressed[key] for key in self.action_keys)
            second_press = max(self.last_pressed[key] for key in self.action_keys)
            if second_press - first_press > self.combo_window:
                return None
            self.combo_active = True
            self.combo_started = second_press
            self.combo_released = {
                key
                for key in self.action_keys
                if self.last_released.get(key, float("-inf")) >= first_press
            }
            return None

        if value == 0:
            self.combo_released.add(code)
            if self.combo_released == self.action_keys:
                self.reset()
        return None

    def check_prompt(self, current_action, now=None):
        now = time.monotonic() if now is None else now
        if self.pending or not self.combo_active or self.combo_handled:
            return None
        if now - self.combo_started < self.hold_seconds:
            return None
        self.combo_handled = True

        labels = " + ".join(self.key_labels)
        if current_action in GROUND_ACTIONS:
            prompt = ActionPrompt(
                "STAND_UP",
                f"是否执行站起？请松开 {labels}，再同时按 {labels} 确认。",
            )
        elif current_action in STANDING_ACTIONS:
            prompt = ActionPrompt(
                "LIE_FACE_DOWN",
                f"是否执行趴下？请松开 {labels}，再同时按 {labels} 确认。",
            )
        else:
            return None

        self.prompt = prompt
        self.waiting_for_release = True
        self.released_keys = set(self.combo_released)
        self.confirmation_pressed.clear()
        self.confirmation_deadline = now + self.confirmation_timeout
        return prompt

    def expire_confirmation(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.pending or now < self.confirmation_deadline:
            return False
        self.reset()
        return True


class PressHoldActionState:
    def __init__(
        self,
        hold_seconds=2.0,
        confirmation_timeout=15.0,
        action_keys=(311,),
        key_labels=("O",),
        short_press_max=0.8,
        sequence_timeout=1.5,
    ):
        self.hold_seconds = hold_seconds
        self.confirmation_timeout = confirmation_timeout
        self.key = action_keys[0]
        self.label = key_labels[0]
        self.short_press_max = short_press_max
        self.sequence_timeout = sequence_timeout
        self.stage = "idle"
        self.press_started = None
        self.sequence_deadline = None
        self.prompt = None
        self.waiting_for_release = False
        self.confirmation_deadline = None

    @property
    def pending(self):
        return self.prompt is not None

    @property
    def combo_active(self):
        return self.stage != "idle"

    def reset(self):
        self.stage = "idle"
        self.press_started = None
        self.sequence_deadline = None
        self.prompt = None
        self.waiting_for_release = False
        self.confirmation_deadline = None

    def handle_event(self, code, value, now=None):
        now = time.monotonic() if now is None else now
        if code != self.key:
            return None
        if self.pending:
            if value == 0:
                self.waiting_for_release = False
                return None
            if self.waiting_for_release:
                return None
            action = self.prompt.action
            self.reset()
            return action

        if value != 0:
            if self.stage == "await_long" and now > self.sequence_deadline:
                self.reset()
            self.press_started = now
            if self.stage == "await_long":
                self.stage = "holding"
            else:
                self.stage = "first_press"
            return None

        if self.stage == "holding":
            self.reset()
            return None
        if self.stage == "first_press" and self.press_started is not None:
            if now - self.press_started <= self.short_press_max:
                self.stage = "await_long"
                self.sequence_deadline = now + self.sequence_timeout
            else:
                self.reset()
        return None

    def check_prompt(self, current_action, now=None):
        now = time.monotonic() if now is None else now
        if self.pending:
            return None
        if self.stage == "await_long" and now > self.sequence_deadline:
            self.reset()
            return None
        if self.stage != "holding" or self.press_started is None:
            return None
        if now - self.press_started < self.hold_seconds:
            return None

        if current_action in GROUND_ACTIONS:
            action = "STAND_UP"
            name = "站起"
        elif current_action in STANDING_ACTIONS:
            action = "LIE_FACE_DOWN"
            name = "趴下"
        else:
            self.reset()
            return None

        self.prompt = ActionPrompt(
            action,
            f"是否执行{name}？请松开 {self.label}，再短按 {self.label} 确认。",
        )
        self.stage = "prompt"
        self.waiting_for_release = True
        self.confirmation_deadline = now + self.confirmation_timeout
        return self.prompt

    def expire_confirmation(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.pending or now < self.confirmation_deadline:
            return False
        self.reset()
        return True
