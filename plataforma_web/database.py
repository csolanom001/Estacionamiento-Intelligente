# -*- coding: utf-8 -*-
"""
Capa de Persistencia SQLite - Sistema de Estacionamiento Inteligente con ESP32
Gestiona usuarios, vehículos, credenciales RFID (RC522), estado de cajones (HC-SR04),
estado del hardware (Servo SG90, LCD 16x2, LEDs, Buzzer) y bitácora de accesos.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estacionamiento.db")


def normalizar_uid(uid: str) -> str:
    """
    Normaliza cualquier representación de UID RFID (ej. '83cf7a28', '83:CF:7A:28', '83 CF 7A 28')
    al formato estándar hexadecimal separado por espacios: '83 CF 7A 28' (o cadena limpia si es alfanumérico).
    """
    if not uid:
        return ""
    limpio = uid.strip().upper().replace(":", "").replace("-", "").replace(" ", "")
    if len(limpio) == 8:
        return " ".join(limpio[i:i+2] for i in range(0, 8, 2))
    return uid.strip().upper()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Inicializa las tablas de la base de datos y carga datos semilla si está vacía."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Tabla de Usuarios (Docentes, Administrativos, etc.)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'Docente',
            departamento TEXT NOT NULL DEFAULT 'Ingeniería',
            correo TEXT,
            telefono TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_registro TEXT NOT NULL
        );
    """)

    # 2. Tabla de Vehículos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vehiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            placas TEXT NOT NULL UNIQUE,
            marca TEXT NOT NULL,
            modelo TEXT NOT NULL,
            color TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        );
    """)

    # 3. Tabla de Credenciales RFID (UIDs RC522)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credenciales_rfid (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL UNIQUE,
            usuario_id INTEGER NOT NULL,
            vehiculo_id INTEGER,
            alias_tag TEXT NOT NULL DEFAULT 'Tarjeta Blanca MIFARE',
            estado TEXT NOT NULL DEFAULT 'ACTIVA',
            fecha_asignacion TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id) ON DELETE SET NULL
        );
    """)

    # 4. Tabla de Cajones de Estacionamiento (Monitoreo HC-SR04 y Aforo)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cajones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            zona TEXT NOT NULL DEFAULT 'Zona Maestros A',
            estado TEXT NOT NULL DEFAULT 'LIBRE',
            distancia_cm REAL NOT NULL DEFAULT 999.0,
            umbral_cm REAL NOT NULL DEFAULT 10.0,
            es_sensor_fisico INTEGER NOT NULL DEFAULT 0,
            vehiculo_actual_placas TEXT,
            ultima_actualizacion TEXT NOT NULL
        );
    """)

    # 5. Tabla de Estado en Tiempo Real del Hardware ESP32
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estado_hardware (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            pluma_estado TEXT NOT NULL DEFAULT 'CERRADA',
            pluma_angulo INTEGER NOT NULL DEFAULT 0,
            lugar_ocupado INTEGER NOT NULL DEFAULT 0,
            distancia_cm REAL NOT NULL DEFAULT 145.0,
            lcd_linea1 TEXT NOT NULL DEFAULT 'Lugar: LIBRE',
            lcd_linea2 TEXT NOT NULL DEFAULT 'Acerque tarjeta',
            led_verde INTEGER NOT NULL DEFAULT 0,
            led_rojo INTEGER NOT NULL DEFAULT 0,
            buzzer_activo INTEGER NOT NULL DEFAULT 0,
            lector_rfid_operativo INTEGER NOT NULL DEFAULT 0,
            modo_respaldo_serial INTEGER NOT NULL DEFAULT 1,
            esp32_ip TEXT DEFAULT '192.168.1.150',
            ultimo_heartbeat TEXT,
            comando_pendiente TEXT DEFAULT NULL
        );
    """)

    # 6. Tabla de Bitácora / Historial de Accesos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bitacora_accesos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            uid_leido TEXT NOT NULL,
            usuario_nombre TEXT NOT NULL,
            rol_usuario TEXT DEFAULT '-',
            vehiculo_placas TEXT DEFAULT '-',
            vehiculo_descripcion TEXT DEFAULT '-',
            tipo_evento TEXT NOT NULL,
            acceso_concedido INTEGER NOT NULL,
            motivo TEXT NOT NULL,
            distancia_sensor_cm REAL NOT NULL DEFAULT 0.0,
            origen TEXT NOT NULL DEFAULT 'RFID_RC522'
        );
    """)

    # Verificar si ya existen datos semilla
    cursor.execute("SELECT COUNT(*) as total FROM usuarios;")
    if cursor.fetchone()["total"] == 0:
        ahora = datetime.now()
        fmt = "%Y-%m-%d %H:%M:%S"

        # Insertar usuarios principales (incluyendo los 3 UIDs del firmware pluma.ino)
        usuarios_seed = [
            ("Mtro. Carlos Solano M.", "Docente Tiempo Completo", "Facultad de Ingeniería", "csolano@uaemex.mx", "722-510-4412", 1, (ahora - timedelta(days=30)).strftime(fmt)),
            ("Dra. Diana Ivon Benítez González", "Investigadora / Docente", "Tecnologías Computacionales", "dbenitez@uaemex.mx", "722-398-1120", 1, (ahora - timedelta(days=28)).strftime(fmt)),
            ("Dr. Juan Pérez Ramírez", "Docente Tiempo Completo", "Sistemas y Computación", "jperez@uaemex.mx", "722-104-8891", 1, (ahora - timedelta(days=20)).strftime(fmt)),
            ("Mtra. María García López", "Coordinadora Académica", "Administración Escolar", "mgarcia@uaemex.mx", "722-841-9902", 1, (ahora - timedelta(days=15)).strftime(fmt)),
            ("Ing. Roberto Hernández Cruz", "Personal Administrativo", "Servicios Universitarios", "rhernandez@uaemex.mx", "722-672-3319", 1, (ahora - timedelta(days=7)).strftime(fmt)),
        ]
        cursor.executemany("""
            INSERT INTO usuarios (nombre, rol, departamento, correo, telefono, activo, fecha_registro)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, usuarios_seed)

        # Insertar vehículos asociados
        vehiculos_seed = [
            (1, "UAM-204-C", "Volkswagen", "Jetta", "Blanco"),
            (2, "MTR-910-B", "Mazda", "Mazda 3", "Rojo"),
            (3, "LFK-482-A", "Nissan", "Sentra", "Gris Oxford"),
            (4, "EDO-771-X", "Toyota", "Corolla", "Plata"),
            (5, "TLC-309-Z", "Honda", "Civic", "Azul Marino"),
        ]
        cursor.executemany("""
            INSERT INTO vehiculos (usuario_id, placas, marca, modelo, color)
            VALUES (?, ?, ?, ?, ?);
        """, vehiculos_seed)

        # Insertar credenciales RFID (los UIDs físicos del prototipo ESP32)
        credenciales_seed = [
            ("6C D3 F5 37", 1, 1, "Llavero Azul RFID (Nuevo RC522)", "ACTIVA", (ahora - timedelta(days=1)).strftime(fmt)),
            ("E1 91 E9 BE", 2, 2, "Tarjeta Blanca MIFARE 13.56MHz", "ACTIVA", (ahora - timedelta(days=2)).strftime(fmt)),
            ("83 CF 7A 28", 1, 1, "Tarjeta MIFARE Principal (ESP32 #1)", "ACTIVA", (ahora - timedelta(days=30)).strftime(fmt)),
            ("A3 6C 9F 14", 2, 2, "Llavero Azul RFID (ESP32 #2)", "ACTIVA", (ahora - timedelta(days=28)).strftime(fmt)),
            ("09 B8 95 80", 3, 3, "Tarjeta MIFARE Docente (ESP32 #3)", "ACTIVA", (ahora - timedelta(days=20)).strftime(fmt)),
            ("A1 B2 C3 D4", 4, 4, "Tag NFC Coordinación", "ACTIVA", (ahora - timedelta(days=15)).strftime(fmt)),
            ("E5 F6 G7 H8", 5, 5, "Credencial Temporal bloqueada", "BLOQUEADA", (ahora - timedelta(days=7)).strftime(fmt)),
        ]
        cursor.executemany("""
            INSERT INTO credenciales_rfid (uid, usuario_id, vehiculo_id, alias_tag, estado, fecha_asignacion)
            VALUES (?, ?, ?, ?, ?, ?);
        """, credenciales_seed)

        # Insertar cajones de estacionamiento (Cajones A-01 y A-02 son los 2 sensores HC-SR04 físicos del ESP32)
        cajones_seed = [
            ("A-01", "Prototipo Físico #1 (HC-SR04 GPIO 32/35)", "LIBRE", 42.0, 10.0, 1, None, ahora.strftime(fmt)),
            ("A-02", "Prototipo Físico #2 (HC-SR04 GPIO 33/34)", "LIBRE", 45.0, 10.0, 1, None, ahora.strftime(fmt)),
            ("A-03", "Zona Docentes Norte", "LIBRE", 120.0, 10.0, 0, None, (ahora - timedelta(minutes=30)).strftime(fmt)),
            ("A-04", "Zona Docentes Sur", "LIBRE", 95.0, 10.0, 0, None, (ahora - timedelta(minutes=15)).strftime(fmt)),
        ]
        cursor.executemany("""
            INSERT INTO cajones (codigo, zona, estado, distancia_cm, umbral_cm, es_sensor_fisico, vehiculo_actual_placas, ultima_actualizacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, cajones_seed)

        # Insertar estado inicial del hardware ESP32
        cursor.execute("""
            INSERT INTO estado_hardware (
                id, pluma_estado, pluma_angulo, lugar_ocupado, distancia_cm,
                lcd_linea1, lcd_linea2, led_verde, led_rojo, buzzer_activo,
                lector_rfid_operativo, modo_respaldo_serial, esp32_ip, ultimo_heartbeat, comando_pendiente
            ) VALUES (
                1, 'CERRADA', 0, 0, 42.0,
                'Lugar: LIBRE', 'Acerque tarjeta', 0, 0, 0,
                1, 1, '192.168.1.150', ?, NULL
            );
        """, (ahora.strftime(fmt),))

        # Insertar eventos de demostración en la bitácora
        bitacora_seed = [
            (
                (ahora - timedelta(minutes=52)).strftime(fmt),
                "A3 6C 9F 14",
                "Dra. Diana Ivon Benítez González",
                "Investigadora / Docente",
                "MTR-910-B",
                "Mazda 3 (Rojo)",
                "ENTRADA",
                1,
                "Credencial válida y cajón libre. Pluma abierta 90° por 3s.",
                45.0,
                "RFID_RC522"
            ),
            (
                (ahora - timedelta(minutes=34)).strftime(fmt),
                "FF 12 9A 01",
                "No Registrado",
                "Desconocido",
                "-",
                "-",
                "RECHAZO_NO_AUTORIZADO",
                0,
                "UID no registrado en la base de datos. LED Rojo + Tono 400Hz.",
                42.0,
                "RFID_RC522"
            ),
            (
                (ahora - timedelta(minutes=19)).strftime(fmt),
                "83 CF 7A 28",
                "Mtro. Carlos Solano M.",
                "Docente Tiempo Completo",
                "UAM-204-C",
                "Volkswagen Jetta (Blanco)",
                "RECHAZO_LUGAR_OCUPADO",
                0,
                "Credencial válida pero HC-SR04 detectó cajón OCUPADO (6.5 cm <= 10 cm).",
                6.5,
                "SERIAL_MONITOR"
            ),
            (
                (ahora - timedelta(minutes=8)).strftime(fmt),
                "83 CF 7A 28",
                "Mtro. Carlos Solano M.",
                "Docente Tiempo Completo",
                "UAM-204-C",
                "Volkswagen Jetta (Blanco)",
                "ENTRADA",
                1,
                "Autorizado por Respaldo Serial ('1'). Cajón libre (42.0 cm).",
                42.0,
                "SERIAL_MONITOR"
            ),
        ]
        cursor.executemany("""
            INSERT INTO bitacora_accesos (
                timestamp, uid_leido, usuario_nombre, rol_usuario,
                vehiculo_placas, vehiculo_descripcion, tipo_evento,
                acceso_concedido, motivo, distancia_sensor_cm, origen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, bitacora_seed)

    # Asegurar que A-01 esté configurado como el sensor HC-SR04 físico de cajón (GPIO 32/35)
    cursor.execute("""
        UPDATE cajones
        SET zona = 'Prototipo Físico ESP32 (HC-SR04 GPIO 32/35)', es_sensor_fisico = 1
        WHERE codigo = 'A-01';
    """)
    cursor.execute("""
        UPDATE cajones
        SET zona = 'Zona Docentes Norte', es_sensor_fisico = 0
        WHERE codigo = 'A-02';
    """)

    conn.commit()
    conn.close()
