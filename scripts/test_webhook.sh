#!/bin/bash
# Test if a webhook is still responding
# Usage: ./test_webhook.sh WEBHOOK_ID

if [ -z "$1" ]; then
    echo "Usage: $0 WEBHOOK_ID"
    echo "Example: $0 db0397c326c7c1f4d66139bbb71d35ec4aeaf211f55e157a6dbb9b0f7deb2166"
    exit 1
fi

WEBHOOK_ID="$1"
HA_URL="${HA_URL:-http://localhost:8123}"

echo "=========================================="
echo "🧪 Testing webhook: $WEBHOOK_ID"
echo "=========================================="
echo ""

# Test from localhost (internal)
echo "📡 Testing from localhost..."
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    "$HA_URL/api/webhook/$WEBHOOK_ID" \
    -H "Content-Type: application/json" \
    -d '{"test": "manual_test"}' 2>&1)

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

echo "HTTP Status: $HTTP_CODE"
echo "Response: $BODY"
echo ""

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Webhook is ACTIVE and responding"
    echo "⚠️  This webhook should be removed if the integration was deleted!"
else
    echo "❌ Webhook is NOT responding (might be already removed)"
fi

echo ""
echo "=========================================="
echo "To check Home Assistant logs:"
echo "  ha core logs | grep -i '$WEBHOOK_ID'"
echo "=========================================="

