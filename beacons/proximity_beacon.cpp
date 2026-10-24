// ESP32 BLE mesh beacon
// Each board advertises as BEACON-<id> AND scans for the other beacons.
// The signal strength (RSSI) it hears from each peer is packed into its own
// advertisement, so a Raspberry Pi can read the beacon-to-beacon signal matrix.
//
// Flash to each ESP32, changing BEACON_ID to 1, 2, 3.
// Board: ESP32 Dev Module (arduino-esp32 core 3.x, built-in BLE library).
//
// Advertised manufacturer data (company ID 0xFFFF = test/unassigned):
//   [0xFF 0xFF] ['B'] [my id] [rssi to beacon 1] ... [rssi to beacon MAX_BEACONS]
//   rssi bytes are signed dBm; 127 = not heard / self.

#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

#define BEACON_ID    3     // <-- change per board: 1, 2, 3
#define MAX_BEACONS  8     // room for up to 8 beacons in the payload
#define STALE_MS     5000  // forget a peer not heard for this long
#define EMA_ALPHA    0.3f  // smoothing: lower = smoother but slower

static float    ema[MAX_BEACONS];
static uint32_t lastSeen[MAX_BEACONS];   // 0 = never seen
static char     name[16];
static BLEAdvertising *adv;
static BLEScan *scan;

class PeerCallback : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    if (!d.haveName()) return;
    String n = d.getName();
    if (!n.startsWith("BEACON-")) return;
    int id = n.substring(7).toInt();
    if (id < 1 || id > MAX_BEACONS || id == BEACON_ID) return;

    int i = id - 1;
    float r = d.getRSSI();
    uint32_t now = millis();
    if (lastSeen[i] == 0 || now - lastSeen[i] > STALE_MS) ema[i] = r;  // fresh start
    else ema[i] = ema[i] * (1 - EMA_ALPHA) + r * EMA_ALPHA;
    lastSeen[i] = now;
  }
};

void updateAdvert() {
  // Manufacturer data; no byte may be 0 (Arduino String), which holds since
  // RSSI is always negative and 127 marks "none".
  char m[4 + MAX_BEACONS + 1];
  m[0] = (char)0xFF;
  m[1] = (char)0xFF;
  m[2] = 'B';
  m[3] = (char)BEACON_ID;
  uint32_t now = millis();
  for (int i = 0; i < MAX_BEACONS; i++) {
    bool fresh = lastSeen[i] != 0 && now - lastSeen[i] <= STALE_MS;
    int v = fresh ? constrain((int)lroundf(ema[i]), -126, -1) : 127;
    m[4 + i] = (char)(int8_t)v;
  }
  m[4 + MAX_BEACONS] = 0;

  BLEAdvertisementData data;
  data.setFlags(0x06);
  data.setName(name);
  data.setManufacturerData(String(m));

  adv->stop();
  adv->setAdvertisementData(data);
  adv->start();
}

void setup() {
  Serial.begin(115200);
  snprintf(name, sizeof(name), "BEACON-%d", BEACON_ID);

  BLEDevice::init(name);
  BLEDevice::setPower(ESP_PWR_LVL_P9);

  adv = BLEDevice::getAdvertising();
  adv->setScanResponse(false);
  adv->setMinInterval(0xA0);   // 100 ms
  adv->setMaxInterval(0xA0);

  scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new PeerCallback(), true);  // true = report every packet
  scan->setActiveScan(false);
  scan->setInterval(160);      // 100 ms
  scan->setWindow(80);         // listen 50% of the time, leaves room for advertising

  updateAdvert();
  Serial.printf("Running as %s\n", name);
}

void loop() {
  scan->start(1, false);       // scan for 1 s (blocking)
  scan->clearResults();
  updateAdvert();

  // Debug output
  Serial.printf("%s hears:", name);
  for (int i = 0; i < MAX_BEACONS; i++) {
    if (i + 1 == BEACON_ID || lastSeen[i] == 0 || millis() - lastSeen[i] > STALE_MS) continue;
    Serial.printf("  B%d=%.0f", i + 1, ema[i]);
  }
  Serial.println();
}