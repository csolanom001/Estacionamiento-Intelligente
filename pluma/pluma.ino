#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// =====================================================
// PINES RFID RC522 (ESP-WROOM-32D) - BUS VSPI NATIVO
// IMPORTANTE: ALIMENTAR EXCLUSIVAMENTE A 3.3V
// =====================================================
#define SS_PIN    5   // SDA -> GPIO 5
#define RST_PIN   27  // RST -> GPIO 27
#define SCK_PIN   18  // SCK -> GPIO 18 (VSPI nativo)
#define MISO_PIN  19  // MISO -> GPIO 19 (VSPI nativo)
#define MOSI_PIN  23  // MOSI -> GPIO 23 (VSPI nativo)

// =====================================================
// PINES SENSOR ULTRASONICO HC-SR04
// =====================================================
#define TRIG_PIN  32  // Trig -> GPIO 32
#define ECHO_PIN  35  // Echo -> GPIO 35

// Umbral de detección del cajón (en cm)
#define DISTANCIA_UMBRAL_CM  10

// =====================================================
// PINES INDICADORES Y SERVO
// =====================================================
#define LED_ROJO    12  // GPIO 12 -> LED rojo
#define LED_VERDE   13  // GPIO 13 -> LED verde
#define BUZZER_PIN  2   // GPIO 2  -> Buzzer
#define SERVO_PIN   4   // GPIO 4  -> Señal del Servo

// I2C (Display LCD):
// SDA -> GPIO 21
// SCL -> GPIO 22

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
// TARJETAS AUTORIZADAS
// =====================================================
byte UIDS_AUTORIZADOS[][4] = {
  {0x6C, 0xD3, 0xF5, 0x37}, // Llavero azul nuevo RC522
  {0xE1, 0x91, 0xE9, 0xBE}, // Tarjeta blanca MIFARE
  {0x83, 0xCF, 0x7A, 0x28},
  {0xA3, 0x6C, 0x9F, 0x14},
  {0x09, 0xB8, 0x95, 0x80}
};

const byte CANTIDAD_UIDS = sizeof(UIDS_AUTORIZADOS) / sizeof(UIDS_AUTORIZADOS[0]);

// Variables de estado
bool lugarOcupado = false;
long distanciaActualCm = 999;
unsigned long ultimaLecturaUltrasonico = 0;
unsigned long ultimoReporteTelemetria = 0;

// Prototipos
bool tarjetaAutorizada(const byte *uidLeido, byte uidSize);
void imprimirUID(const byte *uid, byte uidSize);
void accesoConcedido();
void accesoDenegado();
void sonarBuzzer(uint16_t frecuencia, uint16_t duracion);
void posicionarServo(int angulo, int duracionMs);
long medirDistanciaCm();
void actualizarPantallaInicio();
void rearmarLectorRFID();

// =====================================================
// SETUP
// =====================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  // 1. Inicializar LCD I2C
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Iniciando...");

  // 2. Pines de salida y entrada
  pinMode(LED_ROJO, OUTPUT);
  pinMode(LED_VERDE, OUTPUT);
  pinMode(SERVO_PIN, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  digitalWrite(LED_ROJO, LOW);
  digitalWrite(LED_VERDE, LOW);
  digitalWrite(SERVO_PIN, LOW);
  digitalWrite(TRIG_PIN, LOW);

  // 3. Buzzer (LEDC ESP32 Core 3.x)
  ledcAttach(BUZZER_PIN, BUZZER_FRECUENCIA, BUZZER_RESOLUCION);
  ledcWriteTone(BUZZER_PIN, 0);

  // 4. Ubicar pluma en reposo (cerrada)
  posicionarServo(ANGULO_CERRADO, 400);

  // 5. Iniciar SPI y RFID (VSPI a 3.3V)
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

  Serial.println(F("======================================="));
  Serial.println(F(" ACCESO Y MONITOREO DE ESTACIONAMIENTO"));
  Serial.println(F(" - Lector RC522 listo en VSPI (3.3V)"));
  Serial.println(F(" - Respaldo Serial: '1' autoriza, '0' deniega"));
  Serial.println(F("======================================="));

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
// LOOP
// =====================================================
void loop() {
  // 1. Monitoreo periódico del sensor ultrasónico cada 500 ms
  if (millis() - ultimaLecturaUltrasonico > 500) {
    ultimaLecturaUltrasonico = millis();
    distanciaActualCm = medirDistanciaCm();
    bool estadoAnterior = lugarOcupado;

    // Se detecta presencia si hay objeto dentro del rango válido
    if (distanciaActualCm > 0 && distanciaActualCm <= DISTANCIA_UMBRAL_CM) {
      lugarOcupado = true;
    } else {
      lugarOcupado = false;
    }

    // Refrescar pantalla si cambió el estado del cajón
    if (estadoAnterior != lugarOcupado) {
      actualizarPantallaInicio();
      Serial.print(F("[HC-SR04] DIST: "));
      Serial.print(distanciaActualCm);
      Serial.print(F(" CM | ESTADO: "));
      Serial.println(lugarOcupado ? F("OCUPADO") : F("LIBRE"));
    }
  }

  // 2. Envío periódico de telemetría a consola Serial cada 2 segundos
  if (millis() - ultimoReporteTelemetria > 2000) {
    ultimoReporteTelemetria = millis();
    Serial.print(F("[TELEMETRIA] DIST: "));
    Serial.print(distanciaActualCm);
    Serial.print(F(" | CAJON: "));
    Serial.println(lugarOcupado ? F("OCUPADO") : F("LIBRE"));
    rearmarLectorRFID();
  }

  // 3. MODO DE RESPALDO POR CONSOLA SERIAL ('1' autoriza, '0' deniega)
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == '1') {
      Serial.println(F("\n[SERIAL] Comando '1' recibido -> Solicitando autorizacion..."));
      if (lugarOcupado) {
        Serial.println(F("ACCESO DENEGADO: Lugar actualmente ocupado."));
        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("Lugar Ocupado");
        lcd.setCursor(0, 1);
        lcd.print("Espere por favor");
        sonarBuzzer(500, 600);
        delay(2000);
        actualizarPantallaInicio();
      } else {
        accesoConcedido();
      }
      rearmarLectorRFID();
    } else if (cmd == '0') {
      Serial.println(F("\n[SERIAL] Comando '0' recibido -> Denegar acceso"));
      accesoDenegado();
      rearmarLectorRFID();
    }
  }

  // 4. Revisar lector RFID físico RC522 (si está conectado y soldado)
  if (!mfrc522.PICC_IsNewCardPresent()) return;
  if (!mfrc522.PICC_ReadCardSerial()) return;

  Serial.println();
  Serial.print(F("UID leido: "));
  imprimirUID(mfrc522.uid.uidByte, mfrc522.uid.size);

  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();

  if (tarjetaAutorizada(mfrc522.uid.uidByte, mfrc522.uid.size)) {
    if (lugarOcupado) {
      // Bloqueo por falta de espacio
      Serial.println(F("ACCESO DENEGADO: Lugar actualmente ocupado."));
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Lugar Ocupado");
      lcd.setCursor(0, 1);
      lcd.print("Espere por favor");
      sonarBuzzer(500, 600);
      delay(2000);
      actualizarPantallaInicio();
    } else {
      accesoConcedido();
    }
  } else {
    accesoDenegado();
  }

  rearmarLectorRFID();
  delay(300);
}

// =====================================================
// MEDICIÓN ULTRASÓNICA (HC-SR04)
// =====================================================
long medirDistanciaCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Tiempo de retorno en microsegundos (timeout de 25 ms para evitar bloqueos)
  long duracion = pulseIn(ECHO_PIN, HIGH, 25000);
  
  if (duracion == 0) return 999; // Fuera de rango o sin eco
  return duracion / 58;          // Conversión acústica a centímetros
}

// =====================================================
// INTERFAZ LCD
// =====================================================
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

// =====================================================
// VALIDACIÓN Y ACTUADORES
// =====================================================
bool tarjetaAutorizada(const byte *uidLeido, byte uidSize) {
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

void imprimirUID(const byte *uid, byte uidSize) {
  for (byte i = 0; i < uidSize; i++) {
    if (uid[i] < 0x10) Serial.print(F("0"));
    Serial.print(uid[i], HEX);
    if (i < uidSize - 1) Serial.print(F(" "));
  }
  Serial.println();
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

void accesoConcedido() {
  Serial.println(F("ACCESO CONCEDIDO: Abriendo pluma..."));

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

  // Abrir pluma a 90 grados
  posicionarServo(ANGULO_ABIERTO, 800);
  delay(3000);

  // Cerrar pluma a 0 grados
  Serial.println(F("Cerrando pluma..."));
  posicionarServo(ANGULO_CERRADO, 800);
  digitalWrite(LED_VERDE, LOW);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Hasta luego.");
  delay(2000);

  actualizarPantallaInicio();
  Serial.println(F("Sistema listo para otra tarjeta."));
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

void sonarBuzzer(uint16_t frecuencia, uint16_t duracion) {
  ledcWriteTone(BUZZER_PIN, frecuencia);
  delay(duracion);
  ledcWriteTone(BUZZER_PIN, 0);
}