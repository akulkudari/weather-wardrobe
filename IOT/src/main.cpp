#include "ECE140_WIFI.h"
#include "ECE140_MQTT.h"
#include "SFE_BMP180.cpp"
#include "WiFi.h"

// MQTT client - using descriptive client ID and topic


/*
#define CLIENT_ID "esp32-sensors"
#define TOPIC_PREFIX "pineapple/ece140/sensors"
*/
const char* client_id = CLIENT_ID;
const char* topic_prefix = TOPIC_PREFIX;

ECE140_MQTT mqtt(CLIENT_ID, TOPIC_PREFIX);
ECE140_WIFI wifi;
SFE_BMP180 bmp;

// WiFi credentials

const char* ucsdUsername = UCSD_USERNAME;
const char* ucsdPassword = UCSD_PASSWORD;
const char* wifiSsid = WIFI_SSID;
const char* nonEnterpriseWifiPassword = NON_ENTERPRISE_WIFI_PASSWORD;

void setup() {
    Serial.begin(115200);
    bmp.begin();
    //connect to wifi
    wifi.connectToWPAEnterprise(wifiSsid, ucsdUsername, ucsdPassword);

    //connect to MQTT
    Serial.println("[Main] Connecting to MQTT...");
    if(!mqtt.connectToBroker(1883)){
        Serial.println("[Main] failed to connect to MQTT broker");
    }

}

void loop() {
    //read in sensor data
    //start collecting temperature data
    String macAddress = WiFi.macAddress();
	bmp.startTemperature();
    //start collecting Pressure data with oversampling level = 0;
    bmp.startPressure(1);
    //declaration of temperature variable
    double temp_value = 0;
    //fetch temperature data, passing pointer to temperature variable
    bmp.getTemperature(temp_value);
    //declaration of pressure variable
    double pressure_value = 0;
    //fetch pressure value passing pointers to temperature and pressure value.
    bmp.getPressure(pressure_value, temp_value);
    //send data
    String payload = "{"
        "\"temperature\": " + String(temp_value) + ","
        "\"pressure\": " + String(pressure_value) + ","
        "\"mac_address\": \"" + macAddress + "\""
        "}";
    Serial.println("[Main] Publishing sensor data...");
    Serial.println(payload);
    mqtt.publishMessage("readings", payload);
    mqtt.loop();
    delay(1000);
}