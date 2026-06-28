#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>
#include <Preferences.h>  // EEPROM/Preferences storage to save settings

// ================= SYSTEM VARIABLES =================
Preferences preferences;

// Dynamic configuration parameters
float tempThreshold = 35.0;
int gasThreshold = 300;
int uploadInterval = 2;       // In seconds
int actuatorOverride = 0;     // 0 = OFF, 1 = ON (Manual Dashboard Trigger)

// ================= WIFI CONFIG =================
const char* ssid = "POCO X6 5G";
const char* password = "11111111";
const char* serverURL = "http://10.75.221.112:5000/upload";

// ================= OLED CONFIG =================
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// ================= DHT SENSOR =================
#define DHTPIN 4
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// ================= SENSOR PINS =================
#define MQ2_PIN 34
#define LDR_PIN 35
#define SOUND_PIN 32

#define TRIG_PIN 13
#define ECHO_PIN 14

#define RELAY_PIN 26
#define BUZZER_PIN 25

// ================= TOUCH SENSOR =================
#define TOUCH_PIN 15
int touchThreshold = 30;
bool alarmMuted = false;

// ================= WIFI CONNECT =================
void connectWiFi() {
  WiFi.begin(ssid, password);
  Serial.print("Connecting WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi Connected");
  Serial.println(WiFi.localIP());
}

// ================= READ ULTRASONIC =================
float readDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH);
  float distance = duration * 0.034 / 2;
  return distance;
}

// ================= SEND DATA & SYNC SETTINGS =================
void sendData(float temp, float hum, int gas, int light, int sound, float dist) {

  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(serverURL);
  http.addHeader("Content-Type", "application/json");

  // Construct data JSON
  String json = "{";
  json += "\"device_id\":\"ESP32_Env_Monitor\",";
  json += "\"temp\":" + String(temp) + ",";
  json += "\"humidity\":" + String(hum) + ",";
  json += "\"gas\":" + String(gas) + ",";
  json += "\"light\":" + String(light) + ",";
  json += "\"sound\":" + String(sound) + ",";
  json += "\"distance\":" + String(dist) + ",";
  json += "\"alarm_muted\":" + String(alarmMuted ? 1 : 0);
  json += "}";

  int code = http.POST(json);

  Serial.print("HTTP Code: ");
  Serial.println(code);

  // If upload succeeded, parse server response to load dashboard controls/thresholds
  if (code == 200) {
    String response = http.getString();
    Serial.println("Server Response: " + response);

    // Manual string parsing to read JSON settings cleanly
    int actuatorIdx = response.indexOf("\"actuator_status\":");
    if (actuatorIdx != -1) {
      int endIdx = response.indexOf(",", actuatorIdx);
      if (endIdx == -1) endIdx = response.indexOf("}", actuatorIdx);
      String val = response.substring(actuatorIdx + 18, endIdx);
      actuatorOverride = val.toInt();
    }

    int muteIdx = response.indexOf("\"alarm_muted\":");
    if (muteIdx != -1) {
      int endIdx = response.indexOf(",", muteIdx);
      if (endIdx == -1) endIdx = response.indexOf("}", muteIdx);
      String val = response.substring(muteIdx + 14, endIdx);
      int remoteMute = val.toInt();
      if (remoteMute != (alarmMuted ? 1 : 0)) {
        alarmMuted = (remoteMute == 1);
        preferences.putBool("alarm_muted", alarmMuted);
        Serial.println("Updated Alarm Muted state from server: " + String(alarmMuted ? "MUTED" : "ACTIVE"));
      }
    }

    int intervalIdx = response.indexOf("\"upload_interval\":");
    if (intervalIdx != -1) {
      int endIdx = response.indexOf(",", intervalIdx);
      if (endIdx == -1) endIdx = response.indexOf("}", intervalIdx);
      String val = response.substring(intervalIdx + 18, endIdx);
      int parsedInterval = val.toInt();
      if (parsedInterval != uploadInterval && parsedInterval > 0) {
        uploadInterval = parsedInterval;
        preferences.putInt("upload_int", uploadInterval);
        Serial.println("Saved new upload interval to Preferences: " + String(uploadInterval));
      }
    }

    int tempThreshIdx = response.indexOf("\"temp_threshold\":");
    if (tempThreshIdx != -1) {
      int endIdx = response.indexOf(",", tempThreshIdx);
      if (endIdx == -1) endIdx = response.indexOf("}", tempThreshIdx);
      String val = response.substring(tempThreshIdx + 17, endIdx);
      float parsedTemp = val.toFloat();
      if (parsedTemp != tempThreshold) {
        tempThreshold = parsedTemp;
        preferences.putFloat("temp_thresh", tempThreshold);
        Serial.println("Saved new temp threshold to Preferences: " + String(tempThreshold));
      }
    }

    int gasThreshIdx = response.indexOf("\"gas_threshold\":");
    if (gasThreshIdx != -1) {
      int endIdx = response.indexOf(",", gasThreshIdx);
      if (endIdx == -1) endIdx = response.indexOf("}", gasThreshIdx);
      String val = response.substring(gasThreshIdx + 16, endIdx);
      int parsedGas = val.toInt();
      if (parsedGas != gasThreshold) {
        gasThreshold = parsedGas;
        preferences.putInt("gas_thresh", gasThreshold);
        Serial.println("Saved new gas threshold to Preferences: " + String(gasThreshold));
      }
    }
  }

  http.end();
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);

  dht.begin();

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED Failed");
    while (true);
  }

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(WHITE);

  // Initialize NVS storage and reload saved configs
  preferences.begin("iot-settings", false);
  tempThreshold = preferences.getFloat("temp_thresh", 35.0);
  gasThreshold = preferences.getInt("gas_thresh", 300);
  uploadInterval = preferences.getInt("upload_int", 2);
  alarmMuted = preferences.getBool("alarm_muted", false);

  Serial.println("--- RELOADED CONFIGURATIONS ---");
  Serial.println("Temp Threshold: " + String(tempThreshold));
  Serial.println("Gas Threshold: " + String(gasThreshold));
  Serial.println("Upload Interval: " + String(uploadInterval));
  Serial.println("Alarm Muted: " + String(alarmMuted ? "MUTED" : "ACTIVE"));

  connectWiFi();
}

// ================= LOOP =================
void loop() {

  // ===== TOUCH SENSOR =====
  int touchValue = touchRead(TOUCH_PIN);

  if (touchValue < touchThreshold) {
    alarmMuted = !alarmMuted;  // toggle mute
    Serial.println("TOUCH DETECTED - TOGGLE ALARM");
    delay(500);
  }

  // ===== SENSOR READINGS =====
  float temp = dht.readTemperature();
  float hum = dht.readHumidity();

  int gas = analogRead(MQ2_PIN);
  int lightRaw = analogRead(LDR_PIN);
  int light = 4095 - lightRaw;
  int sound = analogRead(SOUND_PIN);

  float distance = readDistance();

  // ===== SERIAL OUTPUT =====
  Serial.println("---- SENSOR DATA ----");
  Serial.println("Temp: " + String(temp));
  Serial.println("Humidity: " + String(hum));
  Serial.println("Gas: " + String(gas) + " (Limit: " + String(gasThreshold) + ")");
  Serial.println("Light: " + String(light));
  Serial.println("Sound: " + String(sound));
  Serial.println("Distance: " + String(distance));
  Serial.println("Touch: " + String(touchValue));
  Serial.println("Relay Override: " + String(actuatorOverride == 1 ? "ON" : "OFF"));

  // ===== OLED DISPLAY =====
  display.clearDisplay();
  
  bool isAlert = (gas > gasThreshold || temp >= tempThreshold);
  
  // Render status bar header
  if (isAlert) {
    // Blinking alarm banner alternating fill/outline styles
    if ((millis() / 500) % 2 == 0) {
      display.fillRect(0, 0, 128, 14, WHITE);
      display.setTextColor(BLACK);
    } else {
      display.drawRect(0, 0, 128, 14, WHITE);
      display.setTextColor(WHITE);
    }
    display.setTextSize(1);
    display.setCursor(8, 3);
    if (gas > gasThreshold && temp >= tempThreshold) {
      display.print("!! MULTI-HAZARD !!");
    } else if (gas > gasThreshold) {
      display.print("!! GAS LEAK !!");
    } else {
      display.print("!! OVERHEAT !!");
    }
  } else {
    display.fillRect(0, 0, 128, 14, WHITE);
    display.setTextColor(BLACK);
    display.setTextSize(1);
    display.setCursor(4, 3);
    display.print("SYSTEM SECURE");
    
    if (alarmMuted) {
      display.setCursor(85, 3);
      display.print("[MUTED]");
    }
  }
  
  // Set default colors for data cells
  display.setTextColor(WHITE);
  
  // Draw structural grid dividers
  display.drawFastHLine(0, 15, 128, WHITE);
  display.drawFastVLine(64, 16, 48, WHITE);
  display.drawFastHLine(0, 31, 128, WHITE);
  display.drawFastHLine(0, 47, 128, WHITE);
  
  // Cell 1: Temperature
  display.setCursor(4, 20);
  display.print("T: ");
  if (isnan(temp)) display.print("---");
  else display.print(String(temp, 1) + "C");
  
  // Cell 2: Humidity
  display.setCursor(68, 20);
  display.print("H: ");
  if (isnan(hum)) display.print("---");
  else display.print(String(hum, 0) + "%");
  
  // Cell 3: Gas
  display.setCursor(4, 35);
  display.print("G: ");
  display.print(String(gas));
  
  // Cell 4: Sound
  display.setCursor(68, 35);
  display.print("S: ");
  display.print(String(sound));
  
  // Cell 5: Distance
  display.setCursor(4, 51);
  display.print("D: ");
  if (distance > 400 || distance < 2) display.print("---");
  else display.print(String(distance, 0) + "cm");
  
  // Cell 6: Light
  display.setCursor(68, 51);
  display.print("L: ");
  display.print(String(light));
  
  display.display();

  // ===== ACTUATOR LOGIC =====
  // 1. Buzzer sounds if gas exceeds threshold OR temperature exceeds threshold (unless muted)
  if (!alarmMuted && (gas > gasThreshold || temp >= tempThreshold)) {
    // Pulse the buzzer to sound like a real warning siren (beep - beep - pause)
    digitalWrite(BUZZER_PIN, HIGH);
    delay(150);
    digitalWrite(BUZZER_PIN, LOW);
    delay(100);
    digitalWrite(BUZZER_PIN, HIGH);
    delay(150);
    digitalWrite(BUZZER_PIN, LOW);
  } else {
    digitalWrite(BUZZER_PIN, LOW);
  }

  // 2. Relay triggers if object is close (dist < 10) OR manual dashboard trigger is active
  if (distance < 10 || actuatorOverride == 1) {
    digitalWrite(RELAY_PIN, HIGH);
  } else {
    digitalWrite(RELAY_PIN, LOW);
  }

  // ===== SEND TO SERVER & SYNC =====
  sendData(temp, hum, gas, light, sound, distance);

  // Dynamic sleep period loaded from configurations
  delay(uploadInterval * 1000);
}
