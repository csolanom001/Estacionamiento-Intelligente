#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// =====================================================
// CONFIGURACIÓN WI-FI Y SERVIDOR API REST (FASTAPI)
// =====================================================
const char* WIFI_SSID     = "iPhone de Carlos";
const char* WIFI_PASSWORD = "12345678";

// Dirección IP de la PC y puerto 8085 (exclusivo para el Sistema de Estacionamiento):
// - En Zona con cobertura móvil de tu Laptop (Windows): http://192.168.137.1:8085
// - En Hotspot del iPhone:                              http://172.20.10.5:8085
// - En Wi-Fi de casa:                                   http://192.168.1.74:8085
const char* API_BASE_URL  = "http://192.168.137.1:8085";

// =====================================================
// PINES RFID RC522 - BUS VSPI NATIVO (ESP-WROOM-32D)
// IMPORTANTE: ALIMENTAR EXCLUSIVAMENTE A 3.3V
// =====================================================
#define SS_PIN    5   // SDA/SS -> GPIO 5
#define SCK_PIN   18  // SCK    -> GPIO 18 (VSPI nativo)
#define MISO_PIN  19  // MISO   -> GPIO 19 (VSPI nativo)
#define MOSI_PIN  23  // MOSI   -> GPIO 23 (VSPI nativo)
#define RST_PIN   27  // RST    -> GPIO 27

// =====================================================
// PINES SENSORES ULTRASÓNICOS HC-SR04
// - Sensor 1 (Cajón A-01): Trig -> GPIO 32, Echo -> GPIO 35
// - Sensor 2 (Salida):     Trig -> GPIO 33, Echo -> GPIO 34
// =====================================================
#define TRIG_PIN          32  // Cajón A-01 Trig -> GPIO 32
#define ECHO_PIN          35  // Cajón A-01 Echo -> GPIO 35
#define TRIG_SALIDA_PIN   33  // Sensor Salida Trig -> GPIO 33
#define ECHO_SALIDA_PIN   34  // Sensor Salida Echo -> GPIO 34
#define DISTANCIA_UMBRAL_CM  10

// =====================================================
// PINES INDICADORES Y SERVO SG90
// =====================================================
#define LED_ROJO    12  // GPIO 12 -> LED rojo
#define LED_VERDE   13  // GPIO 13 -> LED verde
#define BUZZER_PIN  2   // GPIO 2  -> Buzzer LEDC
#define SERVO_PIN   4   // GPIO 4  -> Señal Servo SG90 (6V externo con GND común)

// I2C (Display LCD 16x2): SDA -> GPIO 21, SCL -> GPIO 22

#define BUZZER_FRECUENCIA   1000
#define BUZZER_RESOLUCION   8

#define ANGULO_CERRADO   0
#define ANGULO_ABIERTO  90

// =====================================================
// OBJETOS
// =====================================================
MFRC522 mfrc522(SS_PIN, RST_PIN);
LiquidCrystal_I2C lcd(0x27, 16, 2);

// =====================================================
// CACHÉ LOCAL DE TARJETAS AUTORIZADAS (RESPALDO OFFLINE)
// =====================================================
byte UIDS_AUTORIZADOS[][4] = {
  {0x6C, 0xD3, 0xF5, 0x37}, // Llavero azul nuevo RC522
  {0x83, 0xCF, 0x7A, 0x28}, // Tarjeta blanca MIFARE
  {0x7A, 0x51, 0x11, 0x11},
  {0xA3, 0x6C, 0x9F, 0x14},
  {0x09, 0xB8, 0x95, 0x80}
};
const byte CANTIDAD_UIDS = sizeof(UIDS_AUTORIZADOS) / sizeof(UIDS_AUTORIZADOS[0]);

// Variables de estado
bool lugarOcupado = false;
long ultimaDistanciaCm = 999;
long distanciaSalidaCm = 999;
unsigned long ultimaLecturaUltrasonico = 0;
unsigned long ultimoReporteTelemetria = 0;

// Prototipos
bool tarjetaAutorizadaLocal(const byte *uidLeido, byte uidSize);
String uidToHexString(const byte *uid, byte uidSize);
int validarAccesoRemoto(const String &uidHex, long distCajonCm, long distSalidaCm, const String &origen);
void enviarTelemetriaRest(long distCajonCm, long distSalidaCm);
void procesarDecisionAcceso(bool credencialValida);
void accesoConcedido();
void salidaVehiculo();
void accesoDenegado();
void accesoDenegadoPorLugarOcupado();
void sonarBuzzer(uint16_t frecuencia, uint16_t duracion);
void posicionarServo(int angulo, int duracionMs);
long medirDistanciaSensorCm(int trigPin, int echoPin);
void actualizarPantallaInicio();
void rearmarLectorRFID();

// =====================================================
// SETUP
// =====================================================
void setup() {
  Serial.begin(115200);
  delay(800);

  // 1. Inicializar LCD I2C
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Iniciando...");

  // 2. Configurar Pines
  pinMode(LED_ROJO, OUTPUT);
  pinMode(LED_VERDE, OUTPUT);
  pinMode(SERVO_PIN, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(TRIG_SALIDA_PIN, OUTPUT);
  pinMode(ECHO_SALIDA_PIN, INPUT);

  digitalWrite(LED_ROJO, LOW);
  digitalWrite(LED_VERDE, LOW);
  digitalWrite(SERVO_PIN, LOW);
  digitalWrite(TRIG_PIN, LOW);
  digitalWrite(TRIG_SALIDA_PIN, LOW);

  // 3. Buzzer (LEDC ESP32 Core 3.x)
  ledcAttach(BUZZER_PIN, BUZZER_FRECUENCIA, BUZZER_RESOLUCION);
  ledcWriteTone(BUZZER_PIN, 0);

  // 4. Ubicar pluma en reposo (cerrada a 0°)
  posicionarServo(ANGULO_CERRADO, 400);

  // 5. Iniciar bus VSPI y lector RFID RC522 (3.3V)
  pinMode(RST_PIN, OUTPUT);
  digitalWrite(RST_PIN, HIGH);
  pinMode(SS_PIN, OUTPUT);
  digitalWrite(SS_PIN, HIGH);
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);
  delay(50);
  rearmarLectorRFID();
  byte versionRC522 = mfrc522.PCD_ReadRegister(mfrc522.VersionReg);
  Serial.print(F("[RFID] Chip RC522 detectado -> VersionReg = 0x"));
  Serial.println(versionRC522, HEX);

  // 6. Conexión Wi-Fi no bloqueante (hasta 10s para Hotspot de iPhone; si no, opera con caché local)
  lcd.setCursor(0, 1);
  lcd.print("Conectando WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long inicioWifi = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - inicioWifi < 10000)) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("[WIFI] Conectado. IP ESP32: "));
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(F("[WIFI] Sin conexion. Operando con cache local y respaldo Serial."));
  }

  Serial.println(F("===================================================="));
  Serial.println(F(" SISTEMA INTELIGENTE DE ESTACIONAMIENTO ESP32"));
  Serial.println(F(" - Lector RC522 (VSPI 3.3V) o Serial ('1'=SI, '0'=NO)"));
  Serial.println(F(" - Sensor Cajon HC-SR04  (Trig:32, Echo:35, <=10cm)"));
  Serial.println(F(" - Sensor Salida HC-SR04 (Trig:33, Echo:34, <=10cm)"));
  Serial.println(F("===================================================="));

  sonarBuzzer(1200, 150);
  actualizarPantallaInicio();
}

void rearmarLectorRFID() {
  digitalWrite(RST_PIN, HIGH);
  mfrc522.PCD_Init();
  delay(10);
  mfrc522.PCD_SetAntennaGain(mfrc522.RxGain_max);
}

// =====================================================
// LOOP PRINCIPAL
// =====================================================
void loop() {
  // 1. Monitoreo periódico de los 2 sensores ultrasónicos HC-SR04 cada 400 ms
  if (millis() - ultimaLecturaUltrasonico > 400) {
    ultimaLecturaUltrasonico = millis();

    // 1A. Medir Sensor 1 (Ocupación del Cajón A-01)
    ultimaDistanciaCm = medirDistanciaSensorCm(TRIG_PIN, ECHO_PIN);
    bool estadoAnterior = lugarOcupado;
    lugarOcupado = (ultimaDistanciaCm > 0 && ultimaDistanciaCm <= DISTANCIA_UMBRAL_CM);

    if (estadoAnterior != lugarOcupado) {
      Serial.print(F("[CAJON] DIST: "));
      Serial.println(ultimaDistanciaCm);
      actualizarPantallaInicio();
      enviarTelemetriaRest(ultimaDistanciaCm, distanciaSalidaCm);
    }

    // 1B. Medir Sensor 2 (Sensor de Salida Vehicular)
    delay(15); // Pausa breve para evitar ecos cruzados
    distanciaSalidaCm = medirDistanciaSensorCm(TRIG_SALIDA_PIN, ECHO_SALIDA_PIN);

    if (distanciaSalidaCm > 0 && distanciaSalidaCm <= DISTANCIA_UMBRAL_CM) {
      Serial.print(F("\n[SALIDA] Vehiculo detectado en sensor de salida ("));
      Serial.print(distanciaSalidaCm);
      Serial.println(F(" cm) -> Abriendo pluma para salida..."));

      if (WiFi.status() == WL_CONNECTED) {
        validarAccesoRemoto("SALIDA", ultimaDistanciaCm, distanciaSalidaCm, "SENSOR_SALIDA");
      }
      salidaVehiculo();
      rearmarLectorRFID();
      return;
    }
  }

  // 2. Envío periódico de telemetría y consulta de comandos remotos cada 3 segundos
  if (millis() - ultimoReporteTelemetria > 3000) {
    ultimoReporteTelemetria = millis();
    rearmarLectorRFID();
    enviarTelemetriaRest(ultimaDistanciaCm, distanciaSalidaCm);
  }

  // 3. MODO DE RESPALDO POR CONSOLA SERIAL ('1' autoriza, '0' deniega)
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == '1') {
      Serial.println(F("\n[SERIAL] Comando '1' recibido -> Credencial Autorizada"));
      if (WiFi.status() == WL_CONNECTED) {
        validarAccesoRemoto("1", ultimaDistanciaCm, distanciaSalidaCm, "SERIAL_MONITOR");
      }
      procesarDecisionAcceso(true);
      rearmarLectorRFID();
    } else if (cmd == '0') {
      Serial.println(F("\n[SERIAL] Comando '0' recibido -> Credencial NO Autorizada"));
      if (WiFi.status() == WL_CONNECTED) {
        validarAccesoRemoto("0", ultimaDistanciaCm, distanciaSalidaCm, "SERIAL_MONITOR");
      }
      procesarDecisionAcceso(false);
      rearmarLectorRFID();
    }
  }

  // 4. LECTURA DEL MÓDULO RFID RC522 (3.3V)
  if (!mfrc522.PICC_IsNewCardPresent()) return;
  if (!mfrc522.PICC_ReadCardSerial()) return;

  String uidStr = uidToHexString(mfrc522.uid.uidByte, mfrc522.uid.size);
  Serial.print(F("\n[RFID] UID leido: "));
  Serial.println(uidStr);

  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();

  bool autorizada = false;
  if (WiFi.status() == WL_CONNECTED) {
    // Valida contra la base de datos SQLite vía API REST (1=Autorizado, 0=Denegado, -1=Sin respuesta HTTP -> usa caché local)
    int respApi = validarAccesoRemoto(uidStr, ultimaDistanciaCm, distanciaSalidaCm, "RFID_RC522");
    if (respApi == 1) {
      autorizada = true;
    } else if (respApi == 0) {
      autorizada = false;
    } else {
      autorizada = tarjetaAutorizadaLocal(mfrc522.uid.uidByte, mfrc522.uid.size);
    }
  } else {
    // Respaldo local en caso de operar sin Wi-Fi
    autorizada = tarjetaAutorizadaLocal(mfrc522.uid.uidByte, mfrc522.uid.size);
  }

  procesarDecisionAcceso(autorizada);

  rearmarLectorRFID();
  delay(500);
}

// =====================================================
// LÓGICA CENTRAL DE DECISIÓN Y ACTUADORES
// =====================================================
void procesarDecisionAcceso(bool credencialValida) {
  if (credencialValida) {
    if (lugarOcupado) {
      accesoDenegadoPorLugarOcupado();
    } else {
      accesoConcedido();
    }
  } else {
    accesoDenegado();
  }
}

void accesoDenegadoPorLugarOcupado() {
  Serial.println(F("ACCESO DENEGADO: Lugar actualmente ocupado."));
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Lugar Ocupado");
  lcd.setCursor(0, 1);
  lcd.print("Espere por favor");
  sonarBuzzer(500, 600);
  delay(2000);
  actualizarPantallaInicio();
}

void accesoConcedido() {
  Serial.println(F("ACCESO CONCEDIDO: Abriendo pluma a 90 grados..."));

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Bienvenido.");
  lcd.setCursor(0, 1);
  lcd.print("Adelante");

  digitalWrite(LED_ROJO, LOW);
  digitalWrite(LED_VERDE, HIGH);

  sonarBuzzer(1400, 120);
  delay(100);
  sonarBuzzer(1800, 120);
  delay(150);

  posicionarServo(ANGULO_ABIERTO, 800);
  delay(3000);

  Serial.println(F("Cerrando pluma a 0 grados..."));
  posicionarServo(ANGULO_CERRADO, 800);
  digitalWrite(LED_VERDE, LOW);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Hasta luego.");
  delay(2000);

  actualizarPantallaInicio();
  Serial.println(F("Sistema listo para otra tarjeta."));
}

void salidaVehiculo() {
  Serial.println(F("SALIDA AUTORIZADA: Abriendo pluma a 90 grados..."));

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Buen viaje.");
  lcd.setCursor(0, 1);
  lcd.print("Hasta luego");

  digitalWrite(LED_ROJO, LOW);
  digitalWrite(LED_VERDE, HIGH);

  sonarBuzzer(1600, 120);
  delay(100);
  sonarBuzzer(1200, 120);
  delay(150);

  posicionarServo(ANGULO_ABIERTO, 800);
  delay(3000);

  // Si el vehículo sigue frente al sensor de salida, esperar hasta que termine de pasar (máx 3s extra)
  unsigned long esperaPaso = millis();
  while (millis() - esperaPaso < 3000) {
    long d = medirDistanciaSensorCm(TRIG_SALIDA_PIN, ECHO_SALIDA_PIN);
    if (d == 0 || d > DISTANCIA_UMBRAL_CM) break;
    delay(200);
  }

  Serial.println(F("Cerrando pluma tras salida a 0 grados..."));
  posicionarServo(ANGULO_CERRADO, 800);
  digitalWrite(LED_VERDE, LOW);

  // Actualizar lectura del cajón tras la salida del vehículo
  ultimaDistanciaCm = medirDistanciaSensorCm(TRIG_PIN, ECHO_PIN);
  lugarOcupado = (ultimaDistanciaCm > 0 && ultimaDistanciaCm <= DISTANCIA_UMBRAL_CM);
  actualizarPantallaInicio();
  enviarTelemetriaRest(ultimaDistanciaCm, 999);
  Serial.println(F("Salida completada. Sistema listo."));
}

void accesoDenegado() {
  Serial.println(F("ACCESO DENEGADO: Pluma bloqueada."));

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Acceso Denegado");
  lcd.setCursor(0, 1);
  lcd.print("No autorizado");

  posicionarServo(ANGULO_CERRADO, 200);

  digitalWrite(LED_VERDE, LOW);
  digitalWrite(LED_ROJO, HIGH);

  sonarBuzzer(400, 700);
  delay(1200);

  digitalWrite(LED_ROJO, LOW);
  actualizarPantallaInicio();
  Serial.println(F("Sistema listo para otra tarjeta."));
}

// =====================================================
// COMUNICACIÓN HTTP REST CON LA BASE DE DATOS
// =====================================================
int validarAccesoRemoto(const String &uidHex, long distCajonCm, long distSalidaCm, const String &origen) {
  HTTPClient http;
  http.setTimeout(2500);
  String url = String(API_BASE_URL) + "/api/esp32/validar-acceso";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  String payload = "{\"uid\":\"" + uidHex + "\",\"distancia_cm\":" + String(distCajonCm) + ",\"distancia_2_cm\":" + String(distSalidaCm) + ",\"origen\":\"" + origen + "\"}";
  int httpCode = http.POST(payload);

  if (httpCode == 200) {
    String respuesta = http.getString();
    http.end();
    // Si la API respondió acceso_concedido:true o DENEGADO_LUGAR_OCUPADO (credencial sí era válida)
    if (respuesta.indexOf("\"acceso_concedido\":true") != -1 ||
        respuesta.indexOf("DENEGADO_LUGAR_OCUPADO") != -1) {
      return 1;
    }
    return 0;
  }
  http.end();
  return -1;
}

void enviarTelemetriaRest(long distCajonCm, long distSalidaCm) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/esp32/telemetria";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  String payload = "{\"distancia_cm\":" + String(distCajonCm) + ",\"distancia_2_cm\":" + String(distSalidaCm) + ",\"esp32_ip\":\"" + WiFi.localIP().toString() + "\"}";
  int httpCode = http.POST(payload);

  if (httpCode == 200) {
    String resp = http.getString();
    if (resp.indexOf("ABRIR_PLUMA") != -1) {
      Serial.println(F("[REMOTO] Apertura de pluma solicitada desde Dashboard Web"));
      accesoConcedido();
    }
  }
  http.end();
}

// =====================================================
// FUNCIONES AUXILIARES DE HARDWARE
// =====================================================
long medirDistanciaSensorCm(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duracion = pulseIn(echoPin, HIGH, 25000);
  if (duracion == 0) return 999;
  return duracion / 58;
}

void actualizarPantallaInicio() {
  lcd.clear();
  lcd.setCursor(0, 0);
  if (lugarOcupado) {
    lcd.print("Lugar: OCUPADO");
  } else {
    lcd.print("Lugar: LIBRE");
  }
  lcd.setCursor(0, 1);
  lcd.print("Acerque tarjeta ");
}

bool tarjetaAutorizadaLocal(const byte *uidLeido, byte uidSize) {
  if (uidSize != 4) return false;
  for (byte tarjeta = 0; tarjeta < CANTIDAD_UIDS; tarjeta++) {
    bool coincide = true;
    for (byte i = 0; i < 4; i++) {
      if (uidLeido[i] != UIDS_AUTORIZADOS[tarjeta][i]) {
        coincide = false;
        break;
      }
    }
    if (coincide) return true;
  }
  return false;
}

String uidToHexString(const byte *uid, byte uidSize) {
  String resultado = "";
  for (byte i = 0; i < uidSize; i++) {
    if (uid[i] < 0x10) resultado += "0";
    resultado += String(uid[i], HEX);
    if (i < uidSize - 1) resultado += " ";
  }
  resultado.toUpperCase();
  return resultado;
}

void posicionarServo(int angulo, int duracionMs) {
  int pulsoUs = map(angulo, 0, 180, 544, 2400);
  int repeticiones = duracionMs / 20;

  for (int i = 0; i < repeticiones; i++) {
    digitalWrite(SERVO_PIN, HIGH);
    delayMicroseconds(pulsoUs);
    digitalWrite(SERVO_PIN, LOW);
    delayMicroseconds(20000 - pulsoUs);
  }
}

void sonarBuzzer(uint16_t frecuencia, uint16_t duracion) {
  ledcWriteTone(BUZZER_PIN, frecuencia);
  delay(duracion);
  ledcWriteTone(BUZZER_PIN, 0);
}
