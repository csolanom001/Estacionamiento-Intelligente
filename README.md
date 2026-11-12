# 🚗 Sistema de Estacionamiento Inteligente con ESP32 (IoT + FastAPI + Gemelo Digital)

Sistema integral de control de acceso vehicular y monitoreo de estacionamiento en tiempo real basado en el microcontrolador **ESP32 (DOIT ESP32 DevKit V1 / WROOM-32D)**, lector **RFID RC522 (13.56 MHz)**, doble **sensor ultrasónico HC-SR04** (detección de ocupación de cajón y apertura automática en salida), **servomotor SG90**, **display LCD 16x2 I2C** y una **Plataforma Web con Gemelo Digital, PWA Móvil y Base de Datos SQLite (FastAPI)**.

---

## ✨ Características Principales

- **Control de Acceso RFID RC522 (Bus VSPI a 3.3V):**
  - Validación de tarjetas y llaveros MIFARE 13.56 MHz en línea (contra SQLite vía API REST) y fuera de línea (caché local en memoria del ESP32).
  - Rearmado activo de antena (`RxGain_max` a 48 dB) para operación continua sin bloqueos por ruido electromagnético del servomotor.
- **Doble Sensor Ultrasónico HC-SR04:**
  - **Sensor #1 (Cajón `A-01` — `TRIG: GPIO 32`, `ECHO: GPIO 35`):** Detecta en tiempo real si el cajón está `LIBRE` ($> 10\text{ cm}$) u `OCUPADO` ($\le 10\text{ cm}$) y bloquea el acceso si no hay cupo aunque la tarjeta sea válida.
  - **Sensor #2 (Salida Automática — `TRIG: GPIO 33`, `ECHO: GPIO 34`):** Detecta cuando un vehículo se aproxima a la salida ($\le 10\text{ cm}$), levanta la pluma automáticamente a $90^\circ$, muestra `"Buen viaje. / Hasta luego"` en el LCD, espera a que el vehículo cruce y cierra la barrera registrando el evento `SALIDA` en la bitácora.
- **Actuadores e Indicadores Físicos:**
  - **Servomotor SG90 (`GPIO 4`):** Control de barrera vehicular ($0^\circ$ cerrada / $90^\circ$ abierta) mediante tren de pulsos nativo.
  - **Display LCD 16x2 I2C (`0x27`, `SDA: GPIO 21`, `SCL: GPIO 22`):** Mensajes de estado en tiempo real.
  - **Indicadores Audiovisuales:** LED Verde (`GPIO 13`), LED Rojo (`GPIO 12`) y Buzzer pasivo PWM (`GPIO 2`).
- **Plataforma Web, Gemelo Digital y Base de Datos SQLite (`FastAPI`):**
  - Monitoreo en vivo (sincronización cada 1 segundo) del LCD 16x2, posición de la pluma, LEDs, distancia ultrasónica y mapa de cajones.
  - Administración CRUD de usuarios, vehículos (placas, marca, modelo, color) y tarjetas RFID (`ACTIVA` / `BLOQUEADA`).
  - Bitácora histórica auditable con exportación directa a Excel (`.csv`).
  - Doble vía de comunicación: **Wi-Fi HTTP REST** (`pluma_wifi.ino`) y **Puente Serial USB** (`puente_serial_esp32.py`).

---

## 🔌 Mapa de Pines (Pinout ESP32 30 Pines)

| Periférico | Pin del Módulo | Pin ESP32 (GPIO) | Alimentación y Notas |
| :--- | :--- | :--- | :--- |
| **RFID RC522 (VSPI)** | `SDA (SS)` / `SCK` / `MOSI` / `MISO` / `RST` | `GPIO 5` / `18` / `23` / `19` / `27` | **3.3V exclusivo** y `GND` directo al ESP32 |
| **HC-SR04 #1 (Cajón A-01)** | `TRIG` / `ECHO` | `GPIO 32` / `GPIO 35` | `5V` (`VIN`), umbral $\le 10\text{ cm}$ |
| **HC-SR04 #2 (Salida)** | `TRIG` / `ECHO` | `GPIO 33` / `GPIO 34` | `5V` (`VIN`), apertura automática $\le 10\text{ cm}$ |
| **Servomotor SG90** | Señal PWM | `GPIO 4` | Fuente externa `5V–6V` con `GND` común |
| **Display LCD 16x2 I2C** | `SDA` / `SCL` (`0x27`) | `GPIO 21` / `GPIO 22` | `5V` (`VIN`) y `GND` |
| **Indicadores** | LED Verde / LED Rojo / Buzzer | `GPIO 13` / `GPIO 12` / `GPIO 2` | Salidas digitales / PWM (`LEDC`) |

---

## 📂 Estructura del Proyecto

```text
├── iniciar_sistema.bat                       # Lanzador automático del servidor FastAPI (puerto 8085)
├── DOCUMENTO_TECNICO_PROYECTO_FINAL.md       # Documentación técnica completa del sistema
├── PROMPT_DISENO_SISTEMA_ESTACIONAMIENTO.md  # Prompt maestro de ingeniería del sistema
├── pluma_wifi/
│   └── pluma_wifi.ino                        # Firmware principal ESP32 con Wi-Fi REST + Caché Offline + 2 HC-SR04
├── pluma/
│   └── pluma.ino                             # Firmware autónomo ESP32 (sin Wi-Fi) con 2 HC-SR04
├── test_rfid/
│   └── test_rfid.ino                         # Diagnóstico de hardware y lectura de UIDs RC522
└── plataforma_web/
    ├── app.py                                # Servidor Backend FastAPI y lógica del Gemelo Digital
    ├── database.py                           # Esquema relacional SQLite (6 tablas) y datos semilla
    ├── puente_serial_esp32.py                # Puente bidireccional por cable USB Serial (COM)
    ├── requirements.txt                      # Dependencias de Python
    └── static/
        ├── index.html                        # Interfaz Web Responsiva + Simulador + Vista App Móvil
        └── manifest.json                     # Manifiesto Progressive Web App (PWA)
```

---

## 🚀 Instalación y Ejecución Rápida

### 1. Instalar dependencias de Python
```bash
cd plataforma_web
pip install -r requirements.txt
```

### 2. Iniciar la Plataforma Web y Base de Datos
En Windows, haz doble clic en **`iniciar_sistema.bat`** o ejecuta manualmente:
```bash
cd plataforma_web
python -m uvicorn app:app --host 0.0.0.0 --port 8085 --reload
```
- **Dashboard Web y Gemelo Digital:** `http://localhost:8085`
- **Documentación Interactiva API (Swagger UI):** `http://localhost:8085/docs`

### 3. Cargar el Firmware en el ESP32
1. Abre `pluma_wifi/pluma_wifi.ino` en **Arduino IDE** (con el core **esp32 by Espressif Systems v3.x** y las librerías `MFRC522` y `LiquidCrystal I2C`).
2. Configura tu red Wi-Fi (`WIFI_SSID`, `WIFI_PASSWORD`) y la IP de tu computadora (`API_BASE_URL = "http://<TU_IP>:8085"`).
3. Sube el sketch a tu placa **DOIT ESP32 DEVKIT V1**.
