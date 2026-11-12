# -*- coding: utf-8 -*-
"""
Puente Serial USB (PC <-> ESP32 WROOM-32D)
Conecta el ESP32 conectado por cable USB (puerto COM) con el servidor FastAPI y SQLite.

Funcionalidades:
1. Escanea y detecta automáticamente el puerto COM del ESP32 (115200 baudios).
2. Lee en tiempo real las mediciones del sensor ultrasónico HC-SR04 y lecturas RFID.
3. Actualiza el Dashboard Web y la base de datos SQLite en vivo.
4. Escucha comandos remotos desde la Web o App Móvil (ej. 'Subir Pluma') y envía '1' o '0'
   por el cable USB al ESP32 para activar físicamente el Servomotor SG90, LCD 16x2 y LEDs.
"""

import sys
import time
import re
import threading
import requests
import serial
import serial.tools.list_ports

API_URL = "http://127.0.0.1:8085"
BAUD_RATE = 115200


def buscar_puerto_esp32() -> str:
    """Busca y detecta automáticamente puertos COM asociados a microcontroladores."""
    puertos = list(serial.tools.list_ports.comports())
    if not puertos:
        return ""
    
    print("\n🔍 Puertos COM detectados en tu equipo:")
    candidato = ""
    for p in puertos:
        desc = f"{p.device} - {p.description} ({p.hwid})"
        print(f"   • {desc}")
        # Palabras clave comunes de drivers ESP32 (CP210x, CH340, USB Serial, JTAG)
        desc_upper = p.description.upper()
        if any(chip in desc_upper for chip in ["CP210", "CH340", "USB-SERIAL", "UART", "ESP32", "SERIAL"]):
            candidato = p.device

    # Si hay un candidato específico, usarlo; de lo contrario el primer puerto disponible
    return candidato or puertos[0].device


def hilo_escucha_esp32(ser: serial.Serial, stop_event: threading.Event):
    """Hilo que lee la salida Serial del ESP32 y sincroniza con la API."""
    print("📡 [PUENTE SERIAL] Escuchando datos en vivo del ESP32 por USB...")
    regex_distancia = re.compile(r"DIST:\s*([\d\.]+)", re.IGNORECASE)
    regex_uid = re.compile(r"UID leido:\s*([0-9A-Fa-f\s]+)", re.IGNORECASE)
    regex_salida = re.compile(r"\[SALIDA\].*?\((\d+)\s*cm\)", re.IGNORECASE)

    ultima_distancia = 42.0
    ultimo_uid_pendiente = None

    while not stop_event.is_set():
        try:
            if ser.in_waiting > 0:
                linea = ser.readline().decode("utf-8", errors="replace").strip()
                if not linea:
                    continue
                
                print(f"[ESP32 -> PC] {linea}")

                # 1. Detectar mediciones directas del HC-SR04 (Cajón A-01)
                match_dist = regex_distancia.search(linea)
                if match_dist:
                    try:
                        dist = float(match_dist.group(1))
                        ultima_distancia = dist
                        requests.post(
                            f"{API_URL}/api/esp32/telemetria",
                            json={"distancia_cm": dist, "esp32_ip": "USB_SERIAL_COM"},
                            timeout=1.5
                        )
                    except Exception:
                        pass

                # 2. Detectar Sensor Ultrasónico #2 de Salida Vehicular
                match_salida = regex_salida.search(linea)
                if match_salida:
                    dist_salida = float(match_salida.group(1))
                    print(f"🚗 [PUENTE] Salida vehicular detectada en sensor #2 ({dist_salida} cm)")
                    try:
                        requests.post(
                            f"{API_URL}/api/esp32/validar-acceso",
                            json={
                                "uid": "SALIDA",
                                "distancia_cm": ultima_distancia,
                                "distancia_2_cm": dist_salida,
                                "origen": "SENSOR_SALIDA"
                            },
                            timeout=2.0
                        )
                    except Exception:
                        pass

                # 3. Detectar lecturas de tarjetas RFID físicas
                match_uid = regex_uid.search(linea)
                if match_uid:
                    ultimo_uid_pendiente = match_uid.group(1).strip()
                    print(f"💳 [PUENTE] Tarjeta física detectada en ESP32: {ultimo_uid_pendiente}")
                    continue

                # 4. Sincronizar resultado de validación física con el Dashboard Web y SQLite
                if ultimo_uid_pendiente:
                    if "Lugar actualmente ocupado" in linea:
                        ultima_distancia = 5.0
                        try:
                            requests.post(
                                f"{API_URL}/api/esp32/validar-acceso",
                                json={
                                    "uid": ultimo_uid_pendiente,
                                    "distancia_cm": 5.0,
                                    "origen": "RFID_RC522"
                                },
                                timeout=2.0
                            )
                        except Exception:
                            pass
                        ultimo_uid_pendiente = None
                    elif "ACCESO CONCEDIDO" in linea or "Pluma bloqueada" in linea:
                        if "ACCESO CONCEDIDO" in linea and ultima_distancia <= 10.0:
                            ultima_distancia = 42.0
                        try:
                            requests.post(
                                f"{API_URL}/api/esp32/validar-acceso",
                                json={
                                    "uid": ultimo_uid_pendiente,
                                    "distancia_cm": ultima_distancia,
                                    "origen": "RFID_RC522"
                                },
                                timeout=2.0
                            )
                        except Exception:
                            pass
                        ultimo_uid_pendiente = None

            else:
                time.sleep(0.02)
        except Exception as e:
            if not stop_event.is_set():
                print(f"⚠️ Error en lectura serial: {e}")
            break


def hilo_comandos_remotos(ser: serial.Serial, stop_event: threading.Event):
    """Hilo que consulta comandos pendientes en la web y los envía al ESP32 por USB."""
    while not stop_event.is_set():
        try:
            r = requests.get(f"{API_URL}/api/dashboard", timeout=2.0)
            if r.status_code == 200:
                hw = r.json().get("hardware", {})
                comando = hw.get("comando_pendiente")
                if comando == "ABRIR_PLUMA":
                    print("🌐 [WEB -> ESP32] Comando 'ABRIR_PLUMA' recibido desde la Web/Móvil. Enviando '1' por USB...")
                    ser.write(b"1")
                    ser.flush()
                    # Limpiar comando pendiente
                    requests.post(
                        f"{API_URL}/api/esp32/telemetria",
                        json={"distancia_cm": hw.get("distancia_cm", 42.0), "pluma_estado": "ABIERTA", "esp32_ip": "USB_SERIAL_COM"},
                        timeout=1.5
                    )
        except Exception:
            pass
        time.sleep(0.5)


def main():
    print("=" * 60)
    print("🚗 PUENTE SERIAL USB: ESP32 <-> PLATAFORMA WEB / BASE DE DATOS")
    print("=" * 60)

    # Verificar que el servidor FastAPI esté corriendo
    try:
        r = requests.get(f"{API_URL}/api/dashboard", timeout=2.0)
        print(f"✅ Servidor FastAPI y SQLite detectados en {API_URL}")
    except Exception:
        print("❌ Error: El servidor FastAPI no está corriendo.")
        print("   Inicia primero el servidor con iniciar_sistema.bat")
        sys.exit(1)

    while True:
        puerto = sys.argv[1] if len(sys.argv) > 1 else buscar_puerto_esp32()
        if not puerto:
            print("\n⏳ Esperando a que conectes el ESP32 por cable USB a la computadora...")
            time.sleep(3)
            continue

        print(f"\n🔌 Conectando al ESP32 en el puerto {puerto} a {BAUD_RATE} baudios...")
        try:
            ser = serial.Serial(puerto, BAUD_RATE, timeout=0.1)
            time.sleep(1.5)  # Esperar reinicio tras abrir DTR/RTS
            print(f"🎉 ¡ESP32 conectado por USB en {puerto}! Sincronizando en vivo con http://localhost:8085\n")
            break
        except Exception as e:
            print(f"⚠️ Puerto {puerto} ocupado o no disponible ({e}).")
            print("   (Si tienes abierto el Monitor Serial de Arduino IDE, ciérralo para liberar el puerto). Reintentando en 3s...")
            time.sleep(3)

    stop_event = threading.Event()
    t_rx = threading.Thread(target=hilo_escucha_esp32, args=(ser, stop_event), daemon=True)
    t_tx = threading.Thread(target=hilo_comandos_remotos, args=(ser, stop_event), daemon=True)

    t_rx.start()
    t_tx.start()

    print("ℹ️ Presiona Ctrl+C en cualquier momento para detener el puente.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo puente serial...")
        stop_event.set()
        ser.close()
        print("✅ Puente cerrado.")


if __name__ == "__main__":
    main()
