#!/usr/bin/env python3
import time
import json
import jwt
from pathlib import Path

from datetime import datetime, timedelta
from common.api import api_get
from common.params import Params
from common.spinner import Spinner
from common.basedir import PERSIST
from selfdrive.controls.lib.alertmanager import set_offroad_alert
from selfdrive.hardware import HARDWARE, PC
from selfdrive.swaglog import cloudlog


UNREGISTERED_DONGLE_ID = "UnregisteredDevice"


def is_registered_device() -> bool:
  dongle = Params().get("DongleId", encoding='utf-8')
  return dongle not in (None, UNREGISTERED_DONGLE_ID)


def register(show_spinner=False) -> str:
  return UNREGISTERED_DONGLE_ID


if __name__ == "__main__":
  print(register())
