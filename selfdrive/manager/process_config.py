import os
from common.params import Params
from selfdrive.manager.process import PythonProcess, NativeProcess, DaemonProcess
from selfdrive.hardware import EON, TICI, PC

WEBCAM = os.getenv("USE_WEBCAM") is not None

if Params().get_bool('LoggerEnabled'):
  procs = [
    DaemonProcess("manage_athenad", "selfdrive.athena.manage_athenad", "AthenadPid"),
  # due to qualcomm kernel bugs SIGKILLing camerad sometimes causes page table corruption
    NativeProcess("soundd", "selfdrive/ui", ["./soundd"]),
    NativeProcess("camerad", "selfdrive/camerad", ["./camerad"], unkillable=True, driverview=True),
    NativeProcess("clocksd", "selfdrive/clocksd", ["./clocksd"]),
    NativeProcess("dmonitoringmodeld", "selfdrive/modeld", ["./dmonitoringmodeld"], enabled=False, driverview=True),
    NativeProcess("logcatd", "selfdrive/logcatd", ["./logcatd"]),
    NativeProcess("loggerd", "selfdrive/loggerd", ["./loggerd"]),
    NativeProcess("modeld", "selfdrive/modeld", ["./modeld"]),
    NativeProcess("proclogd", "selfdrive/proclogd", ["./proclogd"]),
    NativeProcess("sensord", "selfdrive/sensord", ["./sensord"], enabled=not PC, persistent=EON, sigkill=EON),
    NativeProcess("ubloxd", "selfdrive/locationd", ["./ubloxd"], enabled=(not PC or WEBCAM)),
    NativeProcess("ui", "selfdrive/ui", ["./ui"], persistent=True, watchdog_max_dt=(10 if TICI else None)),
    NativeProcess("locationd", "selfdrive/locationd", ["./locationd"]),
    PythonProcess("calibrationd", "selfdrive.locationd.calibrationd"),
    PythonProcess("controlsd", "selfdrive.controls.controlsd"),
    PythonProcess("deleter", "selfdrive.loggerd.deleter", persistent=True),
    PythonProcess("dmonitoringd", "selfdrive.monitoring.dmonitoringd", enabled=False, driverview=True),
    PythonProcess("logmessaged", "selfdrive.logmessaged", persistent=True),
    PythonProcess("pandad", "selfdrive.pandad", persistent=True),
    PythonProcess("paramsd", "selfdrive.locationd.paramsd"),
    PythonProcess("plannerd", "selfdrive.controls.plannerd"),
    PythonProcess("radard", "selfdrive.controls.radard"),
    PythonProcess("rtshield", "selfdrive.rtshield", enabled=EON),
    PythonProcess("thermald", "selfdrive.thermald.thermald", persistent=True),
    PythonProcess("timezoned", "selfdrive.timezoned", enabled=TICI, persistent=True),
    PythonProcess("tombstoned", "selfdrive.tombstoned", enabled=not PC, persistent=True),
    PythonProcess("updated", "selfdrive.updated", enabled=not PC, persistent=True),
    PythonProcess("uploader", "selfdrive.loggerd.uploader", persistent=True),
      # EON only
    PythonProcess("rtshield", "selfdrive.rtshield", enabled=EON),
    PythonProcess("androidd", "selfdrive.hardware.eon.androidd", enabled=EON, persistent=True),
  ]
else:
  procs = [
  #DaemonProcess("manage_athenad", "selfdrive.athena.manage_athenad", "AthenadPid"),
  # due to qualcomm kernel bugs SIGKILLing camerad sometimes causes page table corruption
  NativeProcess("camerad", "selfdrive/camerad", ["./camerad"], unkillable=True, driverview=True),
  NativeProcess("clocksd", "selfdrive/clocksd", ["./clocksd"]),
  NativeProcess("dmonitoringmodeld", "selfdrive/modeld", ["./dmonitoringmodeld"], enabled=False, driverview=True),
  #NativeProcess("logcatd", "selfdrive/logcatd", ["./logcatd"]),
  #NativeProcess("loggerd", "selfdrive/loggerd", ["./loggerd"]),
  NativeProcess("modeld", "selfdrive/modeld", ["./modeld"]),
  NativeProcess("navd", "selfdrive/ui/navd", ["./navd"], enabled=(PC or TICI), persistent=True),
  NativeProcess("proclogd", "selfdrive/proclogd", ["./proclogd"]),
  NativeProcess("sensord", "selfdrive/sensord", ["./sensord"], enabled=not PC, persistent=EON, sigkill=EON),
  NativeProcess("ubloxd", "selfdrive/locationd", ["./ubloxd"], enabled=(not PC or WEBCAM)),
  NativeProcess("ui", "selfdrive/ui", ["./ui"], persistent=True, watchdog_max_dt=(5 if TICI else None)),
  NativeProcess("soundd", "selfdrive/ui/soundd", ["./soundd"]),
  NativeProcess("locationd", "selfdrive/locationd", ["./locationd"]),
  NativeProcess("boardd", "selfdrive/boardd", ["./boardd"], enabled=False),
  PythonProcess("calibrationd", "selfdrive.locationd.calibrationd"),
  PythonProcess("controlsd", "selfdrive.controls.controlsd"),
  PythonProcess("deleter", "selfdrive.loggerd.deleter", persistent=True),
  PythonProcess("dmonitoringd", "selfdrive.monitoring.dmonitoringd", enabled=False, driverview=True),
  #PythonProcess("logmessaged", "selfdrive.logmessaged", persistent=True),
  PythonProcess("pandad", "selfdrive.pandad", persistent=True),
  PythonProcess("paramsd", "selfdrive.locationd.paramsd"),
  PythonProcess("plannerd", "selfdrive.controls.plannerd"),
  PythonProcess("radard", "selfdrive.controls.radard"),
  PythonProcess("thermald", "selfdrive.thermald.thermald", persistent=True),
  PythonProcess("timezoned", "selfdrive.timezoned", enabled=TICI, persistent=True),
  #PythonProcess("tombstoned", "selfdrive.tombstoned", enabled=not PC, persistent=True),
  PythonProcess("updated", "selfdrive.updated", enabled=not PC, persistent=True),
  #PythonProcess("uploader", "selfdrive.loggerd.uploader", persistent=True),

  # EON only
  PythonProcess("rtshield", "selfdrive.rtshield", enabled=EON),
  PythonProcess("androidd", "selfdrive.hardware.eon.androidd", enabled=EON, persistent=True),
]

managed_processes = {p.name: p for p in procs}
