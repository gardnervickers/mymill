import linuxcnc

from qtpy.QtCore import QTimer
from qtpy.QtWidgets import QFormLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


STATE_LABELS = {
    linuxcnc.STATE_ESTOP: "ESTOP",
    linuxcnc.STATE_ESTOP_RESET: "READY",
    linuxcnc.STATE_ON: "ON",
    linuxcnc.STATE_OFF: "OFF",
}

MODE_LABELS = {
    linuxcnc.MODE_MANUAL: "MANUAL",
    linuxcnc.MODE_AUTO: "AUTO",
    linuxcnc.MODE_MDI: "MDI",
}


class UserTab(QWidget):
    def __init__(self, parent=None):
        super(UserTab, self).__init__(parent)
        self.setProperty("sidebar", True)
        self.setWindowTitle("Machine Status")
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._stat = linuxcnc.stat()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Machine Status")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(0)
        form.setFormAlignment(0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        layout.addLayout(form)

        self.machine_state = QLabel("-")
        self.mode_state = QLabel("-")
        self.spindle_state = QLabel("-")
        self.spindle_speed = QLabel("-")
        self.homing_state = QLabel("-")

        form.addRow("Machine", self.machine_state)
        form.addRow("Mode", self.mode_state)
        form.addRow("Spindle", self.spindle_state)
        form.addRow("Speed", self.spindle_speed)
        form.addRow("Homed", self.homing_state)

        layout.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(250)
        self._refresh()

    def _set_status(self, label, text, ok=None):
        label.setText(text)
        if ok is None:
            label.setStyleSheet("")
        elif ok:
            label.setStyleSheet("color: #1b5e20; font-weight: 600;")
        else:
            label.setStyleSheet("color: #b71c1c; font-weight: 600;")

    def _refresh(self):
        try:
            self._stat.poll()
        except Exception:
            self._set_status(self.machine_state, "DISCONNECTED", False)
            self._set_status(self.mode_state, "-", None)
            self._set_status(self.spindle_state, "-", None)
            self._set_status(self.spindle_speed, "-", None)
            self._set_status(self.homing_state, "-", None)
            return

        task_state = getattr(self._stat, "task_state", None)
        machine_text = STATE_LABELS.get(task_state, str(task_state))
        self._set_status(self.machine_state, machine_text, task_state == linuxcnc.STATE_ON)

        task_mode = getattr(self._stat, "task_mode", None)
        self._set_status(self.mode_state, MODE_LABELS.get(task_mode, str(task_mode)))

        spindle = {}
        spindle_list = getattr(self._stat, "spindle", None)
        if spindle_list:
            spindle = spindle_list[0] or {}

        spindle_enabled = bool(spindle.get("enabled", False))
        spindle_direction = spindle.get("direction", 0)
        if not spindle_enabled:
            spindle_text = "STOPPED"
        elif spindle_direction > 0:
            spindle_text = "FORWARD"
        elif spindle_direction < 0:
            spindle_text = "REVERSE"
        else:
            spindle_text = "ON"
        self._set_status(self.spindle_state, spindle_text, spindle_enabled)

        speed = spindle.get("speed", 0.0)
        try:
            self._set_status(self.spindle_speed, f"{abs(float(speed)):.0f} RPM")
        except Exception:
            self._set_status(self.spindle_speed, str(speed))

        joint_homed = []
        joints = getattr(self._stat, "joint", [])
        for joint in joints[:4]:
            if isinstance(joint, dict):
                joint_homed.append(bool(joint.get("homed", False)))

        if not joint_homed and hasattr(self._stat, "homed"):
            try:
                joint_homed = [bool(v) for v in list(self._stat.homed)[:4]]
            except Exception:
                joint_homed = []

        if joint_homed:
            homed_count = sum(1 for value in joint_homed if value)
            homed_text = f"{homed_count}/{len(joint_homed)}"
            self._set_status(self.homing_state, homed_text, homed_count == len(joint_homed))
        else:
            self._set_status(self.homing_state, "UNKNOWN", None)
