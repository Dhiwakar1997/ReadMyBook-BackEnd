# Azure Container Apps Deployment Guide
## ReadMyBook Backend - FastAPI App & PDF Worker

### Infrastructure Overview
- **Subscription**: `rmb-dev`
- **Management Group**: `mg-project-rmb`
- **Location**: Central India
- **Resource Groups**:
  - `rmb-rg-app-dev` - Apps, servers, and computes (Container Apps, ACR, Container Apps Environment)
  - `rmb-rg-data-dev` - Data-related entities (PostgreSQL, Redis, Storage Account)
  - `rmb-rg-core` - Core entities (Key Vault, Log Analytics)

---

## Part 1: Deploy FastAPI App (main.py)

### Step 1: Set Up Variables

```bash
# Set subscription
az account set --subscription "rmb-dev"

# Resource Groups
RG_APP="rmb-rg-app-dev"
RG_DATA="rmb-rg-data-dev"
RG_CORE="rmb-rg-core"
LOCATION="centralindia"

# Container Registry (in app resource group)
ACR_NAME="rmbreadmybookdevacr"  # Must be globally unique, lowercase, alphanumeric

# Container Apps
ENVIRONMENT_NAME="rmb-dev-env"
API_APP_NAME="rmb-dev-api"
WORKER_APP_NAME="rmb-dev-worker"
```

### Step 2: Create Azure Container Registry

```bash
# Create ACR in app resource group
az acr create \
  --resource-group $RG_APP \
  --name $ACR_NAME \
  --sku Basic \
  --admin-enabled true \
  --location $LOCATION
```

### Step 3: Build and Push API Image

```bash
# Login to ACR
az acr login --name $ACR_NAME

# Build and push API image
az acr build \
  --registry $ACR_NAME \
  --image readmybook-api:latest \
  --file Dockerfile .
```

### Step 4: Create Data Resources (in rmb-rg-data-dev)

#### 4.1 PostgreSQL Database

```bash
# Variables
DB_SERVER_NAME="rmb-db-server-dev"
DB_NAME="readmybookdb"
DB_ADMIN_USER="rmbadmin"
DB_ADMIN_PASSWORD="<generate-strong-password>"  # Use Azure Key Vault or secure method

# Create PostgreSQL Flexible Server
az postgres flexible-server create \
  --resource-group $RG_DATA \
  --name $DB_SERVER_NAME \
  --location $LOCATION \
  --admin-user $DB_ADMIN_USER \
  --admin-password $DB_ADMIN_PASSWORD \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --version 14 \
  --storage-size 32 \
  --public-access 0.0.0.0

# Create database
az postgres flexible-server db create \
  --resource-group $RG_DATA \
  --server-name $DB_SERVER_NAME \
  --database-name $DB_NAME

# Get connection string
DB_CONNECTION_STRING="postgresql://${DB_ADMIN_USER}:${DB_ADMIN_PASSWORD}@${DB_SERVER_NAME}.postgres.database.azure.com:5432/${DB_NAME}?sslmode=require"
```

#### 4.2 Azure Cache for Redis

```bash
REDIS_NAME="rmb-redis-dev"

az redis create \
  --resource-group $RG_DATA \
  --name $REDIS_NAME \
  --location $LOCATION \
  --sku Basic \
  --vm-size c0

# Get Redis details
REDIS_HOST=$(az redis show \
  --resource-group $RG_DATA \
  --name $REDIS_NAME \
  --query hostName -o tsv)

REDIS_PORT=6380
REDIS_PASSWORD=$(az redis list-keys \
  --resource-group $RG_DATA \
  --name $REDIS_NAME \
  --query primaryKey -o tsv)
```

#### 4.3 Get Storage Account Connection String

```bash
# Assuming storage account already exists in rmb-rg-data-dev
# List storage accounts to find the name
az storage account list --resource-group $RG_DATA --query "[].name" -o tsv

# Set the storage account name (replace with actual name)
STORAGE_ACCOUNT_NAME="<your-storage-account-name>"

# Get connection string
STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
  --resource-group $RG_DATA \
  --name $STORAGE_ACCOUNT_NAME \
  --query connectionString -o tsv)

# Verify containers exist (create if needed)
az storage container create \
  --name pdf \
  --connection-string $STORAGE_CONNECTION_STRING \
  --auth-mode key

az storage container create \
  --name markdown \
  --connection-string $STORAGE_CONNECTION_STRING \
  --auth-mode key

az storage container create \
  --name image \
  --connection-string $STORAGE_CONNECTION_STRING \
  --auth-mode key
```

### Step 5: Create Container Apps Environment

```bash
# Create environment in app resource group
az containerapp env create \
  --name $ENVIRONMENT_NAME \
  --resource-group $RG_APP \
  --location $LOCATION
```

### Step 6: Set Up Key Vault (in rmb-rg-core)

```bash
KEY_VAULT_NAME="rmb-kv-dev"  # Must be globally unique

# Create Key Vault
az keyvault create \
  --name $KEY_VAULT_NAME \
  --resource-group $RG_CORE \
  --location $LOCATION

# Store secrets
az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "database-url" \
  --value "$DB_CONNECTION_STRING"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "storage-connection-string" \
  --value "$STORAGE_CONNECTION_STRING"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "redis-host" \
  --value "$REDIS_HOST"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "redis-port" \
  --value "$REDIS_PORT"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "redis-password" \
  --value "$REDIS_PASSWORD"

# Store application secrets (replace with actual values)
az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "secret-key" \
  --value "<generate-secret-key>"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "google-web-client-id" \
  --value "<your-google-client-id>"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "smtp-username" \
  --value "<your-smtp-username>"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "smtp-password" \
  --value "<your-smtp-password>"
```

### Step 7: Set Up Log Analytics (in rmb-rg-core)

```bash
LOG_ANALYTICS_WORKSPACE="rmb-logs-dev"

# Create Log Analytics workspace
az monitor log-analytics workspace create \
  --resource-group $RG_CORE \
  --workspace-name $LOG_ANALYTICS_WORKSPACE \
  --location $LOCATION

# Get workspace details
WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group $RG_CORE \
  --workspace-name $LOG_ANALYTICS_WORKSPACE \
  --query customerId -o tsv)

WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group $RG_CORE \
  --workspace-name $LOG_ANALYTICS_WORKSPACE \
  --query primarySharedKey -o tsv)

# Link to Container Apps Environment
az containerapp env update \
  --name $ENVIRONMENT_NAME \
  --resource-group $RG_APP \
  --logs-workspace-id $WORKSPACE_ID \
  --logs-workspace-key $WORKSPACE_KEY
```

### Step 8: Deploy FastAPI App

```bash
# Get ACR credentials
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)

# Create Container App for API
az containerapp create \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --environment $ENVIRONMENT_NAME \
  --image ${ACR_NAME}.azurecr.io/readmybook-api:latest \
  --registry-server ${ACR_NAME}.azurecr.io \
  --registry-username $ACR_USERNAME \
  --registry-password $ACR_PASSWORD \
  --target-port 8000 \
  --ingress external \
  --cpu 1.0 \
  --memory 2.0Gi \
  --min-replicas 1 \
  --max-replicas 5 \
  --env-vars \
    DATABASE_URL="secretref:database-url" \
    AZURE_CONNECTION_STRING="secretref:storage-connection-string" \
    SECRET_KEY="secretref:secret-key" \
    REDIS_HOST="secretref:redis-host" \
  --secrets \
    database-url=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/database-url \
    storage-connection-string=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/storage-connection-string \
    secret-key=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/secret-key \
    redis-host=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-host \
    redis-port=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-port \
    redis-password=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/redis-password \
    google-web-client-id=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/google-web-client-id \
    smtp-username=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/smtp-username \
    smtp-password=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/smtp-password \
  --env-vars \
    REDIS_PORT="secretref:redis-port" \
    REDIS_PASSWORD="secretref:redis-password" \
    GOOGLE_WEB_CLIENT_ID="secretref:google-web-client-id" \
    SMTP_USERNAME="secretref:smtp-username" \
    SMTP_PASSWORD="secretref:smtp-password"

# Get application URL
API_URL=$(az containerapp show \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "API URL: https://$API_URL"
```

### Step 9: Configure Managed Identity for API

```bash
# Enable managed identity
az containerapp identity assign \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --system-assigned

# Get identity principal ID
IDENTITY_PRINCIPAL_ID=$(az containerapp show \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --query identity.principalId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name $KEY_VAULT_NAME \
  --object-id $IDENTITY_PRINCIPAL_ID \
  --secret-permissions get list

# Grant Storage Blob Data Contributor role
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG_DATA}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}"
```

---

## Part 2: Deploy PDF-to-MD Worker (worker.py)

### Step 1: Build and Push Worker Image

```bash
# Build and push worker image
az acr build \
  --registry $ACR_NAME \
  --image readmybook-worker:latest \
  --file Dockerfile.worker .
```

### Step 2: Create Storage Queue

```bash
QUEUE_NAME="pdf-to-md"

# Create queue in existing storage account
az storage queue create \
  --name $QUEUE_NAME \
  --connection-string $STORAGE_CONNECTION_STRING \
  --auth-mode key
```

### Step 3: Add Worker Secrets to Key Vault

```bash
# Store queue name and poll interval
az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "queue-name" \
  --value "$QUEUE_NAME"

az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name "poll-interval" \
  --value "5"
```

### Step 4: Deploy Worker Container App

```bash
# Create Container App for Worker
az containerapp create \
  --name $WORKER_APP_NAME \
  --resource-group $RG_APP \
  --environment $ENVIRONMENT_NAME \
  --image ${ACR_NAME}.azurecr.io/readmybook-worker:latest \
  --registry-server ${ACR_NAME}.azurecr.io \
  --registry-username $ACR_USERNAME \
  --registry-password $ACR_PASSWORD \
  --cpu 2.0 \
  --memory 4.0Gi \
  --min-replicas 1 \
  --max-replicas 3 \
  --env-vars \
    DATABASE_URL="secretref:database-url" \
    AZURE_CONNECTION_STRING="secretref:storage-connection-string" \
    QUEUE_NAME="secretref:queue-name" \
    POLL_INTERVAL="secretref:poll-interval" \
  --secrets \
    database-url=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/database-url \
    storage-connection-string=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/storage-connection-string \
    queue-name=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/queue-name \
    poll-interval=keyvaultref:https://${KEY_VAULT_NAME}.vault.azure.net/secrets/poll-interval
```

### Step 5: Configure Managed Identity for Worker

```bash
# Enable managed identity
az containerapp identity assign \
  --name $WORKER_APP_NAME \
  --resource-group $RG_APP \
  --system-assigned

# Get identity principal ID
WORKER_IDENTITY_PRINCIPAL_ID=$(az containerapp show \
  --name $WORKER_APP_NAME \
  --resource-group $RG_APP \
  --query identity.principalId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name $KEY_VAULT_NAME \
  --object-id $WORKER_IDENTITY_PRINCIPAL_ID \
  --secret-permissions get list

# Grant Storage Blob Data Contributor role
az role assignment create \
  --assignee $WORKER_IDENTITY_PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG_DATA}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}"

# Grant Storage Queue Data Contributor role
az role assignment create \
  --assignee $WORKER_IDENTITY_PRINCIPAL_ID \
  --role "Storage Queue Data Contributor" \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG_DATA}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}"
```

---

## Part 3: Post-Deployment Configuration

### Step 1: Configure Scaling

```bash
# Update API scaling
az containerapp update \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --min-replicas 2 \
  --max-replicas 10 \
  --scale-rule-name http-scale \
  --scale-rule-type http \
  --scale-rule-http-concurrency 100

# Update Worker scaling
az containerapp update \
  --name $WORKER_APP_NAME \
  --resource-group $RG_APP \
  --min-replicas 1 \
  --max-replicas 5
```

### Step 2: Add Health Check Endpoint

First, update `app.py` to include a health check endpoint:

```python
@app.get("/health")
def health_check():
    return {"status": "healthy"}
```

Then update the container app:

```bash
az containerapp update \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --health-probe-type HTTP \
  --health-probe-path /health \
  --health-probe-interval 10 \
  --health-probe-timeout 5
```

### Step 3: Configure CORS (if needed)

Update `app.py` to include CORS middleware if your frontend needs it:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure with specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Step 4: Verify Deployment

```bash
# Check API status
az containerapp show \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --query "properties.runningStatus"

# Check Worker status
az containerapp show \
  --name $WORKER_APP_NAME \
  --resource-group $RG_APP \
  --query "properties.runningStatus"

# View API logs
az containerapp logs show \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --follow

# View Worker logs
az containerapp logs show \
  --name $WORKER_APP_NAME \
  --resource-group $RG_APP \
  --follow
```

---

## Part 4: Update Container Apps (After Code Changes)

### Update API

```bash
# Rebuild and push new image
az acr build \
  --registry $ACR_NAME \
  --image readmybook-api:latest \
  --file Dockerfile .

# Update container app
az containerapp update \
  --name $API_APP_NAME \
  --resource-group $RG_APP \
  --image ${ACR_NAME}.azurecr.io/readmybook-api:latest
```

### Update Worker

```bash
# Rebuild and push new image
az acr build \
  --registry $ACR_NAME \
  --image readmybook-worker:latest \
  --file Dockerfile.worker .

# Update container app
az containerapp update \
  --name $WORKER_APP_NAME \
  --resource-group $RG_APP \
  --image ${ACR_NAME}.azurecr.io/readmybook-worker:latest
```

---

## Resource Summary

### rmb-rg-app-dev (Apps & Compute)
- Azure Container Registry: `rmbreadmybookacr`
- Container Apps Environment: `rmb-env`
- Container App (API): `rmb-api`
- Container App (Worker): `rmb-worker`

### rmb-rg-data-dev (Data)
- PostgreSQL Flexible Server: `rmb-db-server-dev`
- Database: `readmybookdb`
- Azure Cache for Redis: `rmb-redis-dev`
- Storage Account: `<your-storage-account-name>`
  - Containers: `pdf`, `markdown`, `image`
  - Queue: `pdf-conversion-queue`

### rmb-rg-core (Core Services)
- Key Vault: `rmb-kv-dev`
- Log Analytics Workspace: `rmb-logs-dev`

---

## Troubleshooting

### Check Container App Logs
```bash
az containerapp logs show --name $API_APP_NAME --resource-group $RG_APP --follow
az containerapp logs show --name $WORKER_APP_NAME --resource-group $RG_APP --follow
```

### Check Container App Status
```bash
az containerapp show --name $API_APP_NAME --resource-group $RG_APP --query "properties.runningStatus"
az containerapp show --name $WORKER_APP_NAME --resource-group $RG_APP --query "properties.runningStatus"
```

### Restart Container Apps
```bash
az containerapp revision restart --name $API_APP_NAME --resource-group $RG_APP
az containerapp revision restart --name $WORKER_APP_NAME --resource-group $RG_APP
```

### Verify Environment Variables
```bash
az containerapp show --name $API_APP_NAME --resource-group $RG_APP --query "properties.template.containers[0].env"
az containerapp show --name $WORKER_APP_NAME --resource-group $RG_APP --query "properties.template.containers[0].env"
```

---

## Next Steps

1. **Set up CI/CD Pipeline** - Automate builds and deployments
2. **Configure Custom Domain** - Add your domain to the API
3. **Set up Alerts** - Configure monitoring and alerting
4. **Database Migrations** - Ensure database schema is up to date
5. **Test End-to-End** - Verify PDF upload → Queue → Conversion → Storage workflow

