# Testing C2C Cleanup Script

## 🧪 Quick Test

Per testare lo script con i tuoi dati reali:

```bash
cd /workspaces/bticino_x8000_component/scripts
python3 cleanup_c2c_subscriptions.py
```

## 📋 Credenziali Necessarie

Ti serviranno:

### 1. Client ID, Secret, Subscription Key
Dalle tue configurazioni API Bticino.

### 2. Refresh Token
Puoi ottenerlo da Home Assistant:

**Metodo 1: Dai log di HA**
```bash
# Abilita debug logging in configuration.yaml
logger:
  logs:
    custom_components.bticino_x8000: debug

# Riavvia HA e cerca nei log:
grep "refresh_token" /config/home-assistant.log
```

**Metodo 2: Dal registry di HA**
```bash
cat /config/.storage/core.config_entries | grep -A 100 "bticino_x8000" | grep "refresh_token"
```

**Metodo 3: Dal container HA attivo**
```bash
docker exec homeassistant cat /config/.storage/core.config_entries | grep -A 100 "bticino_x8000"
```

## 🎯 Cosa Aspettarsi

### Scenario 1: Nessuna Subscription Fantasma
```
✅ Found 3 plant(s)
✅ Found 1 subscription(s)

🏠 HOME ASSISTANT SUBSCRIPTIONS (1):
[1] Subscription ID: abc123...
    Plant: Home Mattiols
    Endpoint: https://my.home-assistant.io/api/webhook/xyz
    Created: 2025-11-25 10:30:00

✅ No cleanup needed - only current active subscription found
```

### Scenario 2: Subscription Fantasma Trovata
```
✅ Found 3 plant(s)
✅ Found 3 subscription(s)

🏠 HOME ASSISTANT SUBSCRIPTIONS (3):
[1] Subscription ID: old123...  ← VECCHIA (da rimuovere)
    Plant: Home Mattiols
    Endpoint: https://192.168.1.100:8123/api/webhook/old
    Created: 2025-11-20 15:00:00

[2] Subscription ID: old456...  ← VECCHIA (da rimuovere)
    Plant: Home Mattiols
    Endpoint: https://old.domain.com/api/webhook/xyz
    Created: 2025-11-22 08:00:00

[3] Subscription ID: current...  ← ATTUALE (mantenere)
    Plant: Home Mattiols
    Endpoint: https://my.home-assistant.io/api/webhook/abc
    Created: 2025-11-25 10:30:00

🗑️  CLEANUP OPTIONS:
1. Delete ALL Home Assistant subscriptions
2. Delete subscriptions one by one (interactive)
3. Exit without deleting anything
```

### Scenario 3: Con Subscriptions di Altre App
```
✅ Found 3 plant(s)
✅ Found 4 subscription(s)

🏠 HOME ASSISTANT SUBSCRIPTIONS (2):
[HA subscriptions listed here]

⚠️  OTHER SUBSCRIPTIONS (2):
(These are NOT from Home Assistant addon - probably other apps)

[1] Subscription ID: app123...
    Plant: Home Mattiols
    Endpoint: https://app.bticino.com/webhook/xyz
    Created: 2025-11-15 08:00:00

[2] Subscription ID: other456...
    Plant: Home Mattiols
    Endpoint: https://ifttt.com/webhook/abc
    Created: 2025-10-01 12:00:00

⚠️  These will NOT be touched by cleanup!
```

## 🔍 Come Identificare le Subscription da Rimuovere

### Subscription da RIMUOVERE:
- ❌ URL con vecchio IP/dominio (es. `https://192.168.1.100`)
- ❌ URL con dominio cambiato (es. `https://old.domain.com`)
- ❌ Creata prima dell'ultima reinstallazione
- ❌ Endpoint non più valido

### Subscription da MANTENERE:
- ✅ URL corrente di Home Assistant
- ✅ Endpoint attivo e funzionante
- ✅ Creata di recente

### Subscription di ALTRE APP (NON TOCCARE):
- 🔒 URL senza `/api/webhook/`
- 🔒 Endpoint Bticino ufficiale
- 🔒 Altri servizi (IFTTT, etc.)

## 🧪 Test Sicuro

**Primo test - Solo visualizzazione:**
1. Esegui lo script
2. Scegli opzione `3` (Exit without deleting)
3. Verifica l'output
4. Identifica le subscription fantasma

**Secondo test - Rimozione selettiva:**
1. Riesegui lo script
2. Scegli opzione `2` (Interactive)
3. Elimina SOLO le subscription vecchie/fantasma
4. Mantieni quella attuale

**Terzo test - Verifica pulizia:**
1. Riesegui lo script
2. Dovresti vedere solo 1 subscription HA (quella attuale)
3. Se ne vedi 0 o altre vecchie, ripeti il cleanup

## ✅ Test di Successo

Dopo il cleanup, riavvia Home Assistant e verifica:

1. **Nessun errore 409:**
```bash
# Nei log NON dovrebbe più comparire:
# "add_c2c_subscription - Failed to subscribe C2C... status: 409"
```

2. **Subscription creata con successo:**
```bash
# Nei log dovrebbe comparire:
# "✅ C2C subscription created: <subscription-id>"
```

3. **Webhook funzionanti:**
```bash
# Cambia temperatura dall'app Bticino
# Verifica che HA si aggiorni in < 5 secondi
```

## 🐛 Troubleshooting

### "Failed to refresh token"
```bash
# Il refresh token è scaduto o invalido
# Soluzione: Ottieni un nuovo refresh token da HA
```

### "Failed to get plants"
```bash
# Credenziali errate o subscription key invalida
# Soluzione: Verifica le credenziali API
```

### "Failed to delete subscription"
```bash
# La subscription potrebbe essere già stata eliminata
# Soluzione: Riesegui lo script per verificare
```

## 📊 Output di Debug

Lo script produce output dettagliato. Copia tutto l'output per il debug:

```bash
python3 cleanup_c2c_subscriptions.py 2>&1 | tee cleanup_output.txt
```

Poi condividi `cleanup_output.txt` se hai problemi.

## 🎯 Prossimi Passi Dopo il Test

1. ✅ Script funziona correttamente
2. ✅ Identifica subscription fantasma
3. ✅ Rimozione selettiva funziona
4. 🔄 Implementare cleanup automatico nell'addon
5. 📝 Aggiornare documentazione release notes

---

**Nota**: Questo script è SICURO e NON può danneggiare le impostazioni del termostato, programmi, o temperature!

