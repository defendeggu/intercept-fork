#!/bin/bash
# INTERCEPT Elastic Stack Setup Script
# This script helps configure Elasticsearch index templates for INTERCEPT

set -e

ES_HOST="${ES_HOST:-localhost:9200}"
ES_USER="${ES_USER:-}"
ES_PASS="${ES_PASS:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}INTERCEPT Elastic Stack Setup${NC}"
echo "================================"
echo ""

# Build curl auth args if credentials provided
CURL_AUTH=""
if [ -n "$ES_USER" ] && [ -n "$ES_PASS" ]; then
    CURL_AUTH="-u $ES_USER:$ES_PASS"
fi

# Check Elasticsearch connection
echo -n "Checking Elasticsearch connection... "
if curl -s $CURL_AUTH "http://$ES_HOST" > /dev/null 2>&1; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
    echo "Cannot connect to Elasticsearch at $ES_HOST"
    echo "Make sure Elasticsearch is running and accessible."
    exit 1
fi

# Get Elasticsearch version
ES_VERSION=$(curl -s $CURL_AUTH "http://$ES_HOST" | grep -oP '"number"\s*:\s*"\K[^"]+' | head -1)
echo "Elasticsearch version: $ES_VERSION"
echo ""

# Create index template
echo -n "Creating index template 'intercept'... "

# Read template file and remove comments
TEMPLATE_FILE="$(dirname "$0")/elasticsearch/index-templates.json"
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo -e "${RED}FAILED${NC}"
    echo "Template file not found: $TEMPLATE_FILE"
    exit 1
fi

# Remove JSON comments (lines with "_comment") and apply template
TEMPLATE_BODY=$(grep -v '"_comment' "$TEMPLATE_FILE")

RESPONSE=$(curl -s -w "\n%{http_code}" $CURL_AUTH -X PUT "http://$ES_HOST/_index_template/intercept" \
    -H "Content-Type: application/json" \
    -d "$TEMPLATE_BODY")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
    echo "HTTP $HTTP_CODE: $BODY"
    exit 1
fi

# Create ILM policy (optional, for index lifecycle management)
echo -n "Creating ILM policy 'intercept-ilm-policy'... "

ILM_POLICY='{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_age": "7d",
            "max_size": "50gb"
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": {
            "number_of_shards": 1
          },
          "forcemerge": {
            "max_num_segments": 1
          }
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'

RESPONSE=$(curl -s -w "\n%{http_code}" $CURL_AUTH -X PUT "http://$ES_HOST/_ilm/policy/intercept-ilm-policy" \
    -H "Content-Type: application/json" \
    -d "$ILM_POLICY")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${YELLOW}SKIPPED${NC} (may already exist or ILM not available)"
fi

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Configure Logstash with: elastic/logstash/intercept-mqtt.conf"
echo "2. Enable MQTT in INTERCEPT web interface"
echo "3. Create Kibana index pattern: intercept-*"
echo ""
echo "See elastic/README.md for detailed instructions."
