from common.numpy_fast import clip, interp
import numpy as np
from random import randint
from cereal import car
from common.realtime import DT_CTRL
from common.numpy_fast import clip, interp
from selfdrive.car import apply_std_steer_torque_limits
from selfdrive.car.hyundai.hyundaican import create_lkas11, create_clu11, \
  create_acc_opt, create_frt_radar_opt, create_acc_commands,\
  create_mdps12, create_lfahda_mfc, create_hda_mfc, create_spas11, create_spas12, create_ems_366, create_eems11, create_ems11
from selfdrive.car.hyundai.scc_smoother import SccSmoother
from selfdrive.car.hyundai.values import Buttons, CAR, FEATURES, CarControllerParams
from opendbc.can.packer import CANPacker
from selfdrive.config import Conversions as CV
from common.params import Params
from selfdrive.controls.lib.longcontrol import LongCtrlState
from selfdrive.road_speed_limiter import road_speed_limiter_get_active

VisualAlert = car.CarControl.HUDControl.VisualAlert
min_set_speed = 30 * CV.KPH_TO_MS
###### SPAS ###### - JPR
STEER_ANG_MAX = 450 # SPAS Max Angle
ANGLE_DELTA_BP = [0., 10., 20.]
ANGLE_DELTA_V = [1.19, 1.14, 1.09]    # windup limit
ANGLE_DELTA_VU = [1.29, 1.19, 1.14]   # unwind limit
TQ = 290 # = TQ / 100 = NM is unit of measure for wheel.
SPAS_SWITCH = 30 * CV.MPH_TO_MS # MPH - lowered Bc of model and overlearn steerRatio
STEER_MAX_OFFSET = 105 # How far from MAX LKAS torque to engage Dynamic SPAS when under 60mph.
###### SPAS #######

CLUSTER_ANIMATION_BP = [0., 1., 10., 20., 30., 40., 50.]
CLUSTER_ANIMATION_SPEED= [0., 100., 40., 30., 20., 10., 3.]

def process_hud_alert(enabled, fingerprint, visual_alert, left_lane, right_lane,
                      left_lane_depart, right_lane_depart):

  sys_warning = (visual_alert in (VisualAlert.steerRequired, VisualAlert.ldw, VisualAlert.fcw))

  # initialize to no line visible
  sys_state = 1
  if left_lane and right_lane or sys_warning:  # HUD alert only display when LKAS status is active
    sys_state = 3 if enabled or sys_warning else 4
  elif left_lane:
    sys_state = 5
  elif right_lane:
    sys_state = 6

  # initialize to no warnings
  left_lane_warning = 0
  right_lane_warning = 0
  if left_lane_depart:
    left_lane_warning = 1
  if right_lane_depart:
    right_lane_warning = 1

  return sys_warning, sys_state, left_lane_warning, right_lane_warning

class CarController():
  def __init__(self, dbc_name, CP, VM):
    self.car_fingerprint = CP.carFingerprint
    self.packer = CANPacker(dbc_name)
    self.apply_steer_last = 0
    self.accel = 0
    self.lkas11_cnt = 0
    self.ACCMode = 0

    self.pcm_cnt = 0
    self.last_resume_frame = 0

    self.turning_signal_timer = 0
    self.cut_timer = 0
    self.longcontrol = CP.openpilotLongitudinalControl

    self.turning_indicator_alert = False
    self.emsType = CP.emsType
    self.low_speed_alert = False
    self.gapsettingdance = 2
    self.gapsetting = 0
    self.gapcount = 0
    self.DTQL = 0

    if CP.spasEnabled:
      self.last_apply_angle = 0.0
      self.en_spas = 2
      self.mdps11_stat_last = 0
      self.lkas_active = False
      self.spas_active = False
      self.spas_active_last = 0
      self.override = False
      self.dynamicSpas = Params().get_bool('DynamicSpas')
      self.ratelimit = 2.3 # Starting point - JPR

    param = Params()

    self.ldws_opt = param.get_bool('IsLdwsCar')
    self.stock_navi_decel_enabled = param.get_bool('StockNaviDecelEnabled')
    self.keep_steering_turn_signals = param.get_bool('KeepSteeringTurnSignals')
    self.NoMinLaneChangeSpeed = param.get_bool('NoMinLaneChangeSpeed')
    self.haptic_feedback_speed_camera = param.get_bool('HapticFeedbackWhenSpeedCamera')

    self.scc_smoother = SccSmoother()
    self.last_blinker_frame = 0
    self.prev_active_cam = False
    self.active_cam_timer = 0

  def update(self, c, enabled, CS, frame, CC, actuators, pcm_cancel_cmd, visual_alert,
             left_lane, right_lane, left_lane_depart, right_lane_depart, set_speed, lead_visible, controls):

    # Steering Torque
    new_steer = int(round(actuators.steer * CarControllerParams.STEER_MAX))
    apply_steer = apply_std_steer_torque_limits(new_steer, self.apply_steer_last, CS.out.steeringTorque,
                                                CarControllerParams)

    self.steer_rate_limited = new_steer != apply_steer

    # SPAS limit angle extremes for safety
    if CS.spas_enabled:
      apply_angle = clip(actuators.steeringAngleDeg, -1*(STEER_ANG_MAX), STEER_ANG_MAX)
      apply_diff = abs(apply_angle - CS.out.steeringAngleDeg)
      if apply_diff > 1.75 and c.active: # Rate limit for when steering angle is not apply_angle - JPR
        self.ratelimit = self.ratelimit + 0.03 # Increase each cycle - JPR
        rate_limit = max(self.ratelimit, 10) # Make sure not to go past +-10 on rate - JPR
        #print("apply_diff is greater than 1.5 : rate limit :", rate_limit)
        apply_angle = clip(apply_angle, CS.out.steeringAngleDeg - rate_limit, CS.out.steeringAngleDeg + rate_limit)
      elif c.active:
        self.ratelimit = 2.3 # Reset it back - JPR
        if self.last_apply_angle * apply_angle > 0. and abs(apply_angle) > abs(self.last_apply_angle):
          rate_limit = interp(CS.out.vEgo, ANGLE_DELTA_BP, ANGLE_DELTA_V)
        else:
          rate_limit = interp(CS.out.vEgo, ANGLE_DELTA_BP, ANGLE_DELTA_VU)
        apply_angle = clip(apply_angle, self.last_apply_angle - rate_limit, self.last_apply_angle + rate_limit)

      self.last_apply_angle = apply_angle
      spas_active = CS.spas_enabled and c.active and CS.out.vEgo < 26.82 and (CS.out.vEgo < SPAS_SWITCH or apply_diff > 3.2 and self.dynamicSpas and not CS.out.steeringPressed or abs(apply_angle) > 3. and self.spas_active or CarControllerParams.STEER_MAX - STEER_MAX_OFFSET < apply_steer and self.dynamicSpas)
      lkas_active = c.active and not self.low_speed_alert and abs(CS.out.steeringAngleDeg) < CS.CP.maxSteeringAngleDeg and not CS.mdps11_stat == 5
    else:
      lkas_active = c.active and not CS.out.steerWarning and not self.low_speed_alert and abs(CS.out.steeringAngleDeg) < CS.CP.maxSteeringAngleDeg

    if CS.spas_enabled:
      if Params().get_bool("SpasMode"):
        if abs(CS.out.steeringWheelTorque) > TQ  and self.DTQL > TQ and spas_active and not lkas_active:
          self.override = True
          #print("OVERRIDE")
        else:
          self.override = False
      else:
        if CS.out.steeringPressed:
            self.cut_timer = 0
        if CS.out.steeringPressed or self.cut_timer <= 85: # Keep SPAS cut for 50 cycles after steering pressed to prevent unintentional fighting. - JPR
          spas_active = False
          lkas_active = True
          self.cut_timer += 1

    # Disable steering while turning blinker on and speed below min lane chnage speed
    if (CS.out.leftBlinker or CS.out.rightBlinker) and not self.keep_steering_turn_signals and not self.NoMinLaneChangeSpeed:
      self.turning_signal_timer = 1.5 / DT_CTRL  # Disable for 1.5 Seconds after blinker turned off
    if self.turning_indicator_alert: # set and clear by interface...)
      lkas_active = False
      if CS.spas_enabled:
        spas_active = False
    if self.turning_signal_timer > 0:
      self.turning_signal_timer -= 1

    if not lkas_active:
      apply_steer = 0

    if abs(CS.out.steeringAngleDeg) > 90 and CS.CP.steerLockout:
      lkas_active = False

    self.lkas_active = lkas_active
    if CS.spas_enabled:
      self.spas_active = spas_active

    self.apply_steer_last = apply_steer

    sys_warning, sys_state, left_lane_warning, right_lane_warning = \
      process_hud_alert(enabled, self.car_fingerprint, visual_alert,
                        left_lane, right_lane, left_lane_depart, right_lane_depart)

    if self.haptic_feedback_speed_camera:
      if self.prev_active_cam != self.scc_smoother.active_cam:
        self.prev_active_cam = self.scc_smoother.active_cam
        if self.scc_smoother.active_cam:
          self.active_cam_timer = int(1.5 / DT_CTRL)

      if self.active_cam_timer > 0:
        self.active_cam_timer -= 1
        left_lane_warning = right_lane_warning = 1

    clu11_speed = CS.clu11["CF_Clu_Vanz"]
    enabled_speed = 38 if CS.is_set_speed_in_mph else 60
    if clu11_speed > enabled_speed or not lkas_active:
      enabled_speed = clu11_speed

    if not (min_set_speed < set_speed < 255 * CV.KPH_TO_MS):
      set_speed = min_set_speed
    set_speed *= CV.MS_TO_MPH if CS.is_set_speed_in_mph else CV.MS_TO_KPH

    if frame == 0:  # initialize counts from last received count signals
      self.lkas11_cnt = CS.lkas11["CF_Lkas_MsgCount"]
      
    self.prev_scc_cnt = CS.scc11["AliveCounterACC"]

    self.lkas11_cnt = (self.lkas11_cnt + 1) % 0x10

    can_sends = []

    # tester present - w/ no response (keeps radar disabled)
    if CS.CP.radarDisable:
      if (frame % 100) == 0:
        can_sends.append([0x7D0, 0, b"\x02\x3E\x80\x00\x00\x00\x00\x00", 0])

    can_sends.append(create_lkas11(self.packer, frame, self.car_fingerprint, apply_steer, lkas_active,
                                   CS.lkas11, sys_warning, sys_state, enabled, left_lane, right_lane,
                                   left_lane_warning, right_lane_warning, 0, self.ldws_opt))

    if CS.mdps_bus or CS.scc_bus == 1:  # send lkas11 bus 1 if mdps or scc is on bus 1
      can_sends.append(create_lkas11(self.packer, frame, self.car_fingerprint, apply_steer, lkas_active,
                                     CS.lkas11, sys_warning, sys_state, enabled, left_lane, right_lane,
                                     left_lane_warning, right_lane_warning, 1, self.ldws_opt))

    if frame % 2 and CS.mdps_bus: # send clu11 to mdps if it is not on bus 0
      can_sends.append(create_clu11(self.packer, CS.mdps_bus, CS.clu11, Buttons.NONE, enabled_speed))

    if pcm_cancel_cmd and self.longcontrol and self.pcm_cnt == 0 and CS.out.cruiseState.enabled and not CS.CP.radarDisable: #Make SCC cancel when op disengage or last accel is kept (IDK) -JPR
      can_sends.append(create_clu11(self.packer, CS.scc_bus, CS.clu11, Buttons.CANCEL, clu11_speed))
      self.pcm_cnt += 1
    else:
      self.pcm_cnt += 1
      can_sends.append(create_mdps12(self.packer, frame, CS.mdps12))
      if CS.out.cruiseState.standstill:
        # send resume at a max freq of 10Hz
        if (frame - self.last_resume_frame) * DT_CTRL > 0.1:
          # send 25 messages at a time to increases the likelihood of resume being accepted
          can_sends.extend([create_clu11(self.packer, CS.scc_bus, CS.clu11, Buttons.RES_ACCEL, clu11_speed)] * 25)
          self.last_resume_frame = frame
    
    if self.pcm_cnt == 20:
      self.pcm_cnt = 0 

    if not lead_visible:
      self.animationSpeed = interp(CS.out.vEgo, CLUSTER_ANIMATION_BP, CLUSTER_ANIMATION_SPEED)
      self.gapcount += 1 # Dragon-Pilot; Adapted and adjusted by JPR. Searching for lead animation 
      if self.gapcount > self.animationSpeed and self.gapsettingdance == 2:
        self.gapsettingdance = 1
        self.gapcount = 0
      elif self.gapcount > self.animationSpeed and self.gapsettingdance == 1:
        self.gapsettingdance = 4
        self.gapcount = 0
      elif self.gapcount > self.animationSpeed and self.gapsettingdance == 4:
        self.gapsettingdance = 3
        self.gapcount = 0
      elif self.gapcount > self.animationSpeed and self.gapsettingdance == 3:
        self.gapsettingdance = 2
        self.gapcount = 0
      self.gapsetting = self.gapsettingdance
    else:
      d = CS.lead_distance
      self.gapsetting = 1 if d < 25 else 2 if d < 40 else 3 if d < 60 else 4
    # scc smoother
    self.scc_smoother.update(enabled, can_sends, self.packer, CC, CS, frame, controls)

    if self.longcontrol and CS.cruiseState_enabled or CS.CP.radarDisable:
      if frame % 2 == 0:
        stopping = controls.LoC.long_control_state == LongCtrlState.stopping
        apply_accel = clip(actuators.accel if c.active else 0,
                           CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX)
        apply_accel = self.scc_smoother.get_apply_accel(CS, controls.sm, apply_accel, stopping)
        self.accel = apply_accel
        controls.apply_accel = apply_accel

        aReqValue = CS.scc12["aReqValue"]
        controls.aReqValue = aReqValue

        if aReqValue < controls.aReqValueMin:
          controls.aReqValueMin = controls.aReqValue

        if aReqValue > controls.aReqValueMax:
          controls.aReqValueMax = controls.aReqValue

        jerk = clip(2.0 * (apply_accel - CS.out.aEgo), -12.7, 12.7)

        can_sends.extend(create_acc_commands(self.packer, enabled, apply_accel, jerk, int(frame / 2), lead_visible, set_speed, stopping, self.gapsetting, CS.out.gasPressed, CS.CP.radarDisable)) 
      
    if visual_alert in (VisualAlert.steerRequired, VisualAlert.ldw): # Hands on wheel alert - JPR
      warning = 5
    else:
      warning = 0

    # 20 Hz LFA MFA message
    if frame % 5 == 0:
      activated_hda = road_speed_limiter_get_active()
      # activated_hda: 0 - off, 1 - main road, 2 - highway
      if self.car_fingerprint in FEATURES["send_lfa_mfa"]:
        can_sends.append(create_lfahda_mfc(self.packer, enabled, activated_hda, warning))
      elif CS.has_lfa_hda:
        can_sends.append(create_hda_mfc(self.packer, activated_hda, CS, left_lane, right_lane))

############### SPAS STATES ############## JPR
# State 1 : Start
# State 2 : New Request
# State 3 : Ready to Assist(Steer)
# State 4 : Hand Shake between OpenPilot and MDPS ECU
# State 5 : Assisting (Steering)
# State 6 : Failed to Assist (Steer)
# State 7 : Cancel
# State 8 : Failed to get ready to Assist (Steer)
# ---------------------------------------------------
    if CS.spas_enabled:
      if CS.mdps_bus:
        spas_active_stat = False
        if spas_active: # Spoof Speed on mdps11_stat 3, 4 and 5 JPR
          if CS.mdps11_stat == 4 or CS.mdps11_stat == 5 or CS.mdps11_stat == 3:
            spas_active_stat = True
          else:
            spas_active_stat = False
        if self.emsType == 1:
          can_sends.append(create_ems_366(self.packer, CS.ems_366, spas_active_stat))
          if Params().get_bool('SPASDebug'):
            print("EMS_366")
        elif self.emsType == 2:
          can_sends.append(create_ems11(self.packer, CS.ems11, spas_active_stat))
          if Params().get_bool('SPASDebug'):
            print("EMS_11")
        elif self.emsType == 3:
          can_sends.append(create_eems11(self.packer, CS.eems11, spas_active_stat))
          if Params().get_bool('SPASDebug'):
            print("E_EMS11")

      if (frame % 2) == 0:
        if CS.mdps11_stat == 7:
            self.en_spas = 7

        if CS.mdps11_stat == 7 and self.mdps11_stat_last == 7:
          self.en_spas = 3
          if CS.mdps11_stat == 3:
            self.en_spas = 2

        if CS.mdps11_stat == 2 and spas_active:
          self.en_spas = 3 # Switch to State 3, and get Ready to Assist(Steer). JPR

        if CS.mdps11_stat == 3 and spas_active:
          self.en_spas = 4

        if CS.mdps11_stat == 4 and spas_active:
          self.en_spas = 5

        if CS.mdps11_stat == 5 and not spas_active:
          self.en_spas = 7

        if CS.mdps11_stat == 6: # Failed to Assist and Steer, Set state back to 2 for a new request. JPR
          self.en_spas = 2

        if CS.mdps11_stat == 8: #MDPS ECU Fails to get into state 3 and ready for state 5. JPR
          self.en_spas = 2

        if not spas_active:
          apply_angle = CS.mdps11_strang

        self.mdps11_stat_last = CS.mdps11_stat
        can_sends.append(create_spas11(self.packer, self.car_fingerprint, (frame // 2), self.en_spas, apply_angle, CS.mdps_bus))
        if Params().get_bool('SPASDebug'):
          print("MDPS SPAS State: ", CS.mdps11_stat) # SPAS STATE DEBUG
          print("OP SPAS State: ", self.en_spas) # OpenPilot Ask MDPS to switch to state.
          print("spas_active:", spas_active)
          print("apply angle:", apply_angle)
          print("lkas_active:", lkas_active)
          print("driver torque:", CS.out.steeringWheelTorque)
        if self.emsType == 0:
          print("Please add a car parameter called ret.emsType = (your EMS type) in interface.py : EMS_366 = 1 : EMS_11 = 2 : E_EMS11 = 3")

      # SPAS12 20Hz
      if (frame % 5) == 0:
        can_sends.append(create_spas12(CS.mdps_bus))

      self.spas_active_last = spas_active
      self.DTQL = abs(CS.out.steeringWheelTorque)

    # 5 Hz ACC options
    if frame % 20 == 0 and CS.CP.openpilotLongitudinalControl:
      can_sends.extend(create_acc_opt(self.packer, CS.CP.radarDisable))

    # 2 Hz front radar options
    if frame % 50 == 0 and CS.CP.radarDisable:
      can_sends.append(create_frt_radar_opt(self.packer))

    new_actuators = actuators.copy()
    new_actuators.steer = apply_steer / CarControllerParams.STEER_MAX
    new_actuators.accel = self.accel
    return new_actuators, can_sends
