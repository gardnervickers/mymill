import subprocess

import linuxcnc

from qtpy.QtCore import QSignalBlocker, QTimer, Qt
from qtpy.QtWidgets import QFormLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget


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
        self.setObjectName("STATUS")
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
        form.setLabelAlignment(Qt.Alignment())
        form.setFormAlignment(Qt.Alignment())
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        layout.addLayout(form)

        self.machine_state = QLabel("-")
        self.mode_state = QLabel("-")
        self.spindle_state = QLabel("-")
        self.spindle_speed = QLabel("-")
        self.homing_state = QLabel("-")
        self.drawbar_state = QLabel("-")
        self.blast_state = QLabel("-")
        self.lockout_state = QLabel("-")

        form.addRow("Machine", self.machine_state)
        form.addRow("Mode", self.mode_state)
        form.addRow("Spindle", self.spindle_state)
        form.addRow("Speed", self.spindle_speed)
        form.addRow("Homed", self.homing_state)
        form.addRow("PDB Extend", self.drawbar_state)
        form.addRow("TS Blast", self.blast_state)
        form.addRow("Lockout", self.lockout_state)

        self.drawbar_button = QPushButton("Power Drawbar Extend: Retracted")
        self.drawbar_button.setCheckable(True)
        self.drawbar_button.toggled.connect(self._toggle_drawbar)
        layout.addWidget(self.drawbar_button)

        self.blast_button = QPushButton("Touchsetter Blast: Off")
        self.blast_button.setCheckable(True)
        self.blast_button.toggled.connect(self._toggle_blast)
        layout.addWidget(self.blast_button)

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
            self._set_status(self.drawbar_state, "-", None)
            self._set_status(self.blast_state, "-", None)
            self._set_status(self.lockout_state, "-", None)
            self._set_drawbar_button_state(None, None)
            self._set_blast_button_state(None)
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

        spindle_commanded = bool(spindle.get("enabled", False))
        spindle_enabled = self._get_spindle_enabled_state()
        if spindle_enabled is None:
            spindle_enabled = spindle_commanded
        spindle_direction = spindle.get("direction", 0)
        if drawbar_active := self._get_drawbar_state():
            if spindle_commanded and not spindle_enabled:
                spindle_text = "BLOCKED"
            else:
                spindle_text = "STOPPED"
        elif not spindle_enabled:
            spindle_text = "STOPPED"
        elif spindle_direction > 0:
            spindle_text = "FORWARD"
        elif spindle_direction < 0:
            spindle_text = "REVERSE"
        else:
            spindle_text = "ON"
        self._set_status(self.spindle_state, spindle_text, spindle_enabled and spindle_text != "BLOCKED")

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

        drawbar_locked_out = spindle_enabled

        manual_drawbar_request = self._get_manual_drawbar_request()
        if drawbar_locked_out and manual_drawbar_request:
            self._set_manual_drawbar_request(False)
            manual_drawbar_request = False

        if drawbar_active is None:
            self._set_status(self.lockout_state, "UNKNOWN", None)
        elif drawbar_active:
            self._set_status(self.lockout_state, "SPDL LK", False)
        elif drawbar_locked_out:
            self._set_status(self.lockout_state, "PDB LK", False)
        else:
            self._set_status(self.lockout_state, "READY", True)

        if drawbar_active is None:
            self._set_status(self.drawbar_state, "UNKNOWN", None)
        elif drawbar_active:
            self._set_status(self.drawbar_state, "EXTENDED", False)
        else:
            self._set_status(self.drawbar_state, "RETRACTED", True)
        self._set_drawbar_button_state(manual_drawbar_request, drawbar_locked_out)

        blast_active = self._get_touchsetter_blast_state()
        if blast_active is None:
            self._set_status(self.blast_state, "UNKNOWN", None)
        elif blast_active:
            self._set_status(self.blast_state, "ON", False)
        else:
            self._set_status(self.blast_state, "OFF", True)
        self._set_blast_button_state(self._get_manual_touchsetter_blast_request())

    def _halcmd(self, *args):
        try:
            return subprocess.run(
                ["halcmd", *args],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None

    def _get_drawbar_state(self):
        result = self._halcmd("getp", "drawbar-out")
        if result is None:
            return None
        value = result.stdout.strip().lower()
        if value in {"1", "true"}:
            return True
        if value in {"0", "false"}:
            return False
        return None

    def _get_manual_drawbar_request(self):
        return self._get_hal_bool("drawbar-manual-request-pin")

    def _get_spindle_enabled_state(self):
        return self._get_hal_bool("spindle-enable-allowed-pin")

    def _get_touchsetter_blast_state(self):
        return self._get_hal_bool("touch-probe-air-out")

    def _get_manual_touchsetter_blast_request(self):
        return self._get_hal_bool("touchsetter-blast-manual-request-pin")

    def _get_hal_bool(self, pin_name):
        result = self._halcmd("getp", pin_name)
        if result is None:
            return None
        value = result.stdout.strip().lower()
        if value in {"1", "true"}:
            return True
        if value in {"0", "false"}:
            return False
        return None

    def _set_manual_drawbar_request(self, active):
        return self._halcmd("setp", "drawbar-manual-request-pin", "TRUE" if active else "FALSE")

    def _set_manual_touchsetter_blast_request(self, active):
        return self._halcmd("setp", "touchsetter-blast-manual-request-pin", "TRUE" if active else "FALSE")

    def _set_drawbar_button_state(self, active, locked_out):
        if locked_out:
            text = "Power Drawbar Extend: Locked Out"
        elif active is None:
            text = "Power Drawbar Extend: Unknown"
        elif active:
            text = "Power Drawbar Extend: Extended"
        else:
            text = "Power Drawbar Extend: Retracted"
        blocker = QSignalBlocker(self.drawbar_button)
        self.drawbar_button.setChecked(bool(active))
        self.drawbar_button.setText(text)
        self.drawbar_button.setEnabled(active is not None and not locked_out)
        del blocker

    def _set_blast_button_state(self, active):
        if active is None:
            text = "Touchsetter Blast: Unknown"
        elif active:
            text = "Touchsetter Blast: On"
        else:
            text = "Touchsetter Blast: Off"
        blocker = QSignalBlocker(self.blast_button)
        self.blast_button.setChecked(bool(active))
        self.blast_button.setText(text)
        self.blast_button.setEnabled(active is not None)
        del blocker

    def _toggle_drawbar(self, active):
        try:
            self._stat.poll()
        except Exception:
            self._set_status(self.drawbar_state, "ERROR", False)
            self._set_drawbar_button_state(self._get_manual_drawbar_request(), None)
            return

        spindle_list = getattr(self._stat, "spindle", None)
        spindle = spindle_list[0] if spindle_list else {}
        spindle_enabled = self._get_spindle_enabled_state()
        if spindle_enabled is None:
            spindle_enabled = bool(spindle.get("enabled", False))
        if spindle_enabled:
            self._set_manual_drawbar_request(False)
            self._set_status(self.lockout_state, "PDB LOCKED", False)
            self._set_drawbar_button_state(False, True)
            return

        result = self._set_manual_drawbar_request(active)
        if result is None:
            self._set_status(self.drawbar_state, "ERROR", False)
            self._set_drawbar_button_state(self._get_manual_drawbar_request(), spindle_enabled)
            return

        self._set_drawbar_button_state(active, False)

    def _toggle_blast(self, active):
        result = self._set_manual_touchsetter_blast_request(active)
        if result is None:
            self._set_status(self.blast_state, "ERROR", False)
            self._set_blast_button_state(self._get_manual_touchsetter_blast_request())
            return

        self._set_blast_button_state(active)
