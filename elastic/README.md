# INTERCEPT Elastic Stack Integration

This directory contains configuration files for integrating INTERCEPT with the Elastic Stack (Elasticsearch, Logstash, Kibana).

## Architecture

```
INTERCEPT → MQTT (Mosquitto) → Logstash → Elasticsearch → Kibana
```

## Prerequisites

1. **Mosquitto MQTT Broker**
   ```bash
   sudo apt install mosquitto mosquitto-clients
   sudo systemctl enable --now mosquitto
   ```

2. **Elasticsearch** (8.x recommended)
   ```bash
   # See: https://www.elastic.co/guide/en/elasticsearch/reference/current/install-elasticsearch.html
   ```

3. **Logstash** (8.x recommended)
   ```bash
   # See: https://www.elastic.co/guide/en/logstash/current/installing-logstash.html

   # Install MQTT input plugin
   /usr/share/logstash/bin/logstash-plugin install logstash-input-mqtt
   ```

4. **Kibana** (8.x recommended)
   ```bash
   # See: https://www.elastic.co/guide/en/kibana/current/install.html
   ```

## Setup Steps

### 1. Configure Mosquitto

Create user for Logstash:
```bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd logstash
sudo mosquitto_passwd /etc/mosquitto/passwd intercept
```

Add to `/etc/mosquitto/conf.d/intercept.conf`:
```conf
listener 1883 0.0.0.0
allow_anonymous false
password_file /etc/mosquitto/passwd
```

Restart Mosquitto:
```bash
sudo systemctl restart mosquitto
```

### 2. Create Elasticsearch Index Template

```bash
# Load index template
curl -X PUT "localhost:9200/_index_template/intercept" \
  -H "Content-Type: application/json" \
  -d @elasticsearch/index-templates.json
```

### 3. Configure Logstash

Copy pipeline configuration:
```bash
sudo cp logstash/intercept-mqtt.conf /etc/logstash/conf.d/
```

Set environment variables in `/etc/default/logstash`:
```bash
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USER=logstash
MQTT_PASS=your_password
ES_HOST=localhost:9200
ES_USER=
ES_PASS=
```

Restart Logstash:
```bash
sudo systemctl restart logstash
```

### 4. Configure INTERCEPT

1. Open INTERCEPT web interface
2. Click the MQTT button in the navigation bar (flag icon)
3. Configure broker connection:
   - Host: localhost
   - Port: 1883
   - Username: intercept
   - Password: your_password
4. Enable desired topics
5. Save settings

### 5. Create Kibana Index Patterns

1. Open Kibana (http://localhost:5601)
2. Go to Stack Management → Index Patterns
3. Create pattern: `intercept-*`
4. Set time field: `@timestamp`

## MQTT Topics

| Decoder | Topic | Description |
|---------|-------|-------------|
| Pager | `intercept/pocsag` | POCSAG/FLEX pager messages |
| ADS-B | `intercept/adsb` | Aircraft tracking data |
| ACARS | `intercept/acars` | Aviation messaging |
| APRS | `intercept/aprs` | Amateur radio position reports |
| 433MHz | `intercept/sensor` | ISM band sensor data |
| Meters | `intercept/rtlamr` | Utility meter readings |

## Index Naming

Indices are created daily with the pattern:
- `intercept-pocsag-YYYY.MM.DD`
- `intercept-adsb-YYYY.MM.DD`
- `intercept-acars-YYYY.MM.DD`
- `intercept-aprs-YYYY.MM.DD`
- `intercept-sensor-YYYY.MM.DD`
- `intercept-rtlamr-YYYY.MM.DD`

## Kibana Visualizations

Create visualizations for:

### Pager Dashboard
- Message count over time
- Top addresses
- Protocol distribution (POCSAG vs FLEX)
- Message word cloud

### ADS-B Dashboard
- Aircraft map (geo_point)
- Altitude histogram
- Squawk code distribution
- Aircraft type breakdown
- Flight path trails

### ACARS Dashboard
- Message count by airline
- Message label distribution
- Signal level histogram

### APRS Dashboard
- Station map (geo_point)
- Packet type distribution
- Weather data (if available)

### 433MHz Sensor Dashboard
- Temperature over time
- Humidity trends
- Device model distribution
- Battery status

### Meter Dashboard
- Consumption over time
- Meter type distribution
- Unique meter count

## Troubleshooting

### No data in Elasticsearch

1. Check INTERCEPT MQTT status (should show "Connected")
2. Verify Mosquitto is receiving messages:
   ```bash
   mosquitto_sub -h localhost -u intercept -P password -t "intercept/#" -v
   ```
3. Check Logstash logs:
   ```bash
   sudo journalctl -u logstash -f
   ```

### Connection refused errors

1. Verify Mosquitto is running:
   ```bash
   sudo systemctl status mosquitto
   ```
2. Check firewall allows port 1883

### Index template not applied

Re-apply template:
```bash
curl -X PUT "localhost:9200/_index_template/intercept" \
  -H "Content-Type: application/json" \
  -d @elasticsearch/index-templates.json
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_HOST` | localhost | MQTT broker hostname |
| `MQTT_PORT` | 1883 | MQTT broker port |
| `MQTT_USER` | (empty) | MQTT username |
| `MQTT_PASS` | (empty) | MQTT password |
| `ES_HOST` | localhost:9200 | Elasticsearch host |
| `ES_USER` | (empty) | Elasticsearch username |
| `ES_PASS` | (empty) | Elasticsearch password |
