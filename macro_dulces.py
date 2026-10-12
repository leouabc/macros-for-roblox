"""
Macro de Dulces - Evento de Halloween (Roblox)

Recorre la villa siguiendo una ruta que TU grabas, toca en cada puerta (E),
mantiene la calabaza equipada, usa el esquive (G) si quieres, puede esperar a
la noche (probabilidad x4) y avisa si aparece el item raro.

Teclas globales:
    F5  Iniciar / Pausar / Reanudar
    F8  PARAR (emergencia)
    F6  Grabar ruta / Terminar grabación
    F2  Capturar plantilla del botón "Knock"   (mouse en el centro del botón)
    F3  Capturar casilla calabaza EQUIPADA     (mouse en el centro de la casilla)
    F4  Capturar casilla calabaza NO equipada  (mouse en el centro de la casilla)
"""

import ctypes
import ctypes.wintypes as wt
import json
import queue
import random
import threading
import time
import traceback
import winsound
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import mss
import numpy as np
from pynput import keyboard

# Coordenadas reales de pantalla aunque Windows tenga escala 125%/150%.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

BASE = Path(__file__).resolve().parent
DIR_PLANTILLAS = BASE / "plantillas"
DIR_RUTAS = BASE / "rutas"
DIR_CAPTURAS = BASE / "capturas"
for _d in (DIR_PLANTILLAS, DIR_RUTAS, DIR_CAPTURAS):
    _d.mkdir(exist_ok=True)
ARCHIVO_CONFIG = BASE / "config.json"
ARCHIVO_META = DIR_PLANTILLAS / "meta.json"

CONFIG_DEFECTO = {
    "ruta": "",
    "tecla_calabaza": "3",
    "espera_knock": 4.0,      # segundos que espera tras tocar la puerta
    "timeout_knock": 2.5,     # segundos buscando el botón Knock antes de presionar E igual
    "umbral_knock": 0.75,
    "esquive_cada": 0.0,      # 0 = no usar G automáticamente
    "modo": "siempre",        # "siempre" | "solo de noche"
    "umbral_noche": 60.0,     # brillo por debajo de esto = noche
    "reset_vuelta": False,
    "espera_respawn": 8.0,
    "vueltas_max": 0,         # 0 = infinito
    "pausa_sin_foco": True,
    "pausar_raro": True,
    "watchdog": 5,            # toques seguidos sin ver la interfaz antes de parar
    "variacion": 15.0,        # % de aleatoriedad en esperas (no en movimiento)
}


# --------------------------------------------------------------------------
# Entrada de teclado/mouse (SendInput con scan codes: Roblox sí los recibe)
# --------------------------------------------------------------------------
user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0002, 0x0008
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _UNION)]


SCAN = {
    "esc": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07,
    "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B, "q": 0x10, "w": 0x11, "e": 0x12,
    "r": 0x13, "enter": 0x1C, "a": 0x1E, "s": 0x1F, "d": 0x20, "g": 0x22,
    "shift": 0x2A, "space": 0x39,
}


def _enviar_tecla(nombre, soltar):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if soltar else 0)
    inp = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, SCAN[nombre], flags, 0, 0))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def key_down(nombre):
    _enviar_tecla(nombre, False)


def key_up(nombre):
    _enviar_tecla(nombre, True)


def titulo_ventana_activa():
    h = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value.strip()


def roblox_activo():
    t = titulo_ventana_activa()
    return t == "Roblox" or (t.startswith("Roblox") and "Studio" not in t)


def posicion_mouse():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def pitido(veces=1, freq=1200):
    def _b():
        for _ in range(veces):
            winsound.Beep(freq, 250)
            time.sleep(0.1)
    threading.Thread(target=_b, daemon=True).start()


# --------------------------------------------------------------------------
# Visión: plantillas y lectura de pantalla
# --------------------------------------------------------------------------
def leer_png(ruta):
    data = np.fromfile(str(ruta), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def guardar_png(ruta, img):
    ok, buf = cv2.imencode(".png", img)
    if ok:
        buf.tofile(str(ruta))


def _a_gris(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _coincidencia(img_gris, plantilla_gris):
    if (img_gris.shape[0] < plantilla_gris.shape[0]
            or img_gris.shape[1] < plantilla_gris.shape[1]):
        return 0.0
    r = cv2.matchTemplate(img_gris, plantilla_gris, cv2.TM_CCOEFF_NORMED)
    return float(np.nan_to_num(r).max())


class Vision:
    TAMANOS = {"knock": (150, 56), "calabaza_si": (64, 64), "calabaza_no": (64, 64)}

    def __init__(self):
        self._local = threading.local()
        self.cargar()

    def _sct(self):
        if not hasattr(self._local, "sct"):
            self._local.sct = mss.mss()
        return self._local.sct

    def pantalla(self):
        return self._sct().monitors[1]

    def capturar(self, left=None, top=None, width=None, height=None):
        mon = self.pantalla()
        if left is None:
            caja = mon
        else:
            caja = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}
        return np.ascontiguousarray(np.array(self._sct().grab(caja))[:, :, :3])

    def cargar(self):
        self.meta = {}
        if ARCHIVO_META.exists():
            try:
                self.meta = json.loads(ARCHIVO_META.read_text(encoding="utf-8"))
            except Exception:
                self.meta = {}
        self.plantillas = {}
        for nombre in ("knock", "calabaza_si", "calabaza_no", "raro"):
            p = DIR_PLANTILLAS / f"{nombre}.png"
            if p.exists():
                img = leer_png(p)
                if img is not None:
                    self.plantillas[nombre] = _a_gris(img)

    def tiene(self, nombre):
        return nombre in self.plantillas

    def guardar_plantilla(self, nombre):
        """Guarda la zona alrededor del mouse como plantilla."""
        w, h = self.TAMANOS[nombre]
        x, y = posicion_mouse()
        img = self.capturar(x - w // 2, y - h // 2, w, h)
        guardar_png(DIR_PLANTILLAS / f"{nombre}.png", img)
        self.meta[nombre] = {"x": x, "y": y, "w": w, "h": h}
        ARCHIVO_META.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")
        self.cargar()
        return x, y

    def puntaje_knock(self):
        """Busca el botón Knock en la zona central de la pantalla."""
        if not self.tiene("knock"):
            return None
        mon = self.pantalla()
        w, h = mon["width"], mon["height"]
        img = self.capturar(mon["left"] + w // 4, mon["top"] + h // 5, w // 2, h * 3 // 5)
        return _coincidencia(_a_gris(img), self.plantillas["knock"])

    def _puntaje_casilla(self, nombre):
        m = self.meta.get(nombre)
        if not m or not self.tiene(nombre):
            return 0.0
        margen = 10
        img = self.capturar(m["x"] - m["w"] // 2 - margen, m["y"] - m["h"] // 2 - margen,
                            m["w"] + 2 * margen, m["h"] + 2 * margen)
        return _coincidencia(_a_gris(img), self.plantillas[nombre])

    def calabaza_calibrada(self):
        return self.tiene("calabaza_si") and self.tiene("calabaza_no")

    def estado_calabaza(self):
        """'si', 'no' o '?' (interfaz oculta, menú abierto, desconectado...)."""
        if not self.calabaza_calibrada():
            return "?", 0.0, 0.0
        si = self._puntaje_casilla("calabaza_si")
        no = self._puntaje_casilla("calabaza_no")
        if si >= 0.80 and si > no + 0.03:
            return "si", si, no
        if no >= 0.80 and no > si + 0.03:
            return "no", si, no
        return "?", si, no

    def brillo(self):
        """Brillo medio de la escena (sin la interfaz de abajo). Menor = más oscuro."""
        img = self.capturar()
        h = img.shape[0]
        zona = img[int(h * 0.10):int(h * 0.70):6, ::6]
        return float(_a_gris(zona).mean())

    def puntaje_raro(self):
        if not self.tiene("raro"):
            return None
        return _coincidencia(_a_gris(self.capturar()), self.plantillas["raro"])

    def guardar_captura(self, motivo):
        nombre = DIR_CAPTURAS / f"{datetime.now():%Y%m%d_%H%M%S}_{motivo}.png"
        guardar_png(nombre, self.capturar())
        return nombre


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------
def nombre_tecla(key):
    if isinstance(key, keyboard.KeyCode):
        vk = key.vk
        if vk is not None and 0x41 <= vk <= 0x5A:
            return chr(vk).lower()
        if vk is not None and 0x30 <= vk <= 0x39:
            return chr(vk)
        return key.char.lower() if key.char else None
    return {
        keyboard.Key.space: "space",
        keyboard.Key.shift: "shift",
        keyboard.Key.shift_l: "shift",
        keyboard.Key.shift_r: "shift",
    }.get(key)


def info_ruta(ruta):
    ev = ruta.get("eventos", [])
    toques = sum(1 for _, tipo, k in ev if k == "e" and tipo == "down")
    dur = ev[-1][0] if ev else 0
    return f"{dur:.1f} s de movimiento, {toques} puertas"


def listar_rutas():
    return sorted(p.name for p in DIR_RUTAS.glob("*.json"))


def cargar_ruta(nombre):
    p = DIR_RUTAS / nombre
    if not nombre or not p.exists():
        return None
    ruta = json.loads(p.read_text(encoding="utf-8"))
    ruta["eventos"].sort(key=lambda e: e[0])
    return ruta


class Grabador:
    TECLAS = {"w", "a", "s", "d", "space", "q", "g", "e", "shift"}

    def __init__(self):
        self.activo = False
        self.eventos = []
        self.t0 = None
        self.abajo = set()
        self.lock = threading.Lock()

    def iniciar(self):
        with self.lock:
            self.activo, self.eventos, self.t0, self.abajo = True, [], None, set()

    def detener(self):
        with self.lock:
            self.activo = False
            if self.t0 is not None:
                t = round(time.perf_counter() - self.t0, 4)
                for k in self.abajo:
                    self.eventos.append([t, "up", k])
            self.abajo = set()
            return list(self.eventos)

    def evento(self, key, tipo):
        if not self.activo:
            return
        nombre = nombre_tecla(key)
        if nombre not in self.TECLAS:
            return
        with self.lock:
            if tipo == "down":
                if nombre in self.abajo:  # autorepetición de Windows
                    return
                self.abajo.add(nombre)
            else:
                if nombre not in self.abajo:
                    return
                self.abajo.discard(nombre)
            ahora = time.perf_counter()
            if self.t0 is None:
                self.t0 = ahora
            self.eventos.append([round(ahora - self.t0, 4), tipo, nombre])


# --------------------------------------------------------------------------
# Motor del macro
# --------------------------------------------------------------------------
class Detenido(Exception):
    pass


class Macro:
    def __init__(self, app):
        self.app = app
        self.vision = app.vision
        self.parar = threading.Event()
        self.pausa = threading.Event()
        self.hilo = None
        self.presionadas = set()
        self.pendientes = {}     # tecla -> momento de soltarla (toques sin bloquear)
        self.desfase = 0.0       # tiempo acumulado en pausas / toques de puerta
        self.estado = "Detenido"
        self.reiniciar_stats()

    def reiniciar_stats(self):
        self.stats = {"vueltas": 0, "toques": 0, "raros": 0, "inicio": None}

    @property
    def corriendo(self):
        return self.hilo is not None and self.hilo.is_alive()

    def log(self, msg):
        self.app.log(msg)

    def iniciar(self, ruta, cfg, una_vuelta=False):
        self.ruta, self.cfg, self.una_vuelta = ruta, cfg, una_vuelta
        self.parar.clear()
        self.pausa.clear()
        self.reiniciar_stats()
        self.hilo = threading.Thread(target=self._correr, daemon=True)
        self.hilo.start()

    def detener(self):
        self.parar.set()

    def alternar_pausa(self):
        if self.pausa.is_set():
            self.pausa.clear()
            self.log("Reanudando...")
        else:
            self.pausa.set()

    # ---- utilidades de tiempo/teclas ----
    def _var(self, v):
        p = self.cfg["variacion"] / 100.0
        return max(0.0, v * (1 + random.uniform(-p, p)))

    def chequear(self):
        if self.parar.is_set():
            raise Detenido
        sin_foco = self.cfg["pausa_sin_foco"] and not roblox_activo()
        if not (self.pausa.is_set() or sin_foco):
            return
        t0 = time.perf_counter()
        guardadas = set(self.presionadas)
        self.soltar_todo()
        anterior = self.estado
        self.estado = "Pausado" if self.pausa.is_set() else "Esperando ventana de Roblox"
        self.log(f"{self.estado} (teclas soltadas).")
        while self.pausa.is_set() or (self.cfg["pausa_sin_foco"] and not roblox_activo()):
            if self.parar.is_set():
                raise Detenido
            nuevo = "Pausado" if self.pausa.is_set() else "Esperando ventana de Roblox"
            if nuevo != self.estado:
                self.estado = nuevo
                self.log(f"{self.estado}.")
            time.sleep(0.1)
        time.sleep(0.4)
        for k in guardadas:
            self.abajo(k)
        self.estado = anterior
        self.desfase += time.perf_counter() - t0

    def esperar(self, seg):
        d0 = self.desfase
        fin = time.perf_counter() + seg
        while True:
            self.chequear()
            self._soltar_pendientes()
            resta = fin + (self.desfase - d0) - time.perf_counter()
            if resta <= 0:
                return
            time.sleep(min(resta, 0.02))

    def abajo(self, k):
        key_down(k)
        self.presionadas.add(k)

    def arriba(self, k):
        key_up(k)
        self.presionadas.discard(k)

    def tocar(self, k, dur=0.06):
        self.abajo(k)
        time.sleep(dur)
        self.arriba(k)

    def tocar_sin_bloquear(self, k):
        key_down(k)
        self.pendientes[k] = time.perf_counter() + 0.06

    def _soltar_pendientes(self):
        ahora = time.perf_counter()
        for k, t in list(self.pendientes.items()):
            if ahora >= t:
                key_up(k)
                del self.pendientes[k]

    def soltar_todo(self):
        for k in list(self.presionadas) + list(self.pendientes):
            key_up(k)
        self.presionadas.clear()
        self.pendientes.clear()

    # ---- acciones del juego ----
    def asegurar_calabaza(self):
        if not self.vision.calabaza_calibrada():
            return True
        for _ in range(3):
            est, _, _ = self.vision.estado_calabaza()
            if est == "si":
                return True
            if est == "?":
                return False  # interfaz no visible: no tocar nada (3 desequiparía)
            self.log("Calabaza no equipada: presionando " + self.cfg["tecla_calabaza"])
            self.tocar(self.cfg["tecla_calabaza"])
            self.esperar(0.5)
        return False

    def tocar_puerta(self):
        self.asegurar_calabaza()
        if self.vision.tiene("knock"):
            fin = time.perf_counter() + self.cfg["timeout_knock"]
            visto = False
            while time.perf_counter() < fin:
                self.chequear()
                if (self.vision.puntaje_knock() or 0) >= self.cfg["umbral_knock"]:
                    visto = True
                    break
                time.sleep(0.08)
            if not visto:
                self.log("No vi el botón Knock aquí (¿ruta desviada?). Presiono E igual.")
        self.tocar("e")
        self.stats["toques"] += 1
        self.esperar(self._var(self.cfg["espera_knock"]))

        # Si la interfaz sigue oculta (cinemática de la puerta), esperar a que vuelva.
        if self.vision.calabaza_calibrada():
            limite = time.perf_counter() + 10
            while self.vision.estado_calabaza()[0] == "?" and time.perf_counter() < limite:
                self.esperar(0.3)

        self._revisar_raro()

        if self.vision.calabaza_calibrada():
            if self.asegurar_calabaza():
                self.fallos_interfaz = 0
            else:
                self.fallos_interfaz += 1
                if self.cfg["watchdog"] and self.fallos_interfaz >= self.cfg["watchdog"]:
                    archivo = self.vision.guardar_captura("watchdog")
                    self.log(f"No veo la interfaz del juego desde hace {self.fallos_interfaz} "
                             f"puertas (¿desconexión o muerte?). Paro. Captura: {archivo.name}")
                    pitido(4, 600)
                    raise Detenido

    def _revisar_raro(self):
        p = self.vision.puntaje_raro()
        if p is not None and p >= 0.80:
            self.stats["raros"] += 1
            archivo = self.vision.guardar_captura("raro")
            self.log(f"¡¡POSIBLE ITEM RARO!! (coincidencia {p:.2f}) Captura: {archivo.name}")
            pitido(6, 1500)
            if self.cfg["pausar_raro"]:
                self.pausa.set()

    def reset_personaje(self):
        self.log("Reseteando personaje para corregir desvío...")
        self.soltar_todo()
        self.tocar("esc")
        self.esperar(0.7)
        self.tocar("r")
        self.esperar(0.7)
        self.tocar("enter")
        self.esperar(self.cfg["espera_respawn"])
        if self.vision.calabaza_calibrada():
            self.asegurar_calabaza()
        else:
            self.tocar(self.cfg["tecla_calabaza"])  # tras reaparecer no hay nada equipado
            self.esperar(0.5)

    def es_noche(self):
        return self.vision.brillo() < self.cfg["umbral_noche"]

    def esperar_noche(self):
        if self.es_noche():
            return
        self.estado = "Esperando la noche"
        self.log("Es de día: espero la noche (salto de vez en cuando para no ser expulsado por AFK).")
        while not self.es_noche():
            self.esperar(self._var(90))
            self.tocar("space")
        self.log("¡Es de noche! Empezando.")

    def _tareas_periodicas(self):
        self._soltar_pendientes()
        cada = self.cfg["esquive_cada"]
        if cada > 0 and time.perf_counter() >= self.prox_esquive:
            self.tocar_sin_bloquear("g")
            self.prox_esquive = time.perf_counter() + self._var(cada)

    def reproducir_ruta(self):
        d0 = self.desfase
        t_inicio = time.perf_counter()
        for t, tipo, k in self.ruta["eventos"]:
            while True:
                self.chequear()
                resta = t_inicio + t + (self.desfase - d0) - time.perf_counter()
                if resta <= 0:
                    break
                self._tareas_periodicas()
                time.sleep(min(resta, 0.005))
            if k == "e":
                if tipo == "down":
                    antes = self.desfase
                    t0 = time.perf_counter()
                    guardadas = set(self.presionadas)
                    self.soltar_todo()
                    self.tocar_puerta()
                    for kk in guardadas:
                        self.abajo(kk)
                    self.desfase = antes + (time.perf_counter() - t0)
                continue
            if tipo == "down":
                self.abajo(k)
            else:
                self.arriba(k)
        self.soltar_todo()

    def _correr(self):
        self.stats["inicio"] = time.time()
        self.fallos_interfaz = 0
        self.prox_esquive = time.perf_counter() + self.cfg["esquive_cada"]
        try:
            self.estado = "Iniciando"
            self.log("Iniciado. Si no estás en Roblox, cambia a la ventana del juego.")
            self.esperar(1.0)
            self.asegurar_calabaza()
            while True:
                if self.cfg["modo"] == "solo de noche":
                    self.esperar_noche()
                self.estado = "Corriendo"
                self.reproducir_ruta()
                self.stats["vueltas"] += 1
                self.log(f"Vuelta {self.stats['vueltas']} completada "
                         f"({self.stats['toques']} puertas en total).")
                if self.una_vuelta or (self.cfg["vueltas_max"]
                                       and self.stats["vueltas"] >= self.cfg["vueltas_max"]):
                    break
                if self.cfg["reset_vuelta"]:
                    self.reset_personaje()
        except Detenido:
            pass
        except Exception:
            self.log("ERROR:\n" + traceback.format_exc())
        finally:
            self.soltar_todo()
            for k in ("w", "a", "s", "d", "space", "shift", "q", "g", "e"):
                key_up(k)
            self.estado = "Detenido"
            self.log("Macro detenido.")


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------
def cargar_config():
    cfg = dict(CONFIG_DEFECTO)
    if ARCHIVO_CONFIG.exists():
        try:
            cfg.update(json.loads(ARCHIVO_CONFIG.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


CAMPOS = [
    # (clave, etiqueta, tipo)
    ("tecla_calabaza", "Tecla de la calabaza", str),
    ("espera_knock", "Espera tras tocar la puerta (s)", float),
    ("timeout_knock", "Buscar botón Knock hasta (s)", float),
    ("umbral_knock", "Sensibilidad Knock (0.5-0.95)", float),
    ("esquive_cada", "Usar esquive G cada (s, 0 = no)", float),
    ("umbral_noche", "Brillo máximo para 'noche'", float),
    ("espera_respawn", "Espera al reaparecer (s)", float),
    ("vueltas_max", "Vueltas máximas (0 = infinito)", int),
    ("watchdog", "Parar tras N puertas sin interfaz (0 = no)", int),
    ("variacion", "Aleatoriedad en esperas (%)", float),
]
CASILLAS = [
    ("pausa_sin_foco", "Pausar si Roblox no es la ventana activa"),
    ("pausar_raro", "Pausar cuando aparezca el item raro"),
    ("reset_vuelta", "Resetear personaje al terminar cada vuelta (corrige desvío)"),
]


class App:
    def __init__(self, root):
        self.root = root
        self.cola = queue.Queue()
        self.cfg = cargar_config()
        self.vision = Vision()
        self.macro = Macro(self)
        self.grabador = Grabador()

        root.title("Macro de Dulces - Halloween")
        root.geometry("620x780")
        root.minsize(560, 640)
        self._construir()
        self._refrescar_rutas()
        self._refrescar_plantillas()

        self.listener = keyboard.Listener(on_press=self._al_presionar, on_release=self._al_soltar)
        self.listener.start()
        root.protocol("WM_DELETE_WINDOW", self._cerrar)
        root.after(150, self._tick)
        self.log("Listo. Lee las instrucciones del README la primera vez.")

    # ---- construcción ----
    def _construir(self):
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        self.lbl_estado = ttk.Label(top, text="Estado: Detenido", font=("Segoe UI", 12, "bold"))
        self.lbl_estado.pack(side="left")
        self.lbl_stats = ttk.Label(top, text="")
        self.lbl_stats.pack(side="right")

        botones = ttk.Frame(self.root)
        botones.pack(fill="x", **pad)
        ttk.Button(botones, text="Iniciar / Pausar (F5)", command=self.f5).pack(side="left", padx=2)
        ttk.Button(botones, text="PARAR (F8)", command=self.f8).pack(side="left", padx=2)
        ttk.Button(botones, text="Grabar ruta (F6)", command=self.f6).pack(side="left", padx=2)
        ttk.Button(botones, text="Probar 1 vuelta", command=lambda: self.iniciar(True)).pack(side="left", padx=2)

        fr = ttk.LabelFrame(self.root, text="Ruta")
        fr.pack(fill="x", **pad)
        self.var_ruta = tk.StringVar(value=self.cfg["ruta"])
        self.cb_ruta = ttk.Combobox(fr, textvariable=self.var_ruta, state="readonly", width=34)
        self.cb_ruta.grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.cb_ruta.bind("<<ComboboxSelected>>", lambda e: self._mostrar_info_ruta())
        ttk.Label(fr, text="Modo:").grid(row=0, column=1, padx=(10, 2))
        self.var_modo = tk.StringVar(value=self.cfg["modo"])
        ttk.Combobox(fr, textvariable=self.var_modo, state="readonly", width=14,
                     values=["siempre", "solo de noche"]).grid(row=0, column=2, padx=4)
        self.lbl_ruta = ttk.Label(fr, text="", foreground="#555")
        self.lbl_ruta.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 4))

        fc = ttk.LabelFrame(self.root, text="Calibración (con Roblox en pantalla, mouse encima y presiona la tecla)")
        fc.pack(fill="x", **pad)
        self.lbl_plantillas = ttk.Label(fc, text="", justify="left")
        self.lbl_plantillas.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(fc, text="Diagnóstico (en 3 s)", command=self.diagnostico).grid(row=0, column=1, padx=6)

        fo = ttk.LabelFrame(self.root, text="Opciones")
        fo.pack(fill="x", **pad)
        self.vars = {}
        for i, (clave, texto, _) in enumerate(CAMPOS):
            ttk.Label(fo, text=texto).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=6, pady=2)
            v = tk.StringVar(value=str(self.cfg[clave]))
            ttk.Entry(fo, textvariable=v, width=8).grid(row=i // 2, column=(i % 2) * 2 + 1, padx=4, pady=2)
            self.vars[clave] = v
        fila = (len(CAMPOS) + 1) // 2
        for j, (clave, texto) in enumerate(CASILLAS):
            v = tk.BooleanVar(value=bool(self.cfg[clave]))
            ttk.Checkbutton(fo, text=texto, variable=v).grid(row=fila + j, column=0, columnspan=4,
                                                             sticky="w", padx=6, pady=1)
            self.vars[clave] = v

        fl = ttk.LabelFrame(self.root, text="Registro")
        fl.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(fl, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(fl, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---- utilidades ----
    def log(self, msg):
        self.cola.put(("log", f"[{datetime.now():%H:%M:%S}] {msg}"))

    def en_ui(self, fn):
        self.cola.put(("call", fn))

    def _tick(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "log":
                    self.txt.configure(state="normal")
                    self.txt.insert("end", dato + "\n")
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
                else:
                    dato()
        except queue.Empty:
            pass
        estado = "Grabando ruta..." if self.grabador.activo else self.macro.estado
        self.lbl_estado.configure(text=f"Estado: {estado}")
        s = self.macro.stats
        if s["inicio"]:
            seg = int(time.time() - s["inicio"])
            self.lbl_stats.configure(text=f"Vueltas {s['vueltas']} | Puertas {s['toques']} | "
                                          f"Raros {s['raros']} | {seg // 3600}:{seg // 60 % 60:02d}:{seg % 60:02d}")
        self.root.after(150, self._tick)

    def _refrescar_rutas(self):
        rutas = listar_rutas()
        self.cb_ruta["values"] = rutas
        if self.var_ruta.get() not in rutas:
            self.var_ruta.set(rutas[-1] if rutas else "")
        self._mostrar_info_ruta()

    def _mostrar_info_ruta(self):
        ruta = cargar_ruta(self.var_ruta.get())
        self.lbl_ruta.configure(text=info_ruta(ruta) if ruta else "Sin ruta. Graba una con F6.")

    def _refrescar_plantillas(self):
        def marca(n):
            return "OK" if self.vision.tiene(n) else "falta"
        self.lbl_plantillas.configure(text=(
            f"F2  Botón Knock: {marca('knock')}\n"
            f"F3  Calabaza equipada: {marca('calabaza_si')}\n"
            f"F4  Calabaza NO equipada: {marca('calabaza_no')}\n"
            f"Item raro (plantillas/raro.png): {marca('raro')}"))

    def _leer_cfg(self):
        try:
            for clave, texto, tipo in CAMPOS:
                valor = self.vars[clave].get().strip()
                self.cfg[clave] = tipo(valor) if tipo is not str else valor.lower()
            for clave, _ in CASILLAS:
                self.cfg[clave] = bool(self.vars[clave].get())
        except ValueError:
            messagebox.showerror("Valor inválido", f"Revisa el campo: {texto}")
            return False
        if self.cfg["tecla_calabaza"] not in SCAN:
            messagebox.showerror("Tecla inválida", "La tecla de la calabaza debe ser un número 0-9.")
            return False
        self.cfg["modo"] = self.var_modo.get()
        self.cfg["ruta"] = self.var_ruta.get()
        ARCHIVO_CONFIG.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return True

    # ---- acciones ----
    def iniciar(self, una_vuelta=False):
        if self.grabador.activo:
            self.log("Termina la grabación (F6) antes de iniciar.")
            return
        if self.macro.corriendo:
            return
        if not self._leer_cfg():
            return
        ruta = cargar_ruta(self.cfg["ruta"])
        if not ruta or not ruta.get("eventos"):
            self.log("Primero graba una ruta con F6.")
            return
        self.vision.cargar()
        if not self.vision.calabaza_calibrada():
            self.log("Aviso: calabaza sin calibrar (F3/F4). Equípala tú antes de iniciar.")
        self.macro.iniciar(ruta, dict(self.cfg), una_vuelta)

    def f5(self):
        if self.macro.corriendo:
            self.macro.alternar_pausa()
        else:
            self.iniciar()

    def f8(self):
        if self.grabador.activo:
            self.f6()
        if self.macro.corriendo:
            self.macro.detener()
            self.log("PARADA solicitada.")

    def f6(self):
        if self.macro.corriendo:
            self.log("Para el macro (F8) antes de grabar.")
            return
        if not self.grabador.activo:
            self.grabador.iniciar()
            self.log("GRABANDO. Haz la vuelta completa en Roblox; presiona E en cada puerta. "
                     "No gires la cámara. F6 para terminar.")
            pitido(1, 900)
            return
        eventos = self.grabador.detener()
        pitido(2, 900)
        if not eventos:
            self.log("Grabación vacía, no se guardó.")
            return
        nombre = f"ruta_{datetime.now():%Y%m%d_%H%M%S}.json"
        ruta = {"version": 1, "creada": datetime.now().isoformat(timespec="seconds"), "eventos": eventos}
        (DIR_RUTAS / nombre).write_text(json.dumps(ruta), encoding="utf-8")
        self.var_ruta.set(nombre)
        self._refrescar_rutas()
        self.log(f"Ruta guardada: {nombre} ({info_ruta(ruta)}).")

    def capturar(self, nombre, texto):
        x, y = self.vision.guardar_plantilla(nombre)
        self._refrescar_plantillas()
        pitido(1, 1000)
        self.log(f"Plantilla '{texto}' guardada en ({x}, {y}).")

    def diagnostico(self):
        self.log("Diagnóstico en 3 s: cambia a Roblox...")

        def _d():
            time.sleep(3)
            v = self.vision
            v.cargar()
            k = v.puntaje_knock()
            est, si, no = v.estado_calabaza()
            self.log(f"Ventana activa: '{titulo_ventana_activa()}' (Roblox: {roblox_activo()})")
            self.log("Knock: " + ("sin plantilla" if k is None else
                                  f"{k:.2f} (visible si >= {self.vars['umbral_knock'].get()})"))
            self.log(f"Calabaza: {est} (equipada {si:.2f} / no equipada {no:.2f})")
            self.log(f"Brillo actual: {v.brillo():.1f} (noche si < {self.vars['umbral_noche'].get()})")
            r = v.puntaje_raro()
            if r is not None:
                self.log(f"Item raro: {r:.2f}")
        threading.Thread(target=_d, daemon=True).start()

    # ---- teclado global ----
    def _al_presionar(self, key):
        self.grabador.evento(key, "down")
        acciones = {
            keyboard.Key.f5: self.f5,
            keyboard.Key.f8: self.f8,
            keyboard.Key.f6: self.f6,
            keyboard.Key.f2: lambda: self.capturar("knock", "botón Knock"),
            keyboard.Key.f3: lambda: self.capturar("calabaza_si", "calabaza equipada"),
            keyboard.Key.f4: lambda: self.capturar("calabaza_no", "calabaza NO equipada"),
        }
        if key in acciones:
            if key in (keyboard.Key.f2, keyboard.Key.f3, keyboard.Key.f4) and self.macro.corriendo:
                return
            self.en_ui(acciones[key])

    def _al_soltar(self, key):
        self.grabador.evento(key, "up")

    def _cerrar(self):
        self.macro.detener()
        self.listener.stop()
        self.root.after(200, self.root.destroy)


if __name__ == "__main__":
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(raiz)
    raiz.mainloop()
