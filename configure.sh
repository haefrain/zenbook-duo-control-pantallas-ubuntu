#!/bin/bash
set -e

# ─── Colores ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

CONFIG="/opt/zenbook-duo/config.yaml"
SERVICE="zenbook-duo"

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()      { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${BOLD}${CYAN}── $* ──${NC}"; }

[ "$EUID" -ne 0 ] && error "Ejecuta con sudo: sudo ./configure.sh"
[ ! -f "$CONFIG" ] && error "No se encontró $CONFIG. Ejecuta primero install.sh"

# ─── Leer valor actual del config.yaml ───────────────────────────────────────
# Uso: cfg_get "features.auto_rotate"  →  "true" o "80" etc.
cfg_get() {
    python3 -c "
import yaml
with open('$CONFIG') as f:
    c = yaml.safe_load(f)
keys = '$1'.split('.')
val = c
for k in keys:
    val = val.get(k, '') if isinstance(val, dict) else ''
print(str(val).lower() if isinstance(val, bool) else (val if val is not None else ''))
" 2>/dev/null
}

# bool → "s" o "n"
bool_to_yn() { [ "$1" = "true" ] && echo "s" || echo "n"; }

ask_yn() {
    local prompt="$1" default="${2:-s}" hint
    [ "$default" = "s" ] && hint="[S/n]" || hint="[s/N]"
    printf "  %s %s: " "$prompt" "$hint" >&2
    read -r ans
    ans="${ans:-$default}"
    case "$ans" in
        [SsYy]*)
            echo -e "         ${GREEN}✓ Activado${NC}" >&2
            echo "true"
            ;;
        *)
            echo -e "         ${YELLOW}✗ Desactivado${NC}" >&2
            echo "false"
            ;;
    esac
}

ask_val() {
    printf "  %s [%s]: " "$1" "$2" >&2
    read -r val
    echo "${val:-$2}"
}

detect_touchscreen_ids() {
    # Busca dispositivos táctiles ELAN en /sys/class/input y extrae su VID:PID.
    # Salida: líneas "vid:pid\tnombre_completo", ordenadas en reversa
    # (04f3:425b antes de 04f3:425a → superior antes que inferior).
    local name id
    for name_file in /sys/class/input/event*/device/name; do
        [ -f "$name_file" ] || continue
        name=$(cat "$name_file" 2>/dev/null)
        echo "$name" | grep -qi "^elan" || continue
        # El nombre tiene la forma "ELAN9008:00 04F3:425B" — extrae el VID:PID
        id=$(echo "$name" | grep -oE '[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}' | tr '[:upper:]' '[:lower:]')
        [ -n "$id" ] && printf '%s\t%s\n' "$id" "$name"
    done | sort -u -r
}

# ─── Mostrar config actual ────────────────────────────────────────────────────
section "Configuración actual"
echo -e "  Archivo: ${CYAN}$CONFIG${NC}"
echo ""
echo -e "  ${BOLD}Funciones:${NC}"
for feat in auto_rotate auto_brightness battery_protection display_dock touchscreen_mapping; do
    val=$(cfg_get "features.$feat")
    [ "$val" = "true" ] \
        && echo -e "    ${GREEN}✓${NC} $feat" \
        || echo -e "    ${YELLOW}✗${NC} $feat"
done
echo ""

# ─── Selección de funciones ───────────────────────────────────────────────────
section "Funciones"
echo "  Cambia o confirma cada función (Enter = mantener valor actual):"
echo ""

FEAT_ROTATE=$(ask_yn        "Auto-rotación de pantallas"                        "$(bool_to_yn "$(cfg_get features.auto_rotate)")")
FEAT_BRIGHTNESS=$(ask_yn    "Brillo automático por sensor de luz ambiental"     "$(bool_to_yn "$(cfg_get features.auto_brightness)")")
FEAT_BATTERY=$(ask_yn       "Protección de batería (limitar carga máxima)"      "$(bool_to_yn "$(cfg_get features.battery_protection)")")
FEAT_DOCK=$(ask_yn          "Apagar/encender pantalla inferior con el teclado"  "$(bool_to_yn "$(cfg_get features.display_dock)")")
FEAT_TOUCHSCREEN=$(ask_yn   "Mapeo de touchscreens (corrige táctil de cada pantalla)" "$(bool_to_yn "$(cfg_get features.touchscreen_mapping)")")

# ─── Batería ──────────────────────────────────────────────────────────────────
BATTERY_LIMIT=$(cfg_get battery.charge_limit)
# Corregir valores inválidos que hayan quedado grabados
case "$BATTERY_LIMIT" in ''|*[!0-9]*) BATTERY_LIMIT=80 ;; esac

if [ "$FEAT_BATTERY" = "true" ]; then
    section "Batería"
    BATTERY_LIMIT=$(ask_val "Límite de carga (%)" "$BATTERY_LIMIT")
fi

# ─── Teclado ─────────────────────────────────────────────────────────────────
VID=$(cfg_get keyboard.vendor_id)
PID=$(cfg_get keyboard.product_id)
MAC=$(cfg_get keyboard.mac_address)

if [ "$FEAT_DOCK" = "true" ]; then
    section "Teclado"
    DETECTED=$(lsusb 2>/dev/null | grep -i "0b05" || true)
    [ -n "$DETECTED" ] && ok "Encontrado: $DETECTED"
    echo ""
    VID=$(ask_val "Vendor ID del teclado" "$VID")
    PID=$(ask_val "Product ID del teclado" "$PID")
    echo "  Para obtener la MAC: bluetoothctl devices"
    MAC=$(ask_val "Dirección MAC bluetooth del teclado" "$MAC")
fi

# ─── Pantallas ────────────────────────────────────────────────────────────────
section "Pantallas"
DISPLAY_TOP=$(cfg_get displays.top)
DISPLAY_BOT=$(cfg_get displays.bottom)
SCALE=$(cfg_get displays.scale)

DISPLAY_TOP=$(ask_val "Pantalla superior" "$DISPLAY_TOP")
DISPLAY_BOT=$(ask_val "Pantalla inferior" "$DISPLAY_BOT")
SCALE=$(ask_val       "Factor de escala HiDPI" "$SCALE")

# ─── Touchscreen ─────────────────────────────────────────────────────────────
TOUCH_TOP=$(cfg_get touchscreen.top_device)
TOUCH_BOT=$(cfg_get touchscreen.bottom_device)
SWAP_TOUCH=$(cfg_get touchscreen.swap)
[ -z "$TOUCH_TOP" ]         && TOUCH_TOP="04f3:425b"
[ -z "$TOUCH_BOT" ]         && TOUCH_BOT="04f3:425a"
[ "$SWAP_TOUCH" != "true" ] && SWAP_TOUCH=false

if [ "$FEAT_TOUCHSCREEN" = "true" ]; then
    section "Touchscreen"
    echo "  Buscando dispositivos táctiles ELAN en el sistema..."
    echo ""

    DETECTED_TOUCH=$(detect_touchscreen_ids)
    TOUCH_COUNT=$(echo "$DETECTED_TOUCH" | grep -c '^[0-9a-f]' || true)

    if [ "$TOUCH_COUNT" -ge 2 ]; then
        ok "Se encontraron $TOUCH_COUNT dispositivos táctiles:"
        echo "$DETECTED_TOUCH" | while IFS=$'\t' read -r id name; do
            echo -e "    ${CYAN}${id}${NC}  →  ${name}"
        done
        echo ""
        # Solo sugerir los detectados si difieren de lo que ya hay en config
        DET_TOP=$(echo "$DETECTED_TOUCH" | head -1 | cut -f1)
        DET_BOT=$(echo "$DETECTED_TOUCH" | sed -n '2p' | cut -f1)
        [ "$TOUCH_TOP" = "04f3:425b" ] && TOUCH_TOP="$DET_TOP"
        [ "$TOUCH_BOT" = "04f3:425a" ] && TOUCH_BOT="$DET_BOT"
    elif [ "$TOUCH_COUNT" -eq 1 ]; then
        warn "Solo se detectó 1 dispositivo táctil:"
        echo "$DETECTED_TOUCH"
        echo ""
        echo "  Para buscar manualmente:"
        echo "    grep -rh '' /sys/class/input/event*/device/name 2>/dev/null | grep -i elan"
        echo ""
    else
        warn "No se detectaron dispositivos táctiles automáticamente."
        echo "  Para buscar manualmente:"
        echo "    grep -rh '' /sys/class/input/event*/device/name 2>/dev/null | grep -i elan"
        echo ""
    fi

    TOUCH_TOP=$(ask_val "ID táctil pantalla superior (${DISPLAY_TOP})" "$TOUCH_TOP")
    TOUCH_BOT=$(ask_val "ID táctil pantalla inferior (${DISPLAY_BOT})" "$TOUCH_BOT")
    SWAP_YN=$(ask_yn "¿Intercambiar táctiles? (si superior e inferior están al revés)" "$(bool_to_yn "$SWAP_TOUCH")")
    [ "$SWAP_YN" = "true" ] && SWAP_TOUCH=true || SWAP_TOUCH=false
fi

# ─── Escribir config ──────────────────────────────────────────────────────────
section "Aplicando configuración"

USER=$(cfg_get system.username)

cat > "$CONFIG" << YAML
system:
  username: "$USER"

features:
  auto_rotate: $FEAT_ROTATE
  auto_brightness: $FEAT_BRIGHTNESS
  battery_protection: $FEAT_BATTERY
  display_dock: $FEAT_DOCK
  touchscreen_mapping: $FEAT_TOUCHSCREEN

keyboard:
  vendor_id: "$VID"
  product_id: "$PID"
  mac_address: "$MAC"

displays:
  top: "$DISPLAY_TOP"
  bottom: "$DISPLAY_BOT"
  scale: $SCALE

battery:
  charge_limit: $BATTERY_LIMIT

touchscreen:
  top_device: "$TOUCH_TOP"
  bottom_device: "$TOUCH_BOT"
  swap: $SWAP_TOUCH
YAML

ok "config.yaml actualizado"

# ─── Reiniciar servicio ───────────────────────────────────────────────────────
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    systemctl restart "$SERVICE"
    ok "Servicio reiniciado"
elif systemctl is-enabled --quiet "$SERVICE" 2>/dev/null; then
    systemctl start "$SERVICE" || warn "No se pudo iniciar el servicio ahora (¿Wayland disponible?)"
fi

# ─── Resumen ──────────────────────────────────────────────────────────────────
section "Configuración aplicada"
echo ""
echo -e "  ${BOLD}Funciones activas:${NC}"
[ "$FEAT_ROTATE"      = "true" ] && echo -e "    ${GREEN}•${NC} Auto-rotación de pantallas"
[ "$FEAT_BRIGHTNESS"  = "true" ] && echo -e "    ${GREEN}•${NC} Brillo automático"
[ "$FEAT_BATTERY"     = "true" ] && echo -e "    ${GREEN}•${NC} Protección de batería (límite: ${BATTERY_LIMIT}%)"
[ "$FEAT_DOCK"        = "true" ] && echo -e "    ${GREEN}•${NC} Control de pantalla con teclado"
[ "$FEAT_TOUCHSCREEN" = "true" ] && echo -e "    ${GREEN}•${NC} Mapeo de touchscreens"
echo ""
echo -e "  ${CYAN}Para ver el estado:${NC} systemctl status $SERVICE"
echo ""
