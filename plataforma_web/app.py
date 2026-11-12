# -*- coding: utf-8 -*-
"""
Backend API REST (FastAPI) - Sistema de Estacionamiento Inteligente con ESP32
Proporciona:
1. API REST para el microcontrolador ESP32 WROOM-32D (validación RFID, telemetría HC-SR04, sincronización offline).
2. Gestión de usuarios, vehículos, placas y credenciales RFID (UIDs).
3. Monitoreo en tiempo real del aforo, cajones y periféricos (LCD 16x2, Servo SG90, LEDs, Buzzer).
4. Bitácora histórica con exportación a CSV y estadísticas en tiempo real.
"""

import asyncio
import csv
import io
import os
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import init_db, get_connection, normalizar_uid

# Inicializar base de datos al arrancar
init_db()

app = FastAPI(
    title="API Sistema de Estacionamiento Inteligente ESP32 - UAEMEX",
    description=(
        "Capa de software y base de datos para el control de acceso vehicular con ESP32 WROOM-32D, "
        "lector RFID RC522 (VSPI), sensor ultrasónico HC-SR04, servomotor SG90 y display LCD 16x2 I2C."
    ),
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# =====================================================================
# MODELOS DE DATOS (PYDANTIC)
# =====================================================================

class RegistroCompletoRequest(BaseModel):
    nombre: str = Field(..., min_length=3, examples=["Dr. Alejandro Morales"])
    rol: str = Field(default="Docente Tiempo Completo", examples=["Docente Tiempo Completo"])
    departamento: str = Field(default="Facultad de Ingeniería", examples=["Facultad de Ingeniería"])
    correo: Optional[str] = Field(default="", examples=["amorales@uaemex.mx"])
    telefono: Optional[str] = Field(default="", examples=["722-123-4567"])
    placas: str = Field(..., min_length=3, examples=["UAM-991-A"])
    marca: str = Field(..., min_length=2, examples=["Toyota"])
    modelo: str = Field(..., min_length=1, examples=["Prius"])
    color: str = Field(default="Blanco", examples=["Blanco"])
    uid_rfid: str = Field(..., min_length=4, examples=["B4 91 2C 08"])
    alias_tag: str = Field(default="Tarjeta Blanca MIFARE", examples=["Tarjeta Docente #4"])


class EstadoCredencialRequest(BaseModel):
    estado: str = Field(..., pattern="^(ACTIVA|BLOQUEADA|PERDIDA)$")


class ValidacionESP32Request(BaseModel):
    uid: str = Field(..., description="UID de 4 bytes en HEX (ej. '83 CF 7A 28') o comando serial ('1' o '0')")
    distancia_cm: Optional[float] = Field(default=None, description="Distancia medida por el HC-SR04 #1 (Cajón A-01) en cm")
    distancia_2_cm: Optional[float] = Field(default=None, description="Distancia medida por el HC-SR04 #2 (Cajón A-02) en cm")
    origen: str = Field(default="RFID_RC522", description="RFID_RC522, SERIAL_MONITOR o SIMULADOR_ESP32")


class TelemetriaESP32Request(BaseModel):
    distancia_cm: float = Field(..., description="Distancia actual medida por HC-SR04 #1 (Cajón A-01, GPIO 32/35)")
    distancia_2_cm: Optional[float] = Field(default=None, description="Distancia actual medida por HC-SR04 #2 (Cajón A-02, GPIO 33/34)")
    pluma_estado: Optional[str] = Field(default=None, description="CERRADA o ABIERTA")
    lector_rfid_operativo: Optional[bool] = Field(default=None)
    esp32_ip: Optional[str] = Field(default="192.168.1.150")


class ControlPlumaRequest(BaseModel):
    accion: str = Field(..., pattern="^(ABRIR|CERRAR)$")
    motivo: Optional[str] = Field(default="Control manual desde Dashboard Web")


class ActualizarCajonRequest(BaseModel):
    distancia_cm: Optional[float] = None
    estado: Optional[str] = None
    vehiculo_actual_placas: Optional[str] = None


# =====================================================================
# RUTAS FRONTEND (DASHBOARD WEB Y PWA MÓVIL)
# =====================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Cargando interfaz...</h1>")


# =====================================================================
# ENDPOINTS DE DASHBOARD Y MONITOREO EN TIEMPO REAL
# =====================================================================

@app.get("/api/dashboard")
async def obtener_dashboard():
    """
    Devuelve el estado global del estacionamiento en tiempo real:
    - Resumen de aforo (total, libres, ocupados, porcentaje)
    - Estado en vivo del hardware ESP32 (HC-SR04, Servo SG90, LCD 16x2, LEDs, Buzzer)
    - Estado de todos los cajones
    - Directorio de usuarios, vehículos y credenciales RFID
    - Bitácora reciente de accesos y estadísticas
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Cajones
    cursor.execute("SELECT * FROM cajones ORDER BY codigo ASC;")
    cajones = [dict(r) for r in cursor.fetchall()]

    total_cajones = len(cajones)
    ocupados = sum(1 for c in cajones if c["estado"] == "OCUPADO")
    libres = total_cajones - ocupados

    # 2. Estado del Hardware ESP32
    cursor.execute("SELECT * FROM estado_hardware WHERE id = 1;")
    hw_row = cursor.fetchone()
    hardware = dict(hw_row) if hw_row else {}

    # 3. Credenciales + Usuarios + Vehículos (JOIN)
    cursor.execute("""
        SELECT
            c.id AS credencial_id,
            c.uid,
            c.alias_tag,
            c.estado AS estado_credencial,
            c.fecha_asignacion,
            u.id AS usuario_id,
            u.nombre AS usuario_nombre,
            u.rol,
            u.departamento,
            u.correo,
            u.telefono,
            v.id AS vehiculo_id,
            v.placas,
            v.marca,
            v.modelo,
            v.color
        FROM credenciales_rfid c
        JOIN usuarios u ON c.usuario_id = u.id
        LEFT JOIN vehiculos v ON c.vehiculo_id = v.id
        ORDER BY c.id DESC;
    """)
    registros = [dict(r) for r in cursor.fetchall()]

    # 4. Bitácora reciente
    cursor.execute("SELECT * FROM bitacora_accesos ORDER BY id DESC LIMIT 40;")
    bitacora = [dict(r) for r in cursor.fetchall()]

    # 5. Estadísticas de bitácora
    cursor.execute("""
        SELECT
            COUNT(*) AS total_eventos,
            SUM(CASE WHEN acceso_concedido = 1 THEN 1 ELSE 0 END) AS accesos_autorizados,
            SUM(CASE WHEN tipo_evento = 'RECHAZO_NO_AUTORIZADO' THEN 1 ELSE 0 END) AS rechazos_uid,
            SUM(CASE WHEN tipo_evento = 'RECHAZO_LUGAR_OCUPADO' THEN 1 ELSE 0 END) AS rechazos_ocupado
        FROM bitacora_accesos;
    """)
    stats_row = dict(cursor.fetchone())

    conn.close()

    return {
        "aforo": {
            "capacidad_total": total_cajones,
            "lugares_ocupados": ocupados,
            "lugares_libres": libres,
            "porcentaje_ocupacion": round((ocupados / total_cajones) * 100, 1) if total_cajones > 0 else 0,
            "cajon_prototipo_ocupado": bool(hardware.get("lugar_ocupado", 0)),
            "distancia_ultrasonico_cm": hardware.get("distancia_cm", 999.0),
        },
        "hardware": hardware,
        "cajones": cajones,
        "registros": registros,
        "bitacora": bitacora,
        "estadisticas": {
            "total_eventos": stats_row["total_eventos"] or 0,
            "accesos_autorizados": stats_row["accesos_autorizados"] or 0,
            "rechazos_uid": stats_row["rechazos_uid"] or 0,
            "rechazos_ocupado": stats_row["rechazos_ocupado"] or 0,
            "credenciales_activas": sum(1 for r in registros if r["estado_credencial"] == "ACTIVA"),
            "total_credenciales": len(registros),
        }
    }


# =====================================================================
# ENDPOINTS DE GESTIÓN DE USUARIOS, VEHÍCULOS Y CREDENCIALES RFID
# =====================================================================

@app.post("/api/registro-completo")
async def crear_registro_completo(datos: RegistroCompletoRequest):
    """
    Registra un nuevo usuario, su vehículo (placas, marca, modelo, color) y su tarjeta/tag RFID.
    """
    uid_norm = normalizar_uid(datos.uid_rfid)
    placas_norm = datos.placas.strip().upper()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Verificar duplicados de UID o Placas
        cursor.execute("SELECT id FROM credenciales_rfid WHERE uid = ?;", (uid_norm,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"El UID RFID '{uid_norm}' ya está registrado en el sistema.")

        cursor.execute("SELECT id FROM vehiculos WHERE placas = ?;", (placas_norm,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Las placas '{placas_norm}' ya están registradas.")

        # 1. Insertar usuario
        cursor.execute("""
            INSERT INTO usuarios (nombre, rol, departamento, correo, telefono, activo, fecha_registro)
            VALUES (?, ?, ?, ?, ?, 1, ?);
        """, (
            datos.nombre.strip(),
            datos.rol.strip(),
            datos.departamento.strip(),
            (datos.correo or "").strip(),
            (datos.telefono or "").strip(),
            ahora
        ))
        usuario_id = cursor.lastrowid

        # 2. Insertar vehículo
        cursor.execute("""
            INSERT INTO vehiculos (usuario_id, placas, marca, modelo, color)
            VALUES (?, ?, ?, ?, ?);
        """, (
            usuario_id,
            placas_norm,
            datos.marca.strip(),
            datos.modelo.strip(),
            datos.color.strip()
        ))
        vehiculo_id = cursor.lastrowid

        # 3. Insertar credencial RFID
        cursor.execute("""
            INSERT INTO credenciales_rfid (uid, usuario_id, vehiculo_id, alias_tag, estado, fecha_asignacion)
            VALUES (?, ?, ?, ?, 'ACTIVA', ?);
        """, (
            uid_norm,
            usuario_id,
            vehiculo_id,
            datos.alias_tag.strip(),
            ahora
        ))
        credencial_id = cursor.lastrowid

        conn.commit()
        return {
            "mensaje": "Usuario, vehículo y credencial RFID registrados correctamente.",
            "credencial_id": credencial_id,
            "uid": uid_norm,
            "usuario": datos.nombre.strip(),
            "placas": placas_norm
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar el registro: {str(e)}")
    finally:
        conn.close()


@app.patch("/api/credenciales/{credencial_id}/estado")
async def cambiar_estado_credencial(credencial_id: int, req: EstadoCredencialRequest):
    """Permite activar o bloquear una tarjeta RFID inmediatamente."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM credenciales_rfid WHERE id = ?;", (credencial_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Credencial no encontrada.")

    cursor.execute(
        "UPDATE credenciales_rfid SET estado = ? WHERE id = ?;",
        (req.estado, credencial_id)
    )
    conn.commit()
    conn.close()
    return {"mensaje": f"Estado de credencial {row['uid']} actualizado a {req.estado}."}


@app.delete("/api/credenciales/{credencial_id}")
async def eliminar_registro(credencial_id: int):
    """Elimina una credencial específica (y su usuario/vehículo solo si no tiene otras credenciales asociadas)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT usuario_id, vehiculo_id, uid FROM credenciales_rfid WHERE id = ?;", (credencial_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Registro no encontrado.")

    usuario_id = row["usuario_id"]
    vehiculo_id = row["vehiculo_id"]
    uid_borrado = row["uid"]

    # Eliminar primero únicamente la credencial seleccionada
    cursor.execute("DELETE FROM credenciales_rfid WHERE id = ?;", (credencial_id,))

    # Verificar si el usuario tiene alguna otra credencial activa/registrada
    cursor.execute("SELECT COUNT(*) AS restantes FROM credenciales_rfid WHERE usuario_id = ?;", (usuario_id,))
    restantes = cursor.fetchone()["restantes"]
    if restantes == 0:
        if vehiculo_id:
            cursor.execute("DELETE FROM vehiculos WHERE id = ?;", (vehiculo_id,))
        cursor.execute("DELETE FROM usuarios WHERE id = ?;", (usuario_id,))

    conn.commit()
    conn.close()
    return {"mensaje": f"Registro con UID {uid_borrado} eliminado correctamente."}


# =====================================================================
# ENDPOINTS DE CONEXIÓN CON EL ESP32 (API REST / WI-FI Y SIMULADOR)
# =====================================================================

@app.get("/api/esp32/uids-autorizados")
async def obtener_uids_para_esp32():
    """
    Devuelve la lista compacta de UIDs activos para que el ESP32 pueda sincronizar
    su caché local al iniciar o periódicamente por Wi-Fi.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.uid, u.nombre, v.placas
        FROM credenciales_rfid c
        JOIN usuarios u ON c.usuario_id = u.id
        LEFT JOIN vehiculos v ON c.vehiculo_id = v.id
        WHERE c.estado = 'ACTIVA';
    """)
    filas = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {
        "total": len(filas),
        "uids": [f["uid"] for f in filas],
        "detalle": filas
    }


def _obtener_estado_cajones_fisicos(cursor):
    """Devuelve (c1_ocup, lcd_linea1) para el cajón físico A-01 monitoreado por el Sensor HC-SR04 #1 (GPIO 32/35)."""
    cursor.execute("SELECT estado, distancia_cm FROM cajones WHERE codigo = 'A-01';")
    fila = cursor.fetchone()
    c1_ocup = (fila["estado"] == "OCUPADO") if fila else False
    lcd_l1 = "Lugar: OCUPADO" if c1_ocup else "Lugar: LIBRE"
    return c1_ocup, lcd_l1


async def _ciclo_cierre_pluma_backend():
    """
    Replica en el Gemelo Digital de la página web el ciclo exacto del ESP32 físico:
    1. Mantiene la pluma ABIERTA (90°) y LED verde por 3.2 segundos.
    2. Baja la pluma a CERRADA (0°), apaga el LED verde y muestra 'Hasta luego.' por 1.8 segundos.
    3. Restaura la pantalla de inicio ('Lugar: LIBRE/OCUPADO' / 'Acerque tarjeta').
    """
    await asyncio.sleep(3.2)
    ahora1 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE estado_hardware
        SET pluma_estado = 'CERRADA',
            pluma_angulo = 0,
            lcd_linea1 = 'Hasta luego.',
            lcd_linea2 = '',
            led_verde = 0,
            led_rojo = 0,
            buzzer_activo = 0,
            ultimo_heartbeat = ?
        WHERE id = 1;
    """, (ahora1,))
    conn.commit()
    conn.close()

    await asyncio.sleep(1.8)
    ahora2 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()
    c1_ocup, lcd_l1 = _obtener_estado_cajones_fisicos(cursor)
    cursor.execute("""
        UPDATE estado_hardware
        SET pluma_estado = 'CERRADA',
            pluma_angulo = 0,
            lugar_ocupado = ?,
            lcd_linea1 = ?,
            lcd_linea2 = 'Acerque tarjeta',
            led_verde = 0,
            led_rojo = 0,
            buzzer_activo = 0,
            ultimo_heartbeat = ?
        WHERE id = 1;
    """, (1 if c1_ocup else 0, lcd_l1, ahora2))
    conn.commit()
    conn.close()


async def _ciclo_reposo_rechazo_backend():
    """Restaura LED rojo y pantalla LCD del Gemelo Digital tras 2 segundos de mostrar un rechazo."""
    await asyncio.sleep(2.0)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()
    c1_ocup, lcd_l1 = _obtener_estado_cajones_fisicos(cursor)
    cursor.execute("""
        UPDATE estado_hardware
        SET pluma_estado = 'CERRADA',
            pluma_angulo = 0,
            lugar_ocupado = ?,
            lcd_linea1 = ?,
            lcd_linea2 = 'Acerque tarjeta',
            led_verde = 0,
            led_rojo = 0,
            buzzer_activo = 0,
            ultimo_heartbeat = ?
        WHERE id = 1;
    """, (1 if c1_ocup else 0, lcd_l1, ahora))
    conn.commit()
    conn.close()


@app.post("/api/esp32/telemetria")
async def recibir_telemetria_esp32(req: TelemetriaESP32Request):
    """
    Endpoint invocado por el ESP32 para reportar la lectura en tiempo real de los sensores HC-SR04:
    - Sensor 1 (Cajón A-01): Trig GPIO 32, Echo GPIO 35
    - Sensor 2 (Salida):     Trig GPIO 33, Echo GPIO 34
    Umbral de detección: <= 10 cm -> OCUPADO, > 10 cm -> LIBRE.
    También retorna cualquier comando remoto pendiente (ej. abrir pluma desde la web).
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ocupado_1 = 1 if (0 < req.distancia_cm <= 10.0) else 0
    estado_texto_1 = "OCUPADO" if ocupado_1 else "LIBRE"

    conn = get_connection()
    cursor = conn.cursor()

    # Sincronizar el cajón físico A-01 (Sensor #1)
    cursor.execute("""
        UPDATE cajones
        SET estado = ?,
            distancia_cm = ?,
            es_sensor_fisico = 1,
            vehiculo_actual_placas = CASE WHEN ? = 0 THEN NULL ELSE vehiculo_actual_placas END,
            ultima_actualizacion = ?
        WHERE codigo = 'A-01';
    """, (estado_texto_1, round(req.distancia_cm, 1), ocupado_1, ahora))

    c1_ocup, lcd_l1 = _obtener_estado_cajones_fisicos(cursor)
    lcd_l2 = "Acerque tarjeta"

    # Leer si hay algún comando remoto pendiente para el ESP32
    cursor.execute("SELECT comando_pendiente, pluma_estado, pluma_angulo FROM estado_hardware WHERE id = 1;")
    hw_actual = cursor.fetchone()
    comando = hw_actual["comando_pendiente"] if hw_actual else None

    if comando == "ABRIR_PLUMA":
        pluma_estado = "ABIERTA"
        pluma_angulo = 90
        lcd_l1 = "Bienvenido."
        lcd_l2 = "Adelante"
    else:
        pluma_estado = req.pluma_estado or "CERRADA"
        pluma_angulo = 90 if pluma_estado == "ABIERTA" else 0

    # Actualizar estado del hardware (limpiando el comando pendiente una vez entregado)
    cursor.execute("""
        UPDATE estado_hardware
        SET lugar_ocupado = ?,
            distancia_cm = ?,
            lcd_linea1 = ?,
            lcd_linea2 = ?,
            pluma_estado = ?,
            pluma_angulo = ?,
            led_verde = ?,
            led_rojo = 0,
            buzzer_activo = 0,
            lector_rfid_operativo = COALESCE(?, lector_rfid_operativo),
            esp32_ip = COALESCE(?, esp32_ip),
            ultimo_heartbeat = ?,
            comando_pendiente = NULL
        WHERE id = 1;
    """, (
        1 if c1_ocup else 0,
        round(req.distancia_cm, 1),
        lcd_l1,
        lcd_l2,
        pluma_estado,
        pluma_angulo,
        1 if pluma_estado == "ABIERTA" else 0,
        1 if req.lector_rfid_operativo else (0 if req.lector_rfid_operativo is False else None),
        req.esp32_ip,
        ahora
    ))

    conn.commit()
    conn.close()

    if comando == "ABRIR_PLUMA":
        asyncio.create_task(_ciclo_cierre_pluma_backend())

    return {
        "ok": True,
        "lugar_ocupado": bool(c1_ocup),
        "estado_cajon": "OCUPADO" if c1_ocup else "LIBRE",
        "distancia_cm": round(req.distancia_cm, 1),
        "distancia_2_cm": round(req.distancia_2_cm, 1) if req.distancia_2_cm is not None else None,
        "lcd_linea1": lcd_l1,
        "lcd_linea2": lcd_l2,
        "comando_pendiente": comando
    }


@app.post("/api/esp32/validar-acceso")
async def validar_acceso_esp32(req: ValidacionESP32Request):
    """
    Ejecuta la lógica central de control de acceso y salida del ESP32:
    - Soporta UIDs leídos por RC522, modo de respaldo Serial ('1'/'0') y el Sensor Ultrasónico de Salida ('SALIDA').
    - Verifica disponibilidad del cajón según el Sensor HC-SR04 #1 (GPIO 32/35, umbral <= 10 cm).
    - Abre automáticamente la pluma en la salida cuando el Sensor HC-SR04 #2 (GPIO 33/34) detecta un vehículo (<= 10 cm).
    - Actualiza los periféricos (LCD 16x2, Servo SG90, LED Verde GPIO 13, LED Rojo GPIO 12, Buzzer GPIO 2).
    - Registra el evento en la bitácora SQLite.
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Obtener estado actual del sensor ultrasónico HC-SR04 #1 (Cajón A-01)
    cursor.execute("SELECT * FROM estado_hardware WHERE id = 1;")
    hw = dict(cursor.fetchone())

    if req.distancia_cm is not None:
        distancia_actual = round(req.distancia_cm, 1)
        lugar_ocupado = (0 < distancia_actual <= 10.0)
        cursor.execute("""
            UPDATE cajones SET estado = ?, distancia_cm = ?, es_sensor_fisico = 1, ultima_actualizacion = ?
            WHERE codigo = 'A-01';
        """, ("OCUPADO" if lugar_ocupado else "LIBRE", distancia_actual, ahora))
    else:
        distancia_actual = hw["distancia_cm"]
        lugar_ocupado = bool(hw["lugar_ocupado"])

    entrada_raw = req.uid.strip().upper()

    # CASO ESPECIAL: SALIDA AUTOMÁTICA POR SENSOR ULTRASÓNICO #2 (GPIO 33/34)
    if entrada_raw == "SALIDA" or req.origen == "SENSOR_SALIDA":
        dist_salida = round(req.distancia_2_cm, 1) if req.distancia_2_cm is not None else 5.0
        lcd_l1 = "Buen viaje."
        lcd_l2 = "Hasta luego"
        motivo_salida = (
            f"Salida vehicular detectada por Sensor Ultrasónico de Salida ({dist_salida} cm <= 10 cm). "
            "Pluma abierta a 90° por 3s."
        )

        cursor.execute("""
            UPDATE estado_hardware
            SET pluma_estado = 'ABIERTA',
                pluma_angulo = 90,
                lugar_ocupado = ?,
                distancia_cm = ?,
                lcd_linea1 = ?,
                lcd_linea2 = ?,
                led_verde = 1,
                led_rojo = 0,
                buzzer_activo = 1,
                ultimo_heartbeat = ?
            WHERE id = 1;
        """, (1 if lugar_ocupado else 0, distancia_actual, lcd_l1, lcd_l2, ahora))

        cursor.execute("""
            UPDATE cajones
            SET vehiculo_actual_placas = NULL, ultima_actualizacion = ?
            WHERE codigo = 'A-01';
        """, (ahora,))

        cursor.execute("""
            INSERT INTO bitacora_accesos (
                timestamp, uid_leido, usuario_nombre, rol_usuario,
                vehiculo_placas, vehiculo_descripcion, tipo_evento,
                acceso_concedido, motivo, distancia_sensor_cm, origen
            ) VALUES (?, 'SENSOR SALIDA', 'Vehículo en Salida', 'Salida Automática', '-', 'Detección HC-SR04 #2', 'SALIDA', 1, ?, ?, 'SENSOR_SALIDA');
        """, (ahora, motivo_salida, dist_salida))

        conn.commit()
        conn.close()

        asyncio.create_task(_ciclo_cierre_pluma_backend())

        return {
            "acceso_concedido": True,
            "codigo_respuesta": "SALIDA_AUTORIZADA",
            "uid": "SENSOR SALIDA",
            "usuario": "Vehículo en Salida",
            "placas": "-",
            "vehiculo": "Detección HC-SR04 #2",
            "motivo": motivo_salida,
            "lcd_linea1": lcd_l1,
            "lcd_linea2": lcd_l2,
            "abrir_pluma": True,
            "angulo_servo": 90,
            "tiempo_abierto_ms": 3000,
            "led_verde": True,
            "led_rojo": False,
            "buzzer_tonos": [{"freq": 1600, "ms": 120}, {"freq": 1200, "ms": 120}],
            "distancia_cm": distancia_actual
        }

    # 2. Evaluar si es Modo Respaldo por Consola Serial ('1' o '0') o Lectura de UID RFID
    es_autorizado = False
    motivo_rechazo_credencial = ""
    usuario_nombre = "No Registrado"
    rol_usuario = "Externo"
    vehiculo_placas = "-"
    vehiculo_desc = "-"
    uid_mostrar = normalizar_uid(entrada_raw)

    if entrada_raw == "1":
        # Modo de respaldo Serial '1' -> Autoriza con perfil de Respaldo Serial
        es_autorizado = True
        uid_mostrar = "SERIAL '1' (83 CF 7A 28)"
        usuario_nombre = "Mtro. Carlos Solano M. (Respaldo Serial)"
        rol_usuario = "Docente Tiempo Completo"
        vehiculo_placas = "UAM-204-C"
        vehiculo_desc = "Volkswagen Jetta (Blanco)"
    elif entrada_raw == "0":
        # Modo de respaldo Serial '0' -> Deniega explícitamente
        es_autorizado = False
        uid_mostrar = "SERIAL '0' (Denegado)"
        motivo_rechazo_credencial = "Denegado manualmente desde consola Serial ('0')."
    else:
        # Búsqueda en la tabla credenciales_rfid
        cursor.execute("""
            SELECT
                c.uid, c.estado, c.alias_tag,
                u.nombre, u.rol, u.activo,
                v.placas, v.marca, v.modelo, v.color
            FROM credenciales_rfid c
            JOIN usuarios u ON c.usuario_id = u.id
            LEFT JOIN vehiculos v ON c.vehiculo_id = v.id
            WHERE c.uid = ?;
        """, (uid_mostrar,))
        fila = cursor.fetchone()

        if not fila:
            es_autorizado = False
            motivo_rechazo_credencial = f"Tarjeta RFID ({uid_mostrar}) no registrada en la base de datos."
        else:
            usuario_nombre = fila["nombre"]
            rol_usuario = fila["rol"]
            vehiculo_placas = fila["placas"] or "-"
            vehiculo_desc = f"{fila['marca']} {fila['modelo']} ({fila['color']})" if fila["placas"] else "-"

            if fila["estado"] != "ACTIVA" or not fila["activo"]:
                es_autorizado = False
                motivo_rechazo_credencial = f"Credencial con estado '{fila['estado']}'. Acceso restringido."
            else:
                es_autorizado = True

    # 3. Aplicar Lógica de Control del Estacionamiento
    if not es_autorizado:
        # CASO 2: Credencial no autorizada -> LED rojo, tono grave (400 Hz, 700 ms) y pluma bloqueada (0°)
        lcd_l1 = "Acceso Denegado"
        lcd_l2 = "No autorizado"
        cursor.execute("""
            UPDATE estado_hardware
            SET pluma_estado = 'CERRADA',
                pluma_angulo = 0,
                lugar_ocupado = ?,
                distancia_cm = ?,
                lcd_linea1 = ?,
                lcd_linea2 = ?,
                led_verde = 0,
                led_rojo = 1,
                buzzer_activo = 1,
                ultimo_heartbeat = ?
            WHERE id = 1;
        """, (1 if lugar_ocupado else 0, distancia_actual, lcd_l1, lcd_l2, ahora))

        cursor.execute("""
            INSERT INTO bitacora_accesos (
                timestamp, uid_leido, usuario_nombre, rol_usuario,
                vehiculo_placas, vehiculo_descripcion, tipo_evento,
                acceso_concedido, motivo, distancia_sensor_cm, origen
            ) VALUES (?, ?, ?, ?, ?, ?, 'RECHAZO_NO_AUTORIZADO', 0, ?, ?, ?);
        """, (
            ahora, uid_mostrar, usuario_nombre, rol_usuario,
            vehiculo_placas, vehiculo_desc, motivo_rechazo_credencial,
            distancia_actual, req.origen
        ))
        conn.commit()
        conn.close()

        asyncio.create_task(_ciclo_reposo_rechazo_backend())

        return {
            "acceso_concedido": False,
            "codigo_respuesta": "DENEGADO_NO_AUTORIZADO",
            "uid": uid_mostrar,
            "usuario": usuario_nombre,
            "placas": vehiculo_placas,
            "vehiculo": vehiculo_desc,
            "motivo": motivo_rechazo_credencial,
            "lcd_linea1": lcd_l1,
            "lcd_linea2": lcd_l2,
            "abrir_pluma": False,
            "angulo_servo": 0,
            "led_verde": False,
            "led_rojo": True,
            "buzzer_tonos": [{"freq": 400, "ms": 700}],
            "distancia_cm": distancia_actual
        }

    # Si la credencial ES válida, verificar si el cajón físico A-01 está OCUPADO
    if lugar_ocupado:
        # CASO 1A: Credencial válida pero cajón OCUPADO -> Deniega paso, muestra "Lugar Ocupado / Espere por favor", tono 500 Hz
        lcd_l1 = "Lugar Ocupado"
        lcd_l2 = "Espere por favor"
        motivo_ocupado = (
            f"Cajón ocupado detectado por sensor HC-SR04 ({distancia_actual} cm <= 10 cm). "
            "Pluma mantenida abajo (0°)."
        )
        cursor.execute("""
            UPDATE estado_hardware
            SET pluma_estado = 'CERRADA',
                pluma_angulo = 0,
                lugar_ocupado = 1,
                distancia_cm = ?,
                lcd_linea1 = ?,
                lcd_linea2 = ?,
                led_verde = 0,
                led_rojo = 1,
                buzzer_activo = 1,
                ultimo_heartbeat = ?
            WHERE id = 1;
        """, (distancia_actual, lcd_l1, lcd_l2, ahora))

        cursor.execute("""
            INSERT INTO bitacora_accesos (
                timestamp, uid_leido, usuario_nombre, rol_usuario,
                vehiculo_placas, vehiculo_descripcion, tipo_evento,
                acceso_concedido, motivo, distancia_sensor_cm, origen
            ) VALUES (?, ?, ?, ?, ?, ?, 'RECHAZO_LUGAR_OCUPADO', 0, ?, ?, ?);
        """, (
            ahora, uid_mostrar, usuario_nombre, rol_usuario,
            vehiculo_placas, vehiculo_desc, motivo_ocupado,
            distancia_actual, req.origen
        ))
        conn.commit()
        conn.close()

        asyncio.create_task(_ciclo_reposo_rechazo_backend())

        return {
            "acceso_concedido": False,
            "codigo_respuesta": "DENEGADO_LUGAR_OCUPADO",
            "uid": uid_mostrar,
            "usuario": usuario_nombre,
            "placas": vehiculo_placas,
            "vehiculo": vehiculo_desc,
            "motivo": motivo_ocupado,
            "lcd_linea1": lcd_l1,
            "lcd_linea2": lcd_l2,
            "abrir_pluma": False,
            "angulo_servo": 0,
            "led_verde": False,
            "led_rojo": True,
            "buzzer_tonos": [{"freq": 500, "ms": 600}],
            "distancia_cm": distancia_actual
        }

    # CASO 1B: Credencial válida y cajón LIBRE -> Concede acceso:
    lcd_l1 = "Bienvenido."
    lcd_l2 = "Adelante"
    motivo_exito = (
        f"Acceso concedido a {usuario_nombre} ({vehiculo_placas}). "
        f"Cajón libre ({distancia_actual} cm). Pluma abierta a 90° por 3s."
    )

    cursor.execute("""
        UPDATE estado_hardware
        SET pluma_estado = 'ABIERTA',
            pluma_angulo = 90,
            lugar_ocupado = 0,
            distancia_cm = ?,
            lcd_linea1 = ?,
            lcd_linea2 = ?,
            led_verde = 1,
            led_rojo = 0,
            buzzer_activo = 1,
            ultimo_heartbeat = ?
        WHERE id = 1;
    """, (distancia_actual, lcd_l1, lcd_l2, ahora))

    cursor.execute("""
        UPDATE cajones
        SET vehiculo_actual_placas = ?, ultima_actualizacion = ?
        WHERE codigo = 'A-01';
    """, (vehiculo_placas, ahora))

    cursor.execute("""
        INSERT INTO bitacora_accesos (
            timestamp, uid_leido, usuario_nombre, rol_usuario,
            vehiculo_placas, vehiculo_descripcion, tipo_evento,
            acceso_concedido, motivo, distancia_sensor_cm, origen
        ) VALUES (?, ?, ?, ?, ?, ?, 'ENTRADA', 1, ?, ?, ?);
    """, (
        ahora, uid_mostrar, usuario_nombre, rol_usuario,
        vehiculo_placas, vehiculo_desc, motivo_exito,
        distancia_actual, req.origen
    ))
    conn.commit()
    conn.close()

    # Programar cierre automático de la pluma en el Gemelo Digital tras 3.2s ("Hasta luego.") y regreso al inicio
    asyncio.create_task(_ciclo_cierre_pluma_backend())

    return {
        "acceso_concedido": True,
        "codigo_respuesta": "ACCESO_CONCEDIDO",
        "uid": uid_mostrar,
        "usuario": usuario_nombre,
        "placas": vehiculo_placas,
        "vehiculo": vehiculo_desc,
        "motivo": motivo_exito,
        "lcd_linea1": lcd_l1,
        "lcd_linea2": lcd_l2,
        "abrir_pluma": True,
        "angulo_servo": 90,
        "tiempo_abierto_ms": 3000,
        "led_verde": True,
        "led_rojo": False,
        "buzzer_tonos": [{"freq": 1400, "ms": 120}, {"freq": 1800, "ms": 120}],
        "distancia_cm": distancia_actual
    }


@app.post("/api/hardware/pluma")
async def controlar_pluma_remota(req: ControlPlumaRequest):
    """
    Permite abrir o cerrar la pluma (Servomotor SG90 en GPIO 4) desde la interfaz web/móvil
    o volver el display a su pantalla de reposo después de los 3 segundos de apertura.
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT lugar_ocupado, distancia_cm FROM estado_hardware WHERE id = 1;")
    hw = dict(cursor.fetchone())
    ocupado = bool(hw["lugar_ocupado"])

    if req.accion == "ABRIR":
        cursor.execute("""
            UPDATE estado_hardware
            SET pluma_estado = 'ABIERTA',
                pluma_angulo = 90,
                lcd_linea1 = 'Bienvenido.',
                lcd_linea2 = 'Adelante',
                led_verde = 1,
                led_rojo = 0,
                comando_pendiente = 'ABRIR_PLUMA',
                ultimo_heartbeat = ?
            WHERE id = 1;
        """, (ahora,))
    else:
        lcd_l1 = "Lugar: OCUPADO" if ocupado else "Lugar: LIBRE"
        cursor.execute("""
            UPDATE estado_hardware
            SET pluma_estado = 'CERRADA',
                pluma_angulo = 0,
                lcd_linea1 = ?,
                lcd_linea2 = 'Acerque tarjeta',
                led_verde = 0,
                led_rojo = 0,
                buzzer_activo = 0,
                comando_pendiente = 'CERRAR_PLUMA',
                ultimo_heartbeat = ?
            WHERE id = 1;
        """, (lcd_l1, ahora))

    conn.commit()
    conn.close()
    return {"ok": True, "pluma_estado": "ABIERTA" if req.accion == "ABRIR" else "CERRADA"}


@app.post("/api/cajones/{codigo}/actualizar")
async def actualizar_cajon(codigo: str, req: ActualizarCajonRequest):
    """
    Actualiza el estado de un cajón de estacionamiento.
    Si es el cajón A-01 (vinculado al sensor HC-SR04 en GPIO 32/35), también sincroniza el estado del hardware.
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM cajones WHERE codigo = ?;", (codigo,))
    cajon = cursor.fetchone()
    if not cajon:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Cajón {codigo} no encontrado.")

    cajon_dict = dict(cajon)
    if req.distancia_cm is not None:
        dist = round(req.distancia_cm, 1)
        estado = "OCUPADO" if (0 < dist <= cajon_dict["umbral_cm"]) else "LIBRE"
    elif req.estado is not None:
        estado = req.estado
        dist = 5.5 if estado == "OCUPADO" else 45.0
    else:
        # Toggle automático
        estado = "LIBRE" if cajon_dict["estado"] == "OCUPADO" else "OCUPADO"
        dist = 5.5 if estado == "OCUPADO" else 45.0

    placas = req.vehiculo_actual_placas if req.vehiculo_actual_placas is not None else (
        cajon_dict["vehiculo_actual_placas"] if estado == "OCUPADO" else None
    )

    cursor.execute("""
        UPDATE cajones
        SET estado = ?, distancia_cm = ?, vehiculo_actual_placas = ?, ultima_actualizacion = ?
        WHERE codigo = ?;
    """, (estado, dist, placas, ahora, codigo))

    if codigo == "A-01":
        ocupado_int = 1 if estado == "OCUPADO" else 0
        lcd_l1 = "Lugar: OCUPADO" if ocupado_int else "Lugar: LIBRE"
        cursor.execute("""
            UPDATE estado_hardware
            SET lugar_ocupado = ?,
                distancia_cm = ?,
                lcd_linea1 = ?,
                lcd_linea2 = 'Acerque tarjeta',
                ultimo_heartbeat = ?
            WHERE id = 1;
        """, (ocupado_int, dist, lcd_l1, ahora))

    conn.commit()
    conn.close()
    return {"ok": True, "codigo": codigo, "estado": estado, "distancia_cm": dist}


@app.get("/api/bitacora/exportar")
async def exportar_bitacora_csv():
    """Exporta el historial completo de accesos en un archivo CSV descargable."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bitacora_accesos ORDER BY id DESC;")
    filas = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    output.write("\ufeff")  # BOM para correcta visualización de acentos en Excel
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Fecha y Hora", "UID / Comando", "Usuario", "Rol",
        "Placas", "Vehículo", "Tipo de Evento", "Acceso Concedido",
        "Distancia HC-SR04 (cm)", "Origen", "Motivo / Detalle"
    ])
    for r in filas:
        writer.writerow([
            r["id"],
            r["timestamp"],
            r["uid_leido"],
            r["usuario_nombre"],
            r["rol_usuario"],
            r["vehiculo_placas"],
            r["vehiculo_descripcion"],
            r["tipo_evento"],
            "SÍ" if r["acceso_concedido"] else "NO",
            r["distancia_sensor_cm"],
            r["origen"],
            r["motivo"]
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=bitacora_estacionamiento_esp32.csv"}
    )
