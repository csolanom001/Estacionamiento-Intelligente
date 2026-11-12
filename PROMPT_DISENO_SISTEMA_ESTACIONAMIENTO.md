# Prompt de Ingeniería para el Diseño e Integración del Sistema de Estacionamiento Inteligente con ESP32

**Universidad Autónoma del Estado de México (UAEMéx)**  
**Materia:** Tecnologías Computacionales II  
**Proyecto:** Sistema de Estacionamiento Inteligente con Control de Acceso RFID, Detección Ultrasónica y Plataforma Web/Móvil en Tiempo Real  
**Autor:** Carlos Solano  

---

## 1. Prompt Maestro de Diseño del Sistema (Full-Stack + IoT Embebido)

El siguiente **Prompt Maestro** fue utilizado para especificar los requerimientos técnicos, de hardware, base de datos, comunicación en red e interfaz de usuario (UI/UX) para diseñar y construir el sistema completo de extremo a extremo:

```text
Actúa como un Ingeniero Senior en Sistemas Embebidos IoT y Desarrollador Full-Stack. Necesito diseñar, programar e integrar la capa completa de firmware, base de datos, backend API REST y plataforma web/móvil para un "Sistema de Estacionamiento Inteligente Universitario basado en ESP32", alineado con una arquitectura física real en maqueta.

1. ESPECIFICACIÓN Y MAPEO DE HARDWARE (ESP32 DOIT DEVKIT V1 - 30 PINES):
El sistema físico utiliza un microcontrolador ESP32 conectado por Wi-Fi con el siguiente pinout exacto:
- Lector RFID RC522 (alimentado estrictamente a 3.3V y GND directo al ESP32) en el bus VSPI nativo:
  • SDA (SS): GPIO 5
  • SCK:      GPIO 18
  • MISO:     GPIO 19
  • MOSI:     GPIO 23
  • RST:      GPIO 27
  (Con ganancia máxima de antena RxGain_max = 48 dB y rutina de rearme automático tras cada activación de actuadores).
- Sensor Ultrasónico HC-SR04 #1 (Monitoreo de Ocupación del Cajón A-01):
  • TRIG: GPIO 32 | ECHO: GPIO 35 | Umbral de detección: <= 10 cm = OCUPADO, > 10 cm = LIBRE.
- Sensor Ultrasónico HC-SR04 #2 (Sensor de Salida Vehicular Automática):
  • TRIG: GPIO 33 | ECHO: GPIO 34 | Umbral de detección: <= 10 cm = Vehículo saliendo (apertura automática de pluma con protección anti-aplastamiento hasta que el vehículo termine de cruzar).
- Actuador de Barrera Vehicular (Pluma):
  • Servomotor TowerPro SG90 en GPIO 4 (alimentado con fuente externa de 6V / 4xAA con tierra común GND). Posición cerrada: 0°, posición abierta: 90° durante 3 segundos.
- Pantalla Display LCD 16x2 con interfaz I2C (dirección 0x27):
  • SDA: GPIO 21 | SCL: GPIO 22.
- Indicadores Audiovisuales:
  • LED Verde (Acceso/Salida autorizada): GPIO 13.
  • LED Rojo (Acceso denegado / Cajón ocupado): GPIO 12.
  • Buzzer piezoeléctrico (PWM LEDC compatible con ESP32 Arduino Core 3.x mediante ledcAttach y ledcWriteTone): GPIO 2.

2. LÓGICA DE CONTROL EMBEBIDA Y MODO HÍBRIDO DE RESPALDO (pluma_wifi.ino):
- Cuando se acerca una tarjeta o llavero RFID (13.56 MHz MIFARE), el ESP32 lee el UID en formato hexadecimal y consulta en tiempo real al servidor Backend vía HTTP POST (/api/esp32/validar-acceso) enviando el UID y las distancias de los sensores ultrasónicos.
- Caso 1 (Credencial ACTIVA y Cajón LIBRE): Enciende LED verde, emite doble tono agudo en el buzzer (1400 Hz y 1800 Hz), muestra en el LCD "Bienvenido. / Adelante", abre la pluma a 90° por 3 segundos, la baja a 0°, muestra "Hasta luego." por 2 segundos y restaura el estado del cajón.
- Caso 2 (Credencial ACTIVA pero Cajón OCUPADO <= 10 cm): Impide la apertura de la pluma, muestra en el LCD "Lugar Ocupado / Espere por favor", emite tono de advertencia (500 Hz) y registra el rechazo por cupo lleno.
- Caso 3 (Credencial NO REGISTRADA o BLOQUEADA): Mantiene la pluma cerrada a 0°, enciende LED rojo, emite tono grave de error (400 Hz por 700 ms) y muestra "Acceso Denegado / No autorizado".
- Caso 4 (Detección en Sensor Ultrasónico de Salida <= 10 cm): Abre automáticamente la pluma a 90°, muestra "Buen viaje. / Hasta luego", espera a que el vehículo termine de cruzar el sensor para no bajar la pluma sobre él, cierra a 0°, libera el cajón en la base de datos y registra el evento de SALIDA.
- Respaldo Offline y Serial: Si la red Wi-Fi no responde, el ESP32 valida contra su caché local de UIDs autorizados; además acepta comandos desde el Monitor Serial ('1' para autorizar y '0' para denegar).

3. BASE DE DATOS RELACIONAL SQLITE (database.py):
Diseña una base de datos SQLite normalizada (estacionamiento.db) con integridad referencial que contenga:
- Tabla `usuarios`: id, nombre, rol académico/administrativo, departamento, correo, teléfono, activo, fecha_registro.
- Tabla `vehiculos`: id, usuario_id (FK), placas, marca, modelo, color.
- Tabla `credenciales_rfid`: id, uid (UNIQUE), usuario_id (FK), vehiculo_id (FK), alias_tag, estado ('ACTIVA', 'BLOQUEADA', 'PERDIDA'), fecha_asignacion.
- Tabla `cajones`: id, codigo ('A-01' a 'A-04'), zona, estado ('LIBRE'/'OCUPADO'), distancia_cm, umbral_cm, es_sensor_fisico, vehiculo_actual_placas, ultima_actualizacion.
- Tabla `estado_hardware`: estado en tiempo real del Gemelo Digital (pluma_estado, pluma_angulo, lugar_ocupado, distancia_cm, lcd_linea1, lcd_linea2, led_verde, led_rojo, buzzer_activo, esp32_ip, ultimo_heartbeat, comando_pendiente).
- Tabla `bitacora_accesos`: historial auditable con timestamp, uid_leido, usuario_nombre, rol_usuario, vehiculo_placas, vehiculo_descripcion, tipo_evento ('ENTRADA', 'SALIDA', 'RECHAZO_NO_AUTORIZADO', 'RECHAZO_LUGAR_OCUPADO'), acceso_concedido, motivo, distancia_sensor_cm y origen.

4. BACKEND API REST CON FASTAPI (app.py):
Implementa un servidor asíncrono en Python con FastAPI que incluya:
- GET /api/dashboard: Estado global en tiempo real para la interfaz web y móvil.
- POST /api/esp32/telemetria: Recepción periódica de distancias ultrasónicas desde el ESP32 y entrega de comandos remotos pendientes (ABRIR_PLUMA / CERRAR_PLUMA).
- POST /api/esp32/validar-acceso: Validación de credenciales RFID, control de salida automática y ejecución de tareas asíncronas en segundo plano (_ciclo_cierre_pluma_backend) para sincronizar exactamente el ciclo de apertura de 3 segundos y cierre automático en la animación del Gemelo Digital.
- POST /api/registro-completo, PATCH /api/credenciales/{id}/estado y DELETE /api/credenciales/{id}: CRUD completo para dar de alta usuarios/vehículos/tarjetas, bloquear o activar tokens en vivo y eliminar registros individuales sin afectar otras tarjetas del mismo usuario.
- GET /api/bitacora/exportar: Exportación directa del historial de accesos y salidas a archivo CSV compatible con Excel (UTF-8 con BOM).

5. PLATAFORMA WEB RESPONSIVE, APP MÓVIL PWA Y GEMELO DIGITAL (index.html):
Construye un Dashboard moderno (Tailwind CSS + JavaScript Vanilla) con soporte de Progressive Web App (PWA) instalable en celular y vista conmutable Escritorio/Móvil que incluya:
- Gemelo Digital interactivo del ESP32: Pantalla LCD 16x2 virtual con la misma tipografía matricial, brazo animado de la pluma en CSS (0° a 90°) que sube y baja automáticamente en sincronía con el servomotor físico, indicadores LED verde/rojo brillantes, síntesis de audio en el navegador (Web Audio API) que reproduce las frecuencias reales del buzzer y control manual de apertura/cierre remoto.
- Mapa de cajones en tiempo real, panel de gestión de usuarios y tarjetas RFID con buscador instantáneo, bitácora auditable en vivo y documentación visual del pinout del hardware.
```

---

## 2. Prompts Secundarios de Refinamiento y Puesta a Punto en Hardware Real

Durante la fase de integración física en protoboard y armado de la maqueta, se emplearon los siguientes prompts específicos para resolver retos reales de ingeniería electrónica y red:

### 2.1 Prompt de Diagnóstico y Estabilización Eléctrica del Lector RFID RC522
```text
Ayúdame a diagnosticar y estabilizar la comunicación SPI entre un ESP32 (30 pines DOIT DevKit V1) y un módulo lector RFID RC522 (placa HW-126 con chip versión 0xB2). Separa la alimentación de 3.3V y GND del lector conectándolos directamente a los pines 3V3 y GND del ESP32 para aislarlo del ruido eléctrico del riel de 5V (VIN) que alimenta el display LCD y los sensores ultrasónicos, y agrega una función rearmarLectorRFID() con ganancia máxima de antena (RxGain_max) después de cada ciclo del servomotor y buzzer.
```

### 2.2 Prompt de Integración del Segundo Sensor Ultrasónico para Salida Automática
```text
Modifica el firmware del ESP32 (pluma_wifi.ino) y el backend FastAPI (app.py) para integrar un segundo sensor ultrasónico HC-SR04 conectado en los pines TRIG = GPIO 33 y ECHO = GPIO 34 como "Sensor de Salida Vehicular". Cuando un vehículo se acerque o se detenga frente a este segundo sensor (<= 10 cm), el sistema debe levantar automáticamente la pluma a 90°, mostrar "Buen viaje. / Hasta luego" en el LCD, esperar a que el vehículo termine de cruzar para evitar bajar la pluma sobre él, cerrarla a 0°, liberar el cajón en la base de datos y registrar el evento como "SALIDA" en la bitácora web.
```

### 2.3 Prompt de Sincronización de Animación del Gemelo Digital y Red Móvil (Hotspot)
```text
Sincroniza la animación de la pluma en el Dashboard del Administrador para que, cuando el acceso o la salida sean activados físicamente desde el lector RFID o el sensor ultrasónico del ESP32, la pluma virtual suba a 90° en la página web y baje sola automáticamente a 0° tras los 3 segundos de apertura, igualando el ciclo físico del servomotor SG90. Asimismo, configura la conexión Wi-Fi del ESP32 para operar sobre el Hotspot móvil (2.4 GHz) apuntando a la dirección IPv4 local del servidor FastAPI con respaldo automático en caché local.
```
