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

INSTALL_DIR="/opt/zenbook-duo"
SERVICE_NAME="zenbook-duo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Funciones ─────────────────────────────────────────────────────────────────
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()      { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${BOLD}${CYAN}── $* ──${NC}"; }

ask_yn() {
    # ask_yn "Pregunta" "s|n"  →  retorna "true" o "false"
    local prompt="$1"
    local default="${2:-s}"
    local hint
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
    # ask_val "Pregunta" "default"
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

# ─── Verificaciones previas ────────────────────────────────────────────────────
[ "$EUID" -ne 0 ] && error "Ejecuta con sudo: sudo ./install.sh"

section "Zenbook Duo Control — Instalador"
echo -e "  Directorio de instalación: ${CYAN}$INSTALL_DIR${NC}"
echo -e "  Servicio systemd:          ${CYAN}$SERVICE_NAME${NC}"

# ─── Detectar usuario real ────────────────────────────────────────────────────
section "Detectando usuario"
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo '')}"
if [ -z "$REAL_USER" ]; then
    REAL_USER=$(ask_val "No se detectó el usuario. Introduce tu nombre de usuario" "")
    [ -z "$REAL_USER" ] && error "Se necesita un nombre de usuario."
fi
USER_UID=$(id -u "$REAL_USER" 2>/dev/null) || error "Usuario '$REAL_USER' no existe."
ok "Usuario: $REAL_USER (UID: $USER_UID)"

# ─── Dependencias del sistema ─────────────────────────────────────────────────
section "Instalando dependencias del sistema"
apt-get install -y -q \
    iio-sensor-proxy \
    python3-dbus \
    python3-yaml \
    python3-pip \
    python3-venv \
    bluetooth \
    bluez
ok "Dependencias instaladas"

# ─── Selección de funciones ───────────────────────────────────────────────────
section "Selección de funciones"
echo "  Activa o desactiva cada función (Enter para aceptar el valor por defecto):"
echo ""
FEAT_ROTATE=$(ask_yn     "Auto-rotación de pantallas (requiere iio-sensor-proxy)" "s")
FEAT_BRIGHTNESS=$(ask_yn "Brillo automático por sensor de luz ambiental"          "s")
FEAT_BATTERY=$(ask_yn    "Protección de batería (limitar carga máxima)"           "s")
FEAT_DOCK=$(ask_yn       "Apagar/encender pantalla inferior con el teclado"       "s")
FEAT_TOUCHSCREEN=$(ask_yn "Mapeo de touchscreens (corrige táctil de cada pantalla)" "s")

# ─── Configuración de batería ─────────────────────────────────────────────────
BATTERY_LIMIT=80
if [ "$FEAT_BATTERY" = "true" ]; then
    BATTERY_LIMIT=$(ask_val "Límite de carga de la batería (%)" "80")
fi

# Defaults de touchscreen (se sobreescriben si FEAT_TOUCHSCREEN=true)
TOUCH_TOP="04f3:425b"
TOUCH_BOT="04f3:425a"
SWAP_TOUCH=false

# ─── Configuración del teclado ────────────────────────────────────────────────
VID="0b05"
PID="1b2c"
MAC="XX:XX:XX:XX:XX:XX"

if [ "$FEAT_DOCK" = "true" ]; then
    section "Configuración del teclado"
    echo "  Buscando dispositivos ASUS en USB..."
    DETECTED=$(lsusb 2>/dev/null | grep -i "0b05" || true)
    if [ -n "$DETECTED" ]; then
        ok "Encontrado: $DETECTED"
    else
        warn "No se detectó ningún dispositivo ASUS por USB ahora mismo."
    fi
    echo ""
    VID=$(ask_val "Vendor ID del teclado (lsusb | grep -i asus)" "$VID")
    PID=$(ask_val "Product ID del teclado" "$PID")
    echo "  Para obtener la MAC: bluetoothctl devices"
    MAC=$(ask_val "Dirección MAC bluetooth del teclado" "$MAC")
fi

# ─── Pantallas y escala ───────────────────────────────────────────────────────
section "Configuración de pantallas"
DISPLAY_TOP=$(ask_val "Nombre de la pantalla superior" "eDP-1")
DISPLAY_BOT=$(ask_val "Nombre de la pantalla inferior" "eDP-2")
SCALE=$(ask_val       "Factor de escala HiDPI"          "2")

# ─── Configuración de touchscreen ─────────────────────────────────────────────
if [ "$FEAT_TOUCHSCREEN" = "true" ]; then
    section "Configuración de touchscreen"
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
        TOUCH_TOP=$(echo "$DETECTED_TOUCH" | head -1 | cut -f1)
        TOUCH_BOT=$(echo "$DETECTED_TOUCH" | sed -n '2p' | cut -f1)
        echo -e "  Asignación automática:"
        echo -e "    Superior (${DISPLAY_TOP}): ${CYAN}${TOUCH_TOP}${NC}"
        echo -e "    Inferior (${DISPLAY_BOT}): ${CYAN}${TOUCH_BOT}${NC}"
        echo ""
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
    SWAP_TOUCH_YN=$(ask_yn "¿Intercambiar táctiles? (si superior e inferior están al revés)" "n")
    [ "$SWAP_TOUCH_YN" = "true" ] && SWAP_TOUCH=true || SWAP_TOUCH=false
fi

# ─── Copiar archivos ──────────────────────────────────────────────────────────
section "Instalando archivos en $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/core"         "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/modules"      "$INSTALL_DIR/"
cp    "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
ok "Archivos copiados"

# ─── Entorno Python ───────────────────────────────────────────────────────────
section "Configurando entorno Python"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
ok "Entorno Python listo"

# ─── Escribir config.yaml ─────────────────────────────────────────────────────
section "Escribiendo configuración"
cat > "$INSTALL_DIR/config.yaml" << YAML
system:
  username: "$REAL_USER"

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
ok "config.yaml escrito en $INSTALL_DIR/config.yaml"

# ─── Instalar servicio systemd ────────────────────────────────────────────────
section "Instalando servicio systemd"
sed "s/__USERNAME__/$REAL_USER/g" "$SCRIPT_DIR/zenbook-duo.service" \
    > "/etc/systemd/system/$SERVICE_NAME.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# Reiniciar si ya estaba corriendo, arrancar si no
if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl restart "$SERVICE_NAME"
    ok "Servicio reiniciado"
else
    systemctl start "$SERVICE_NAME" || warn "El servicio se iniciará al próximo login gráfico."
    ok "Servicio habilitado"
fi

# ─── Resumen ──────────────────────────────────────────────────────────────────
section "Instalación completada"
echo ""
echo -e "  ${GREEN}✓${NC} Funciones activas:"
[ "$FEAT_ROTATE"       = "true" ] && echo -e "    ${GREEN}•${NC} Auto-rotación de pantallas"
[ "$FEAT_BRIGHTNESS"   = "true" ] && echo -e "    ${GREEN}•${NC} Brillo automático"
[ "$FEAT_BATTERY"      = "true" ] && echo -e "    ${GREEN}•${NC} Protección de batería (límite: $BATTERY_LIMIT%)"
[ "$FEAT_DOCK"         = "true" ] && echo -e "    ${GREEN}•${NC} Control de pantalla con teclado"
[ "$FEAT_TOUCHSCREEN"  = "true" ] && echo -e "    ${GREEN}•${NC} Mapeo de touchscreens"
echo ""
echo -e "  ${CYAN}Comandos útiles:${NC}"
echo -e "    Estado del servicio:  ${BOLD}systemctl status $SERVICE_NAME${NC}"
echo -e "    Ver logs en tiempo real: ${BOLD}journalctl -u $SERVICE_NAME -f${NC}"
echo -e "    Editar configuración: ${BOLD}nano $INSTALL_DIR/config.yaml${NC}"
echo -e "    Aplicar cambios:      ${BOLD}systemctl restart $SERVICE_NAME${NC}"
echo ""
