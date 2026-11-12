#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 27

struct ConfigSPI {
  const char* nombre;
  int sda;
  int sck;
  int mosi;
  int miso;
};

// Probamos las combinaciones probables (incluyendo si los 2 cables cafés SDA y MISO quedaron intercambiados)
ConfigSPI configs[] = {
  {"1. Estándar (SDA=5, SCK=18, MOSI=23, MISO=19)",         5,  18, 23, 19},
  {"2. Cafés Invertidos (SDA=19, SCK=18, MOSI=23, MISO=5)", 19, 18, 23, 5},
  {"3. MOSI/MISO Invertidos (SDA=5, SCK=18, MOSI=19, MISO=23)", 5, 18, 19, 23},
  {"4. Cafés + Datos (SDA=19, SCK=18, MOSI=5, MISO=23)",    19, 18, 5,  23},
  {"5. SCK/SDA Invertidos (SDA=18, SCK=5, MOSI=23, MISO=19)", 18, 5, 23, 19},
  {"6. Orden inverso (SDA=23, SCK=19, MOSI=18, MISO=5)",    23, 19, 18, 5}
};

const int TOTAL_CONFIGS = sizeof(configs) / sizeof(configs[0]);

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println(F("=========================================================="));
  Serial.println(F(" PRUEBA OFICIAL MFRC522 (PROBANDO CABLES CAFÉS Y ORDEN SPI)"));
  Serial.println(F("=========================================================="));

  pinMode(RST_PIN, OUTPUT);
  digitalWrite(RST_PIN, HIGH);
}

void loop() {
  bool detectado = false;

  for (int i = 0; i < TOTAL_CONFIGS; i++) {
    ConfigSPI c = configs[i];

    pinMode(c.sda, OUTPUT);
    digitalWrite(c.sda, HIGH);

    SPI.begin(c.sck, c.miso, c.mosi, c.sda);
    delay(10);

    MFRC522 rfid(c.sda, RST_PIN);
    rfid.PCD_Init();
    delay(10);

    byte v = rfid.PCD_ReadRegister(rfid.VersionReg);

    if (v != 0x00 && v != 0xFF) {
      detectado = true;
      Serial.print(F("✅ "));
      Serial.print(c.nombre);
      Serial.print(F(" -> ¡RESPONDIÓ! VersionReg = 0x"));
      if (v < 0x10) Serial.print(F("0"));
      Serial.println(v, HEX);

      rfid.PCD_SetAntennaGain(rfid.RxGain_max);
      // Esperar 1.5 segundos buscando tarjeta en esta configuración ganadora
      unsigned long t0 = millis();
      while (millis() - t0 < 1500) {
        if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
          Serial.println();
          Serial.print(F("🎉💳 ¡¡TARJETA LEÍDA CON ÉXITO!! UID: "));
          for (byte b = 0; b < rfid.uid.size; b++) {
            if (rfid.uid.uidByte[b] < 0x10) Serial.print(F("0"));
            Serial.print(rfid.uid.uidByte[b], HEX);
            if (b < rfid.uid.size - 1) Serial.print(F(" "));
          }
          Serial.println();
          Serial.println(F("=========================================================="));
          rfid.PICC_HaltA();
          rfid.PCD_StopCrypto1();
          delay(1000);
        }
        delay(50);
      }
    }

    SPI.end();
  }

  if (!detectado) {
    Serial.println(F("❌ Ninguna de las 6 configuraciones SPI respondió (todas dieron 0x00/0xFF)."));
  }

  delay(500);
}
