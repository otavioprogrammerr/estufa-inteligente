// Código Arduino para comunicação serial com Python e sensores umidade solo
// Sensores solo: A6, A5, A4 (entradas analógicas 6,5,4)
// Saídas digitais: 7, 9, 10, 11

#define PIN_TEMP_BAIXA 7
#define PIN_UMID 9
#define PIN_IRRIGACAO 10
#define PIN_TEMP_ALTA 11

// Sensores umidade solo (analógicos)
#define SENSOR_SOLO_1 A6
#define SENSOR_SOLO_2 A5
#define SENSOR_SOLO_3 A4

int umidadeSoloLimiar = 400; // ajustar conforme sensor (valor analógico, exemplo)

void setup() {
  Serial.begin(9600);

  pinMode(PIN_TEMP_BAIXA, OUTPUT);
  pinMode(PIN_UMID, OUTPUT);
  pinMode(PIN_IRRIGACAO, OUTPUT);
  pinMode(PIN_TEMP_ALTA, OUTPUT);

  digitalWrite(PIN_TEMP_BAIXA, LOW);
  digitalWrite(PIN_UMID, LOW);
  digitalWrite(PIN_IRRIGACAO, LOW);
  digitalWrite(PIN_TEMP_ALTA, LOW);
}

void loop() {
  // Verificar comandos do Python
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    // Comandos no formato:
    // "TEMP_BAIXA ON" ou "TEMP_BAIXA OFF" e similares
    if (cmd.startsWith("TEMP_BAIXA")) {
      digitalWrite(PIN_TEMP_BAIXA, cmd.endsWith("ON") ? HIGH : LOW);
    }
    else if (cmd.startsWith("TEMP_ALTA")) {
      digitalWrite(PIN_TEMP_ALTA, cmd.endsWith("ON") ? HIGH : LOW);
    }
    else if (cmd.startsWith("UMID")) {
      digitalWrite(PIN_UMID, cmd.endsWith("ON") ? HIGH : LOW);
    }
    else if (cmd.startsWith("IRRIGACAO")) {
      digitalWrite(PIN_IRRIGACAO, cmd.endsWith("ON") ? HIGH : LOW);
    }
  }

  // Ler sensores solo
  int solo1 = analogRead(SENSOR_SOLO_1);
  int solo2 = analogRead(SENSOR_SOLO_2);
  int solo3 = analogRead(SENSOR_SOLO_3);

  // Enviar dados para Python no formato: "SOLO:valor1,valor2,valor3\n"
  Serial.print("SOLO:");
  Serial.print(solo1);
  Serial.print(",");
  Serial.print(solo2);
  Serial.print(",");
  Serial.print(solo3);
  Serial.println();

  // Se solo estiver seco, ativar porta 10 (IRRIGACAO) só se modo tamagotchi OFF (Python controla isso)
  // Para isso, Python pode mandar comando para ativar IRRIGACAO quando necessário.

  delay(2000);
}
