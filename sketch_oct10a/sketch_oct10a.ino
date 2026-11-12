#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>

// =====================================================
// CONEXIONES DEL LECTOR RFID RC522 (ESP-WROOM-32D)
// =====================================================
#define SS_PIN    5   // SDA del RC522 -> GPIO 5
#define RST_PIN   22  // RST del RC522 -> GPIO 22
#define SCK_PIN   19  // SCK del RC522 -> GPIO 19
#define MISO_PIN  16  // MISO del RC522 -> GPIO 16
#define MOSI_PIN  23  // MOSI del RC522 -> GPIO 23

// =====================================================
// CONEXIONES DE LEDS, BUZZER Y SERVO
// =====================================================
#define LED_ROJO    12  // GPIO 12 -> LED rojo
#define LED_VERDE   13  // GPIO 13 -> LED verde
#define BUZZER_PIN  2   // GPIO 2  -> Positivo del Buzzer
#define SERVO_PIN   4   // GPIO 4  -> Cable de señal (naranja/amarillo) del Servo

// Parámetros PWM del buzzer (Core 3.x)
#define BUZZER_FRECUENCIA   1000
#define BUZZER_RESOLUCION   8

// Ángulos de la pluma
#define ANGULO_CERRADO   0   // Posición horizontal (abajo)
#define ANGULO_ABIERTO  90   // Posición vertical (arriba)

// =====================================================
// OBJETOS
// =====================================================
MFRC522 mfrc522(SS_PIN, RST_PIN);
Servo plumaServo;

// =====================================================
// TARJETAS AUTORIZADAS
// =====================================================
byte UIDS_AUTORIZADOS[][4] = {
  {0x83, 0xCF, 0x7A, 0x28},
  {0xA3, 0x6C, 0x9F, 0x14},
  {0x09, 0xB8, 0x95, 0x80}
};

const byte CANTIDAD_UIDS =
  sizeof(UIDS_AUTORIZADOS) / sizeof(UIDS_AUTORIZADOS[0]);

// =====================================================
// DECLARACION DE FUNCIONES
// =====================================================
bool tarjetaAutorizada(const byte *uidLeido, byte uidSize);
void imprimirUID(const byte *uid, byte uidSize);
void accesoConcedido();
void accesoDenegado();
void sonarBuzzer(uint16_t frecuencia, uint16_t duracion);
void moverPluma(int anguloDestino);

// =====================================================
// CONFIGURACION INICIAL
// =====================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Configurar los LED como salidas
  pinMode(LED_ROJO, OUTPUT);
  pinMode(LED_VERDE, OUTPUT);

  digitalWrite(LED_ROJO, LOW);
  digitalWrite(LED_VERDE, LOW);

  // Configurar Servo
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  plumaServo.setPeriodHertz(50); // Estándar 50Hz para servos
  plumaServo.attach(SERVO_PIN, 500, 2400); // Rango de pulsos en microsegundos
  plumaServo.write(ANGULO_CERRADO);        // Inicia cerrada

  // Configurar PWM para el buzzer (ESP32 Core 3.x)
  ledcAttach(BUZZER_PIN, BUZZER_FRECUENCIA, BUZZER_RESOLUCION);
  ledcWriteTone(BUZZER_PIN, 0);

  // Iniciar bus SPI
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);

  // Iniciar lector RFID RC522
  mfrc522.PCD_Init();
  delay(100);

  Serial.println();
  Serial.println(F("======================================="));
  Serial.println(F(" SISTEMA DE CONTROL DE ACCESO CON PLUMA"));
  Serial.println(F(" ESP32 ESP-WROOM-32D + RC522 + SERVO"));
  Serial.println(F("======================================="));
  Serial.println(F("Pluma en posicion CERRADA."));
  Serial.println(F("Acerque una tarjeta o llavero..."));

  // Bip corto de inicio
  sonarBuzzer(1200, 150);
}

// =====================================================
// PROGRAMA PRINCIPAL
// =====================================================
void loop() {
  // Revisar si hay una tarjeta nueva
  if (!mfrc522.PICC_IsNewCardPresent()) {
    return;
  }

  // Intentar leer el UID
  if (!mfrc522.PICC_ReadCardSerial()) {
    return;
  }

  Serial.println();
  Serial.print(F("UID leido: "));
  imprimirUID(mfrc522.uid.uidByte, mfrc522.uid.size);

  // Comprobar si el UID está autorizado
  if (tarjetaAutorizada(mfrc522.uid.uidByte, mfrc522.uid.size)) {
    accesoConcedido();
  } else {
    accesoDenegado();
  }

  // Finalizar comunicación con la tarjeta
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();

  delay(500);
}

// =====================================================
// COMPROBAR TARJETAS AUTORIZADAS
// =====================================================
bool tarjetaAutorizada(const byte *uidLeido, byte uidSize) {
  if (uidSize != 4) {
    return false;
  }

  for (byte tarjeta = 0; tarjeta < CANTIDAD_UIDS; tarjeta++) {
    bool coincide = true;
    for (byte i = 0; i < 4; i++) {
      if (uidLeido[i] != UIDS_AUTORIZADOS[tarjeta][i]) {
        coincide = false;
        break;
      }
    }
    if (coincide) {
      return true;
    }
  }

  return false;
}

// =====================================================
// MOSTRAR UID EN EL MONITOR SERIAL
// =====================================================
void imprimirUID(const byte *uid, byte uidSize) {
  for (byte i = 0; i < uidSize; i++) {
    if (uid[i] < 0x10) {
      Serial.print(F("0"));
    }
    Serial.print(uid[i], HEX);

    if (i < uidSize - 1) {
      Serial.print(F(" "));
    }
  }
  Serial.println();
}

// =====================================================
// ACCESO CONCEDIDO (ABRE PLUMA)
// =====================================================
void accesoConcedido() {
  Serial.println(F("ACCESO CONCEDIDO: Abriendo pluma..."));

  digitalWrite(LED_ROJO, LOW);
  digitalWrite(LED_VERDE, HIGH);

  // Dos bips de éxito
  sonarBuzzer(1400, 150);
  delay(80);
  sonarBuzzer(1800, 150);

  // Abrir la pluma
  plumaServo.write(ANGULO_ABIERTO);

  // Tiempo con la pluma arriba (3 segundos de paso)
  delay(3000);

  // Cerrar la pluma
  Serial.println(F("Cerrando pluma..."));
  plumaServo.write(ANGULO_CERRADO);

  // Apagar LED verde
  digitalWrite(LED_VERDE, LOW);
  Serial.println(F("Sistema listo para otra tarjeta."));
}

// =====================================================
// ACCESO DENEGADO (MANTIENE CERRADO)
// =====================================================
void accesoDenegado() {
  Serial.println(F("ACCESO DENEGADO: Pluma bloqueada."));

  // Asegurar que la pluma se quede cerrada
  plumaServo.write(ANGULO_CERRADO);

  digitalWrite(LED_VERDE, LOW);
  digitalWrite(LED_ROJO, HIGH);

  // Tono grave de error
  sonarBuzzer(400, 800);

  delay(1200);
  digitalWrite(LED_ROJO, LOW);

  Serial.println(F("Sistema listo para otra tarjeta."));
}

// =====================================================
// CONTROL DEL BUZZER (ESP32 Core 3.x)
// =====================================================
void sonarBuzzer(uint16_t frecuencia, uint16_t duracion) {
  ledcWriteTone(BUZZER_PIN, frecuencia);
  delay(duracion);
  ledcWriteTone(BUZZER_PIN, 0);
}