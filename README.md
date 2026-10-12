# Macro de Dulces – Halloween

Abre con **`iniciar.bat`**.

## Cómo funciona

1. **Tú grabas una vuelta** por la villa (F6). El macro guarda cada tecla que presionas
   (W A S D, Espacio, Q, G, Shift, E) con su tiempo exacto.
2. **Cada E que presionas al grabar = una puerta.** Al reproducir, en ese punto el macro:
   revisa que tengas la calabaza, espera a ver el botón **Knock**, presiona E,
   espera el resultado (dulces o robo), revisa si salió el item raro y sigue la ruta.
3. La ruta se repite en bucle.

### Esquinas y vueltas al final de cada fila
**No gires la cámara.** En Roblox el personaje camina relativo a la cámara: si la cámara
no se mueve, W/A/S/D siempre apuntan a la misma dirección del mapa. Para dar la vuelta
al final de una fila simplemente cambia de tecla (por ejemplo W → D → S). El personaje
gira solo. Así el macro no tiene que mover el mouse, que es lo que más falla.

## Configuración de Roblox (importante)
- Menú → Configuración: **Camera Mode: Classic**, **Movement Mode: Default/Keyboard**,
  **Shift Lock: Off**.
- Usa siempre la misma resolución / pantalla completa (las plantillas dependen de eso).
- No hagas zoom ni gires la cámara mientras grabas o corre el macro.

## Calibración (una sola vez)
Con Roblox en pantalla, pon el mouse encima y presiona la tecla:

| Tecla | Qué capturar |
|---|---|
| **F2** | Acércate a una puerta hasta que aparezca **[E] Knock** y pon el mouse en el centro del botón |
| **F3** | Calabaza **equipada**: mouse en el centro de la casilla 3 (con el borde blanco) |
| **F4** | Calabaza **no equipada**: desequípala y pon el mouse en el centro de la misma casilla |

Luego presiona **Diagnóstico** y cambia a Roblox: verás los puntajes de detección y el
**brillo actual**. Haz un diagnóstico de día y otro de noche, y pon en
"Brillo máximo para noche" un valor entre los dos.

**Item raro:** cuando sepas cómo se ve el aviso o el icono del item, recórtalo de una
captura y guárdalo como `plantillas/raro.png`. El macro pitará, guardará una captura en
`capturas/` y se pausará si lo detecta.

Sin calibrar también funciona, pero a ciegas: presiona E en cada puerta y espera un
tiempo fijo. En ese caso equipa tú la calabaza antes de iniciar.

## Grabar una buena ruta
- **Empieza y termina en el mismo punto exacto** y fácil de repetir. Lo ideal es pegado a
  una esquina o pared (camina contra ella un segundo para "alinearte").
- Repite ese truco en cada esquina: empujar contra un borde o pared corrige el desvío
  acumulado de cada vuelta.
- En cada puerta: párate, presiona **E** una vez y espera a que termine el diálogo antes
  de moverte. El tiempo de espera lo controla el macro, no tu grabación.
- Prueba con **Probar 1 vuelta** antes de dejarlo en bucle.
- Si se desvía mucho tras varias vueltas, activa **Resetear personaje al terminar cada
  vuelta** y graba la ruta empezando desde donde reapareces. Verifica antes que resetear
  no te haga perder dulces en este juego.

## Teclas
| Tecla | Acción |
|---|---|
| F5 | Iniciar / pausar / reanudar |
| F8 | **PARAR** (suelta todas las teclas) |
| F6 | Grabar ruta / terminar grabación |

(No se usa F9 porque en Roblox abre la consola de desarrollador.)

## Protecciones incluidas
- Si Roblox deja de ser la ventana activa, el macro se pausa y suelta todas las teclas.
- **Watchdog:** si tras varias puertas seguidas no ve la interfaz del juego (desconexión,
  muerte, menú abierto), para, pita y guarda una captura.
- Solo presiona la tecla 3 si **ve** que la calabaza está desequipada. Si la interfaz está
  oculta no toca nada, porque presionar 3 otra vez la desequiparía.
- Modo **solo de noche**: de día espera y salta cada ~90 s para que Roblox no te expulse por AFK.
- Esquive G automático opcional, sin frenar el movimiento.
- Aleatoriedad solo en las esperas. El movimiento es exacto para no desviarse.
