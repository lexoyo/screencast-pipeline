#!/usr/bin/env bash
# =============================================================================
# Reproducible OBS setup for the screencast pipeline (record screen + face).
#
# Recreates, idempotently, everything configured by hand:
#   1. installs the Source Record plugin (records the webcam to its own file)
#   2. writes the "Screencast" scene collection (screen + face-in-corner + the
#      Source Record filter that outputs a clean full-frame face file)
#   3. writes the "Screencast" profile (NVENC HEVC / mkv / 48 kHz mono / 1080p30)
#   4. activates both in OBS
#
# Result: one Record click -> two frame-synced files:
#   <SCREENCAST_DIR>/<date>.mkv        screen + face-in-corner + mic   (screencast look)
#   <SCREENCAST_DIR>/cam/<date> cam.mkv  clean full-frame face          (face / zoom shots)
#
# OBS MUST BE CLOSED while this runs. On first launch OBS asks once which
# screen to share (system security prompt — unavoidable).
#
# Edit the CONFIG block if the hardware changes.
# =============================================================================
set -euo pipefail

# ---- CONFIG (this machine) --------------------------------------------------
MIC_DEVICE="alsa_input.usb-Razer_Inc._Razer_Seiren_V3_Mini-00.mono-fallback"
WEBCAM_DEVICE="/dev/video0"
SCREENCAST_DIR="$HOME/Videos/Screencasts"
PLUGIN_VER="0.4.8"
# List devices if needed:
#   mic  -> pactl list short sources | grep -iv monitor
#   cam  -> ls /dev/video*    (test with: ffplay /dev/videoN)
# -----------------------------------------------------------------------------

OBSCFG="$HOME/.config/obs-studio"
SO="$OBSCFG/plugins/source-record/bin/64bit/source-record.so"

if pgrep -x obs >/dev/null; then
  echo "!! OBS est ouvert — ferme-le complètement (File > Exit) puis relance ce script."; exit 1
fi
command -v curl >/dev/null || { echo "curl requis"; exit 1; }
command -v python3 >/dev/null || { echo "python3 requis"; exit 1; }

echo ">> 1/4  plugin Source Record"
if [ -f "$SO" ]; then
  echo "   déjà installé."
else
  tmp="$(mktemp -d)"
  url="https://github.com/exeldro/obs-source-record/releases/download/${PLUGIN_VER}/source-record-${PLUGIN_VER}-ubuntu-22.04.tar.gz"
  curl -fsSL -o "$tmp/sr.tgz" "$url"
  mkdir -p "$OBSCFG/plugins"
  tar xzf "$tmp/sr.tgz" -C "$OBSCFG/plugins"
  rm -rf "$tmp"
  [ -f "$SO" ] && echo "   installé." || { echo "   échec install plugin"; exit 1; }
fi
ldd "$SO" 2>&1 | grep -q "not found" && echo "   ATTENTION: dépendances manquantes pour le plugin" || true

echo ">> 2/4  collection de scènes 'Screencast'"
mkdir -p "$SCREENCAST_DIR/cam"
python3 - "$OBSCFG/basic/scenes/Screencast.json" "$WEBCAM_DEVICE" "$MIC_DEVICE" "$SCREENCAST_DIR" <<'PY'
import json, sys, uuid
scene_path, webcam, mic, scdir = sys.argv[1:5]
CANVAS="6c69626f-6273-4c00-9d88-c5136d61696e"
scr_u, cam_u = str(uuid.uuid4()), str(uuid.uuid4())

def rel(cx, cy, bx, by, U=540.0):
    return ((cx-960)/U, (cy-540)/U), (bx/U, by/U)
def item(name, su, iid, cx, cy, bx, by):
    (prx,pry),(brx,bry)=rel(cx,cy,bx,by)
    return {"name":name,"source_uuid":su,"visible":True,"locked":False,"rot":0.0,
        "scale_ref":{"x":1920.0,"y":1080.0},"align":0,"bounds_type":2,"bounds_align":0,
        "bounds_crop":False,"crop_left":0,"crop_top":0,"crop_right":0,"crop_bottom":0,
        "id":iid,"group_item_backup":False,"pos":{"x":float(cx),"y":float(cy)},
        "pos_rel":{"x":prx,"y":pry},"scale":{"x":1.0,"y":1.0},"scale_rel":{"x":1.0,"y":1.0},
        "bounds":{"x":float(bx),"y":float(by)},"bounds_rel":{"x":brx,"y":bry},
        "scale_filter":"disable","blend_method":"default","blend_type":"normal",
        "show_transition":{"duration":0},"hide_transition":{"duration":0},"private_settings":{}}
def src(name, sid, su, settings, filters=None):
    o={"prev_ver":536936449,"name":name,"uuid":su,"id":sid,"versioned_id":sid,
       "settings":settings,"mixers":0,"sync":0,"flags":0,"volume":1.0,"balance":0.5,
       "enabled":True,"muted":False,"push-to-mute":False,"push-to-mute-delay":0,
       "push-to-talk":False,"push-to-talk-delay":0,"hotkeys":{},"deinterlace_mode":0,
       "deinterlace_field_order":0,"monitoring_type":0,"private_settings":{}}
    if filters: o["filters"]=filters
    return o

source_record={"prev_ver":536936449,"name":"Source Record","uuid":str(uuid.uuid4()),
    "id":"source_record_filter","versioned_id":"source_record_filter",
    "settings":{"path":scdir+"/cam",
        "filename":"%CCYY-%MM-%DD %hh-%mm-%ss cam",
        "filename_formatting":"%CCYY-%MM-%DD %hh-%mm-%ss cam",
        "record_mode":3, "encoder":"obs_nvenc_h264_tex"},
    "enabled":True,"mixers":0,"sync":0,"flags":0,"volume":1.0,"balance":0.5,"muted":False,
    "push-to-mute":False,"push-to-mute-delay":0,"push-to-talk":False,"push-to-talk-delay":0,
    "hotkeys":{},"deinterlace_mode":0,"deinterlace_field_order":0,"monitoring_type":0,
    "private_settings":{}}

cam_item=item("Video Capture Device (V4L2)",cam_u,2,1648,913,480,270)   # bottom-right corner
scr_item=item("Screen Capture (PipeWire)",scr_u,1,960,540,1920,1080)    # full canvas
scene=src("REC","scene",str(uuid.uuid4()),{"id_counter":2,"custom_size":False,"items":[cam_item,scr_item]})
scene["hotkeys"]={"OBSBasic.SelectScene":[]}; scene["canvas_uuid"]=CANVAS
screen=src("Screen Capture (PipeWire)","pipewire-screen-capture-source",scr_u,{"RestoreToken":""})
cam=src("Video Capture Device (V4L2)","v4l2_input",cam_u,
        {"device_id":webcam,"input":0,"pixelformat":861030210},filters=[source_record])

coll={"name":"Screencast",
  "AuxAudioDevice1":{"prev_ver":536936449,"name":"Mic/Aux","uuid":str(uuid.uuid4()),
    "id":"pulse_input_capture","versioned_id":"pulse_input_capture",
    "settings":{"device_id":mic},"mixers":255,"sync":0,"flags":0,"volume":1.0,"balance":0.5,
    "enabled":True,"muted":False,"push-to-mute":False,"push-to-mute-delay":0,
    "push-to-talk":False,"push-to-talk-delay":0,
    "hotkeys":{"libobs.mute":[],"libobs.unmute":[],"libobs.push-to-mute":[],"libobs.push-to-talk":[]},
    "deinterlace_mode":0,"deinterlace_field_order":0,"monitoring_type":0,"private_settings":{}},
  "sources":[scene,screen,cam],"groups":[],"scene_order":[{"name":"REC"}],
  "current_scene":"REC","current_program_scene":"REC","canvases":[],
  "current_transition":"Fade","transition_duration":300,"transitions":[],
  "quick_transitions":[{"name":"Cut","duration":300,"hotkeys":[],"id":1,"fade_to_black":False},
                       {"name":"Fade","duration":300,"hotkeys":[],"id":2,"fade_to_black":False}],
  "saved_projectors":[],"preview_locked":False,"scaling_enabled":False,"scaling_level":-2,
  "scaling_off_x":0.0,"scaling_off_y":0.0,"modules":{"scripts-tool":[],"output-timer":{}},"version":2}
json.dump(coll, open(scene_path,"w"), indent=4); json.load(open(scene_path))
print("   ->", scene_path)
PY

echo ">> 3/4  profil 'Screencast' (réglages d'enregistrement)"
PDIR="$OBSCFG/basic/profiles/Screencast"; mkdir -p "$PDIR"
cat > "$PDIR/basic.ini" <<INI
[General]
Name=Screencast
[Output]
Mode=Simple
[SimpleOutput]
FilePath=$SCREENCAST_DIR
RecFormat2=mkv
RecQuality=Small
RecEncoder=nvenc_hevc
RecAudioEncoder=aac
NVENCPreset2=p5
[Video]
BaseCX=1920
BaseCY=1080
OutputCX=1920
OutputCY=1080
FPSType=1
FPSCommon=30
[Audio]
SampleRate=48000
ChannelSetup=Mono
INI
echo "   -> $PDIR/basic.ini"

echo ">> 4/4  activation dans OBS"
python3 - "$OBSCFG/global.ini" <<'PY'
import sys,re
p=sys.argv[1]; t=open(p,encoding="utf-8").read()
kv={"Profile":"Screencast","ProfileDir":"Screencast",
    "SceneCollection":"Screencast","SceneCollectionFile":"Screencast"}
if "[Basic]" not in t: t="[Basic]\n"+t
for k,v in kv.items():
    if re.search(rf"(?m)^{k}=",t): t=re.sub(rf"(?m)^{k}=.*$",f"{k}={v}",t)
    else: t=re.sub(r"(\[Basic\]\n)",rf"\1{k}={v}\n",t,count=1)
open(p,"w",encoding="utf-8").write(t)
print("   profil + collection activés")
PY

echo
echo "OK. Ouvre OBS -> collection 'Screencast', scène 'REC'."
echo "Choisis l'écran à partager une fois, puis Start Recording."
echo "Tu obtiens 2 fichiers dans: $SCREENCAST_DIR (+ /cam)"
