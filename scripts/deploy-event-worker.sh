#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Deploy event-worker container app to Azure Container Apps
#
# Uses Key Vault references (same pattern as rmb-ca-api-dev).
# System-assigned managed identity reads secrets from rmb-key-dev.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RESOURCE_GROUP="rmb-rg-app-dev"
ENVIRONMENT="rmb-dev-env"
ACR_NAME="rmbacrdev"
ACR_SERVER="rmbacrdev.azurecr.io"
IMAGE_NAME="readmybook-event-worker"
IMAGE_TAG="latest"
KEY_VAULT="rmb-key-dev"
KV_URL="https://rmb-key-dev.vault.azure.net/secrets"
APP_NAME="rmb-ca-event-worker-dev"

# ── 1. Store Kafka manage connection string in Key Vault ─────────────────────
# The event worker needs both Listen (consume) and Send (produce to DLQ).
# manage-policy has Listen+Send+Manage — already exists on rmb-eh-dev.
echo "Storing kafka-manage-connection-string in Key Vault..."
KAFKA_CONN=$(az eventhubs namespace authorization-rule keys list \
  --resource-group rmb-rg-data-dev \
  --namespace-name rmb-eh-dev \
  --name manage-policy \
  --query "primaryConnectionString" -o tsv)

az keyvault secret set \
  --vault-name "$KEY_VAULT" \
  --name kafka-manage-connection-string \
  --value "$KAFKA_CONN" \
  --output none

echo "Done."

# ── 2. Build & push image to ACR ────────────────────────────────────────────
echo "Building and pushing image to ACR..."
az acr build \
  --registry "$ACR_NAME" \
  --image "$IMAGE_NAME:$IMAGE_TAG" \
  --file Dockerfile.event-worker \
  .

# ── 3. Create the container app ─────────────────────────────────────────────
echo "Creating container app..."
az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT" \
  --image "$ACR_SERVER/$IMAGE_NAME:$IMAGE_TAG" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_NAME" \
  --min-replicas 1 \
  --max-replicas 1 \
  --cpu 0.5 \
  --memory 1Gi \
  --system-assigned \
  \
  --secrets \
    database-url="keyvaultref:$KV_URL/database-url,identityref:system" \
    redis-host="keyvaultref:$KV_URL/redis-host,identityref:system" \
    redis-port="keyvaultref:$KV_URL/redis-port,identityref:system" \
    redis-password="keyvaultref:$KV_URL/redis-password,identityref:system" \
    kafka-connection-string="keyvaultref:$KV_URL/kafka-manage-connection-string,identityref:system" \
    openai-api-key="keyvaultref:$KV_URL/openai-api-key,identityref:system" \
    smtp-username="keyvaultref:$KV_URL/smtp-username,identityref:system" \
    smtp-password="keyvaultref:$KV_URL/smtp-password,identityref:system" \
    qdrant-url="keyvaultref:$KV_URL/qdrant-url,identityref:system" \
    qdrant-key="keyvaultref:$KV_URL/qdrant-key,identityref:system" \
  \
  --env-vars \
    DATABASE_URL=secretref:database-url \
    REDIS_HOST=secretref:redis-host \
    REDIS_PORT=secretref:redis-port \
    REDIS_PASSWORD=secretref:redis-password \
    REDIS_SSL="true" \
    KAFKA_BROKERS="rmb-eh-dev.servicebus.windows.net:9093" \
    KAFKA_SECURITY_PROTOCOL="SASL_SSL" \
    KAFKA_SASL_MECHANISM="PLAIN" \
    KAFKA_SASL_USERNAME='$ConnectionString' \
    KAFKA_SASL_PASSWORD=secretref:kafka-connection-string \
    OPENAI_API_KEY=secretref:openai-api-key \
    SMTP_USERNAME=secretref:smtp-username \
    SMTP_PASSWORD=secretref:smtp-password \
    ENDPOINT="https://www.readmybook.online" \
    QDRANT_URL=secretref:qdrant-url \
    QDRANT_KEY=secretref:qdrant-key \
    POPULAR_USER_THRESHOLD="100000"

# ── 4. Grant Key Vault access to the new app's managed identity ──────────────
echo "Granting Key Vault access to managed identity..."
PRINCIPAL_ID=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "identity.principalId" -o tsv)

az keyvault set-policy \
  --name "$KEY_VAULT" \
  --object-id "$PRINCIPAL_ID" \
  --secret-permissions get list \
  --output none

echo ""
echo "============================================="
echo " Deployed: $APP_NAME"
echo "============================================="
echo ""
echo "Verify:"
echo "  az containerapp show -n $APP_NAME -g $RESOURCE_GROUP -o table"
echo "  az containerapp logs show -n $APP_NAME -g $RESOURCE_GROUP --follow"
echo ""
echo "If the app fails to start with Key Vault errors, wait 1-2 min"
echo "for the managed identity permission to propagate, then restart:"
echo "  az containerapp revision restart -n $APP_NAME -g $RESOURCE_GROUP --revision \$(az containerapp revision list -n $APP_NAME -g $RESOURCE_GROUP --query '[0].name' -o tsv)"
