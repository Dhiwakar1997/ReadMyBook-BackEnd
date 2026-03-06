#!/bin/bash

# Azure Container Apps Deployment Script
# ReadMyBook Backend - FastAPI App & PDF Worker

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SUBSCRIPTION="rmb-dev"
RG_APP="rmb-rg-app-dev"
RG_DATA="rmb-rg-data-dev"
RG_CORE="rmb-rg-core"
LOCATION="centralindia"

# Container Registry
ACR_NAME="rmbacrdev"  # Must be globally unique

# Container Apps
ENVIRONMENT_NAME="rmb-dev-env"
API_APP_NAME="rmb-ca-api-dev"
WORKER_APP_NAME="rmb-ca-worker-dev"

# Database
DB_SERVER_NAME="rmb-pg-db-dev"
DB_NAME="rmb-dev-db"
DB_ADMIN_USER="dbadmin"

# Redis
REDIS_NAME="rmb-redis-db-dev"

# Key Vault
KEY_VAULT_NAME="rmb-key-dev"  # Must be globally unique

# Log Analytics
LOG_ANALYTICS_WORKSPACE="rmb-logs-dev"

# Queue
QUEUE_NAME="pdf-to-md"

# echo -e "${GREEN}========================================${NC}"
# echo -e "${GREEN}ReadMyBook Backend Deployment Script${NC}"
# echo -e "${GREEN}========================================${NC}"

# # Set subscription
# echo -e "\n${YELLOW}Setting subscription to $SUBSCRIPTION...${NC}"
# az account set --subscription "$SUBSCRIPTION"
# SUBSCRIPTION_ID=$(az account show --query id -o tsv)
# echo -e "${GREEN}✓ Subscription set${NC}"

# # Function to check if resource exists
# check_resource_exists() {
#     local resource_type=$1
#     local resource_name=$2
#     local resource_group=$3
    
#     if [ "$resource_type" == "acr" ]; then
#         az acr show --name "$resource_name" --resource-group "$resource_group" &>/dev/null
#     elif [ "$resource_type" == "postgres" ]; then
#         az postgres flexible-server show --name "$resource_name" --resource-group "$resource_group" &>/dev/null
#     elif [ "$resource_type" == "redis" ]; then
#         az redis show --name "$resource_name" --resource-group "$resource_group" &>/dev/null
#     elif [ "$resource_type" == "keyvault" ]; then
#         az keyvault show --name "$resource_name" --resource-group "$resource_group" &>/dev/null
#     elif [ "$resource_type" == "loganalytics" ]; then
#         az monitor log-analytics workspace show --name "$resource_name" --resource-group "$resource_group" &>/dev/null
#     elif [ "$resource_type" == "containerappenv" ]; then
#         az containerapp env show --name "$resource_name" --resource-group "$resource_group" &>/dev/null
#     elif [ "$resource_type" == "containerapp" ]; then
#         az containerapp show --name "$resource_name" --resource-group "$resource_group" &>/dev/null
#     fi
# }

# # Step 1: Create Azure Container Registry
# echo -e "\n${YELLOW}Step 1: Creating Azure Container Registry...${NC}"
# if check_resource_exists "acr" "$ACR_NAME" "$RG_APP"; then
#     echo -e "${GREEN}✓ ACR $ACR_NAME already exists${NC}"
# else
#     az acr create \
#         --resource-group "$RG_APP" \
#         --name "$ACR_NAME" \
#         --sku Basic \
#         --admin-enabled true \
#         --location "$LOCATION"
#     echo -e "${GREEN}✓ ACR created${NC}"
# fi

# # Step 2: Build and Push API Image
# echo -e "\n${YELLOW}Step 2: Building and pushing API image...${NC}"
# az acr login --name "$ACR_NAME"
# az acr build \
#     --registry "$ACR_NAME" \
#     --image readmybook-api:latest \
#     --file Dockerfile .
# echo -e "${GREEN}✓ API image built and pushed${NC}"

# # Step 3: Build and Push Worker Image
# echo -e "\n${YELLOW}Step 3: Building and pushing Worker image...${NC}"
# az acr build \
#     --registry "$ACR_NAME" \
#     --image readmybook-worker:latest \
#     --file Dockerfile.worker .
# echo -e "${GREEN}✓ Worker image built and pushed${NC}"

# # Step 4: Create PostgreSQL Database
# echo -e "\n${YELLOW}Step 4: Setting up PostgreSQL Database...${NC}"
# if check_resource_exists "postgres" "$DB_SERVER_NAME" "$RG_DATA"; then
#     echo -e "${GREEN}✓ PostgreSQL server $DB_SERVER_NAME already exists${NC}"
#     DB_ADMIN_PASSWORD=$(az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name "db-admin-password" --query value -o tsv 2>/dev/null || echo "")
#     if [ -z "$DB_ADMIN_PASSWORD" ]; then
#         echo -e "${RED}⚠ Database password not found in Key Vault. Please set it manually.${NC}"
#         read -sp "Enter database admin password: " DB_ADMIN_PASSWORD
#         echo
#     fi
# else
#     echo -e "${YELLOW}Creating PostgreSQL server...${NC}"
#     read -sp "Enter database admin password: " DB_ADMIN_PASSWORD
#     echo
    
#     az postgres flexible-server create \
#         --resource-group "$RG_DATA" \
#         --name "$DB_SERVER_NAME" \
#         --location "$LOCATION" \
#         --admin-user "$DB_ADMIN_USER" \
#         --admin-password "$DB_ADMIN_PASSWORD" \
#         --sku-name Standard_B1ms \
#         --tier Burstable \
#         --version 14 \
#         --storage-size 32 \
#         --public-access 0.0.0.0
    
#     echo -e "${GREEN}✓ PostgreSQL server created${NC}"
# fi

# # Check if database exists
# DB_EXISTS=$(az postgres flexible-server db show \
#     --resource-group "$RG_DATA" \
#     --server-name "$DB_SERVER_NAME" \
#     --database-name "$DB_NAME" \
#     --query name -o tsv 2>/dev/null || echo "")

# if [ -z "$DB_EXISTS" ]; then
#     echo -e "${YELLOW}Creating database $DB_NAME...${NC}"
#     az postgres flexible-server db create \
#         --resource-group "$RG_DATA" \
#         --server-name "$DB_SERVER_NAME" \
#         --database-name "$DB_NAME"
#     echo -e "${GREEN}✓ Database created${NC}"
# else
#     echo -e "${GREEN}✓ Database $DB_NAME already exists${NC}"
# fi

# DB_CONNECTION_STRING="postgresql://${DB_ADMIN_USER}:${DB_ADMIN_PASSWORD}@${DB_SERVER_NAME}.postgres.database.azure.com:5432/${DB_NAME}?sslmode=require"

# # Step 5: Create Redis Cache
# echo -e "\n${YELLOW}Step 5: Setting up Redis Cache...${NC}"
# if check_resource_exists "redis" "$REDIS_NAME" "$RG_DATA"; then
#     echo -e "${GREEN}✓ Redis $REDIS_NAME already exists${NC}"
# else
#     az redis create \
#         --resource-group "$RG_DATA" \
#         --name "$REDIS_NAME" \
#         --location "$LOCATION" \
#         --sku Basic \
#         --vm-size c0
#     echo -e "${GREEN}✓ Redis created${NC}"
# fi

# REDIS_HOST=$(az redis show \
#     --resource-group "$RG_DATA" \
#     --name "$REDIS_NAME" \
#     --query hostName -o tsv)

# REDIS_PORT=6380
# REDIS_PASSWORD=$(az redis list-keys \
#     --resource-group "$RG_DATA" \
#     --name "$REDIS_NAME" \
#     --query primaryKey -o tsv)

# # Step 6: Get Storage Account
# echo -e "\n${YELLOW}Step 6: Configuring Storage Account...${NC}"
# STORAGE_ACCOUNTS=$(az storage account list --resource-group "$RG_DATA" --query "[].name" -o tsv)
# if [ -z "$STORAGE_ACCOUNTS" ]; then
#     echo -e "${RED}⚠ No storage account found in $RG_DATA. Please create one first.${NC}"
#     exit 1
# fi

# STORAGE_ACCOUNT_NAME=$(echo "$STORAGE_ACCOUNTS" | head -n 1)
# echo -e "${GREEN}✓ Using storage account: $STORAGE_ACCOUNT_NAME${NC}"

# STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
#     --resource-group "$RG_DATA" \
#     --name "$STORAGE_ACCOUNT_NAME" \
#     --query connectionString -o tsv)

# # Create containers if they don't exist
# for container in pdf markdown image; do
#     az storage container create \
#         --name "$container" \
#         --connection-string "$STORAGE_CONNECTION_STRING" \
#         --auth-mode key \
#         &>/dev/null || echo -e "${GREEN}✓ Container $container exists${NC}"
# done

# # Create queue
# az storage queue create \
#     --name "$QUEUE_NAME" \
#     --connection-string "$STORAGE_CONNECTION_STRING" \
#     --auth-mode key \
#     &>/dev/null || echo -e "${GREEN}✓ Queue $QUEUE_NAME exists${NC}"

# # Step 7: Create Key Vault
# echo -e "\n${YELLOW}Step 7: Setting up Key Vault...${NC}"
# if check_resource_exists "keyvault" "$KEY_VAULT_NAME" "$RG_CORE"; then
#     echo -e "${GREEN}✓ Key Vault $KEY_VAULT_NAME already exists${NC}"
# else
#     az keyvault create \
#         --name "$KEY_VAULT_NAME" \
#         --resource-group "$RG_CORE" \
#         --location "$LOCATION"
#     echo -e "${GREEN}✓ Key Vault created${NC}"
# fi

# # Store secrets in Key Vault
# echo -e "${YELLOW}Storing secrets in Key Vault...${NC}"
# az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "database-url" --value "$DB_CONNECTION_STRING" &>/dev/null || true
# az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "storage-connection-string" --value "$STORAGE_CONNECTION_STRING" &>/dev/null || true
# az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "redis-host" --value "$REDIS_HOST" &>/dev/null || true
# az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "redis-port" --value "$REDIS_PORT" &>/dev/null || true
# az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "redis-password" --value "$REDIS_PASSWORD" &>/dev/null || true
# az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "queue-name" --value "$QUEUE_NAME" &>/dev/null || true
# az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "poll-interval" --value "5" &>/dev/null || true

# # Check if other secrets exist, if not prompt
# if ! az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name "secret-key" &>/dev/null; then
#     echo -e "${YELLOW}Secret key not found. Generating one...${NC}"
#     SECRET_KEY=$(openssl rand -hex 32)
#     az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "secret-key" --value "$SECRET_KEY"
# fi

# if ! az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name "google-web-client-id" &>/dev/null; then
#     echo -e "${YELLOW}Google Web Client ID not found in Key Vault.${NC}"
#     read -p "Enter Google Web Client ID (or press Enter to skip): " GOOGLE_CLIENT_ID
#     if [ -n "$GOOGLE_CLIENT_ID" ]; then
#         az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "google-web-client-id" --value "$GOOGLE_CLIENT_ID"
#     fi
# fi

# if ! az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name "smtp-username" &>/dev/null; then
#     echo -e "${YELLOW}SMTP credentials not found in Key Vault.${NC}"
#     read -p "Enter SMTP username (or press Enter to skip): " SMTP_USER
#     if [ -n "$SMTP_USER" ]; then
#         read -sp "Enter SMTP password: " SMTP_PASS
#         echo
#         az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "smtp-username" --value "$SMTP_USER"
#         az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "smtp-password" --value "$SMTP_PASS"
#     fi
# fi

# echo -e "${GREEN}✓ Secrets stored in Key Vault${NC}"

# # Step 8: Create Log Analytics Workspace
# echo -e "\n${YELLOW}Step 8: Setting up Log Analytics...${NC}"
# if check_resource_exists "loganalytics" "$LOG_ANALYTICS_WORKSPACE" "$RG_CORE"; then
#     echo -e "${GREEN}✓ Log Analytics workspace $LOG_ANALYTICS_WORKSPACE already exists${NC}"
# else
#     az monitor log-analytics workspace create \
#         --resource-group "$RG_CORE" \
#         --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
#         --location "$LOCATION"
#     echo -e "${GREEN}✓ Log Analytics workspace created${NC}"
# fi

# WORKSPACE_ID=$(az monitor log-analytics workspace show \
#     --resource-group "$RG_CORE" \
#     --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
#     --query customerId -o tsv)

# WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
#     --resource-group "$RG_CORE" \
#     --workspace-name "$LOG_ANALYTICS_WORKSPACE" \
#     --query primarySharedKey -o tsv)

# # Step 9: Create Container Apps Environment
# echo -e "\n${YELLOW}Step 9: Creating Container Apps Environment...${NC}"
# if check_resource_exists "containerappenv" "$ENVIRONMENT_NAME" "$RG_APP"; then
#     echo -e "${GREEN}✓ Container Apps Environment $ENVIRONMENT_NAME already exists${NC}"
# else
#     az containerapp env create \
#         --name "$ENVIRONMENT_NAME" \
#         --resource-group "$RG_APP" \
#         --location "$LOCATION"
#     echo -e "${GREEN}✓ Container Apps Environment created${NC}"
# fi

# # Link Log Analytics
# az containerapp env update \
#     --name "$ENVIRONMENT_NAME" \
#     --resource-group "$RG_APP" \
#     --logs-workspace-id "$WORKSPACE_ID" \
#     --logs-workspace-key "$WORKSPACE_KEY" \
#     &>/dev/null || true

# # Step 10: Deploy API Container App
# echo -e "\n${YELLOW}Step 10: Deploying API Container App...${NC}"
# ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
# ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query passwords[0].value -o tsv)

# if check_resource_exists "containerapp" "$API_APP_NAME" "$RG_APP"; then
#     echo -e "${YELLOW}API Container App exists. Updating...${NC}"
#     az containerapp update \
#         --name "$API_APP_NAME" \
#         --resource-group "$RG_APP" \
#         --image "${ACR_NAME}.azurecr.io/readmybook-api:latest"
#     echo -e "${GREEN}✓ API Container App updated${NC}"
# else
#     az containerapp create \
#         --name "$API_APP_NAME" \
#         --resource-group "$RG_APP" \
#         --environment "$ENVIRONMENT_NAME" \
#         --image "${ACR_NAME}.azurecr.io/readmybook-api:latest" \
#         --registry-server "${ACR_NAME}.azurecr.io" \
#         --registry-username "$ACR_USERNAME" \
#         --registry-password "$ACR_PASSWORD" \
#         --target-port 8000 \
#         --ingress external \
#         --cpu 1.0 \
#         --memory 2.0Gi \
#         --min-replicas 1 \
#         --max-replicas 5 \
#         --secrets \
#             database-url=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/database-url \
#             storage-connection-string=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/storage-connection-string \
#             secret-key=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/secret-key \
#             redis-host=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-host \
#             redis-port=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-port \
#             redis-password=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-password \
#             google-web-client-id=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/google-web-client-id \
#             smtp-username=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/smtp-username \
#             smtp-password=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/smtp-password \
#         --env-vars \
#             DATABASE_URL="secretref:database-url" \
#             AZURE_CONNECTION_STRING="secretref:storage-connection-string" \
#             SECRET_KEY="secretref:secret-key" \
#             REDIS_HOST="secretref:redis-host" \
#             REDIS_PORT="secretref:redis-port" \
#             REDIS_PASSWORD="secretref:redis-password" \
#             GOOGLE_WEB_CLIENT_ID="secretref:google-web-client-id" \
#             SMTP_USERNAME="secretref:smtp-username" \
#             SMTP_PASSWORD="secretref:smtp-password"
#     echo -e "${GREEN}✓ API Container App created${NC}"
# fi

# # Enable managed identity for API
# echo -e "${YELLOW}Configuring managed identity for API...${NC}"
# az containerapp identity assign \
#     --name "$API_APP_NAME" \
#     --resource-group "$RG_APP" \
#     --system-assigned \
#     &>/dev/null || true

# IDENTITY_PRINCIPAL_ID=$(az containerapp show \
#     --name "$API_APP_NAME" \
#     --resource-group "$RG_APP" \
#     --query identity.principalId -o tsv)

# # Grant Key Vault access
# az keyvault set-policy \
#     --name "$KEY_VAULT_NAME" \
#     --object-id "$IDENTITY_PRINCIPAL_ID" \
#     --secret-permissions get list \
#     &>/dev/null || true

# # Grant Storage access
# az role assignment create \
#     --assignee "$IDENTITY_PRINCIPAL_ID" \
#     --role "Storage Blob Data Contributor" \
#     --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG_DATA}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}" \
#     &>/dev/null || true

# echo -e "${GREEN}✓ Managed identity configured for API${NC}"

# # Step 11: Deploy Worker Container App
# echo -e "\n${YELLOW}Step 11: Deploying Worker Container App...${NC}"
# if check_resource_exists "containerapp" "$WORKER_APP_NAME" "$RG_APP"; then
#     echo -e "${YELLOW}Worker Container App exists. Updating...${NC}"
#     az containerapp update \
#         --name "$WORKER_APP_NAME" \
#         --resource-group "$RG_APP" \
#         --image "${ACR_NAME}.azurecr.io/readmybook-worker:latest"
#     echo -e "${GREEN}✓ Worker Container App updated${NC}"
# else
#     az containerapp create \
#         --name "$WORKER_APP_NAME" \
#         --resource-group "$RG_APP" \
#         --environment "$ENVIRONMENT_NAME" \
#         --image "${ACR_NAME}.azurecr.io/readmybook-worker:latest" \
#         --registry-server "${ACR_NAME}.azurecr.io" \
#         --registry-username "$ACR_USERNAME" \
#         --registry-password "$ACR_PASSWORD" \
#         --cpu 2.0 \
#         --memory 4.0Gi \
#         --min-replicas 1 \
#         --max-replicas 3 \
#         --secrets \
#             database-url=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/database-url \
#             storage-connection-string=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/storage-connection-string \
#             queue-name=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/queue-name \
#             poll-interval=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/poll-interval \
#             redis-host=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-host \
#             redis-port=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-port \
#             redis-password=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-password \
#         --env-vars \
#             DATABASE_URL="secretref:database-url" \
#             AZURE_CONNECTION_STRING="secretref:storage-connection-string" \
#             QUEUE_NAME="secretref:queue-name" \
#             POLL_INTERVAL="secretref:poll-interval" \
#             REDIS_HOST="secretref:redis-host" \
#             REDIS_PORT="secretref:redis-port" \
#             REDIS_PASSWORD="secretref:redis-password"
#     echo -e "${GREEN}✓ Worker Container App created${NC}"
# fi

# # Enable managed identity for Worker
# echo -e "${YELLOW}Configuring managed identity for Worker...${NC}"
# az containerapp identity assign \
#     --name "$WORKER_APP_NAME" \
#     --resource-group "$RG_APP" \
#     --system-assigned \
#     &>/dev/null || true

# WORKER_IDENTITY_PRINCIPAL_ID=$(az containerapp show \
#     --name "$WORKER_APP_NAME" \
#     --resource-group "$RG_APP" \
#     --query identity.principalId -o tsv)

# # Grant Key Vault access
# az keyvault set-policy \
#     --name "$KEY_VAULT_NAME" \
#     --object-id "$WORKER_IDENTITY_PRINCIPAL_ID" \
#     --secret-permissions get list \
#     &>/dev/null || true

# # Grant Storage access
# az role assignment create \
#     --assignee "$WORKER_IDENTITY_PRINCIPAL_ID" \
#     --role "Storage Blob Data Contributor" \
#     --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG_DATA}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}" \
#     &>/dev/null || true

# az role assignment create \
#     --assignee "$WORKER_IDENTITY_PRINCIPAL_ID" \
#     --role "Storage Queue Data Contributor" \
#     --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG_DATA}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}" \
#     &>/dev/null || true

# echo -e "${GREEN}✓ Managed identity configured for Worker${NC}"

# # Get API URL
# API_URL=$(az containerapp show \
#     --name "$API_APP_NAME" \
#     --resource-group "$RG_APP" \
#     --query properties.configuration.ingress.fqdn -o tsv)

# echo -e "\n${GREEN}========================================${NC}"
# echo -e "${GREEN}Deployment Complete!${NC}"
# echo -e "${GREEN}========================================${NC}"
# echo -e "\n${YELLOW}API URL:${NC} https://$API_URL"
# echo -e "\n${YELLOW}Resources Deployed:${NC}"
# echo -e "  - API Container App: $API_APP_NAME"
# echo -e "  - Worker Container App: $WORKER_APP_NAME"
# echo -e "  - Container Registry: $ACR_NAME"
# echo -e "  - Database: $DB_SERVER_NAME/$DB_NAME"
# echo -e "  - Redis: $REDIS_NAME"
# echo -e "  - Storage: $STORAGE_ACCOUNT_NAME"
# echo -e "  - Key Vault: $KEY_VAULT_NAME"
# echo -e "\n${YELLOW}Next Steps:${NC}"
# echo -e "  1. Test the API: curl https://$API_URL/health"
# echo -e "  2. Check logs: az containerapp logs show --name $API_APP_NAME --resource-group $RG_APP --follow"
# echo -e "  3. Update secrets in Key Vault if needed"
# echo -e "\n"

