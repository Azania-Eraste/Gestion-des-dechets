# SmartBin — Gestion Intelligente des Déchets Urbains

[![Status](https://img.shields.io/badge/status-active-brightgreen)]()
[![Flask](https://img.shields.io/badge/Flask-2.x-blue)]()
[![ESP32](https://img.shields.io/badge/Hardware-ESP32%2B%20HC--SR04-orange)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()

## 📋 Vue d'ensemble

**SmartBin** est une solution **IoT prototype** pour la supervision en temps réel du niveau de remplissage des poubelles urbaines. Un **ESP32** équipé d'un **capteur ultrasonique HC-SR04** mesure la distance jusqu'aux déchets, envoie les données via HTTP POST à un backend **Flask**, qui les diffuse en direct aux clients web via **Server-Sent Events (SSE)**.

## 🎯 Cas d'usage

- ✅ Optimisation des tournées de collecte des ordures
- ✅ Réduction du nombre de passages à vide
- ✅ Alertes automatiques (débordement imminents)
- ✅ Supervision en temps réel depuis un tableau de bord web
- ✅ Données structurées pour futur ML (prédiction de remplissage)

## 🏗️ Architecture

### Stack Technologique
- **Microcontrôleur**: ESP32 (WiFi, capteur HC-SR04)
- **Backend**: Python Flask 2.x
- **Temps réel**: Server-Sent Events (SSE) + fallback polling
- **Frontend**: HTML5 + CSS3 (Glassmorphism, responsive)
- **Concurrence**: Threading (thread-safe state via locks)

### Endpoints API

| Route | Méthode | Description |
|-------|---------|-------------|
| `/` | GET | Interface web (dashboard) |
| `/update` | POST | Reçoit JSON `{distance, message}` de l'ESP32 |
| `/data` | GET | Retourne l'état courant en JSON |
| `/stream` | GET | SSE — diffuse les mises à jour en temps réel |

## 🚀 Démarrage rapide

### Pré-requis
- Python 3.8+
- ESP32 + HC-SR04
- WiFi disponible

### Installation backend

```bash
cd Flask
python -m venv venv
```

Sur Windows :
```bash
venv\Scripts\activate
```

Sur macOS/Linux :
```bash
source venv/bin/activate
```

Installer les dépendances :
```bash
pip install flask flask-cors
```

Démarrer le serveur :
```bash
python app.py
```

Accéder au dashboard : `http://localhost:5000`

### Configuration ESP32

Pseudocode Arduino / PlatformIO pour l'ESP32 :

```cpp
#include <WiFi.h>
#include <HTTPClient.h>

const char* ssid = "VotreSSID";
const char* password = "VotreMotDePasse";
const char* server = "http://<SERVEUR_IP>:5000/update";

// Pins HC-SR04
const int TRIG_PIN = 32;
const int ECHO_PIN = 33;

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  
  // Connexion WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("WiFi connecté");
}

float measureDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  
  long duration = pulseIn(ECHO_PIN, HIGH);
  float distance = (duration * 0.034) / 2;  // cm
  return distance;
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    float distance = measureDistance();
    String message = (distance < 10) ? "deborde" : 
                     (distance < 25) ? "assez rempli" : "bon";
    
    HTTPClient http;
    http.begin(server);
    http.addHeader("Content-Type", "application/json");
    
    String json = "{\"distance\":" + String(distance, 1) + 
                  ",\"message\":\"" + message + "\"}";
    
    int httpCode = http.POST(json);
    Serial.println("POST " + String(httpCode) + " | " + json);
    
    http.end();
  }
  
  delay(5000);  // Intervalle envoi (5 secondes)
}
```

## ✨ Fonctionnalités

### Backend
✅ **Validation robuste** : vérification Content-Type, types, plages de valeurs  
✅ **Gestion des erreurs** : réponses JSON claires + logging structuré  
✅ **Thread-safe** : accès protégé à l'état global avec `threading.Lock()`  
✅ **Temps réel** : diffusion SSE instantanée vers tous les clients  
✅ **CORS optionnel** : support automatique si `flask-cors` installé  
✅ **Robustesse** : tolérant aux JSON malformés, données incomplètes  

### Frontend
✅ **Dashboard moderne** : design glassmorphism, animations fluides  
✅ **SSE prioritaire** : affichage temps réel < 100ms  
✅ **Fallback robuste** : polling 3s si SSE indisponible  
✅ **Responsive** : adapté mobile, tablet, desktop  
✅ **Indicateurs visuels** : statut (Normal/Attention/Critique), jauge remplissage, connexion  
✅ **Horodatage** : dernière mise à jour affichée  

## 📊 Exemple de flux

```
ESP32 (toutes les 5s)
  └─→ POST /update {"distance": 8.5, "message": "assez rempli"}
      └─→ Flask /update
          ├─ Valide JSON & types
          ├─ Enregistre distance=8.5, message="assez rempli"
          ├─ Diffuse via SSE à tous les clients connectés
          └─ Retourne 200 {"status": "success"}
              └─→ Navigateur (SSE EventSource)
                  └─→ Mise à jour DOM instantanée
```

## 🔒 Sécurité & Robustesse

| Aspect | Implémentation |
|--------|----------------|
| **JSON parsing** | `try/except` + `request.is_json` |
| **Types validés** | Distance numérique (0-10000 cm), message string |
| **État thread-safe** | `threading.Lock()` pour accès atomique |
| **Erreurs gérées** | JSON malformé, champs manquants, valeurs hors limites |
| **Logging** | `app.logger.info/warning/exception` |
| **CORS** | Optionnel (`flask-cors` si installé) |

## 🛠️ Améliorations futures

- [ ] **Authentification** : clé API simple pour `/update`
- [ ] **Persistance** : SQLite pour historique + alertes
- [ ] **Rate limiting** : protection contre abus
- [ ] **Notifications** : WebSocket ou SMS/email si débordement
- [ ] **Analytics** : graphiques historiques, prédictions ML
- [ ] **Géolocalisation** : multi-poubelles avec carte interactive
- [ ] **Tests unitaires** : couverture endpoint + validation
- [ ] **Docker** : conteneurisation pour déploiement facile

## 📝 Structure du projet

```
Flask/
├── app.py                    # Backend Flask principal
├── templates/
│   └── index.html           # Dashboard web moderne
├── requirements.txt         # Dépendances Python
├── README.md               # Ce fichier
└── venv/                   # Environnement virtuel
```

## 🧪 Tests manuels

### Test POST valide

```bash
curl -X POST http://localhost:5000/update \
  -H "Content-Type: application/json" \
  -d '{"distance": 15.3, "message": "bon"}'
```

Réponse attendue :
```json
{
  "status": "success"
}
```

### Test JSON malformé

```bash
curl -X POST http://localhost:5000/update \
  -H "Content-Type: application/json" \
  -d '{invalid json}'
```

Réponse attendue (400) :
```json
{
  "status": "error",
  "reason": "Malformed JSON"
}
```

### Test champs manquants

```bash
curl -X POST http://localhost:5000/update \
  -H "Content-Type: application/json" \
  -d '{"distance": 15.3}'
```

Réponse attendue (400) :
```json
{
  "status": "error",
  "reason": "Missing keys: distance and message required"
}
```

### Récupérer état courant

```bash
curl http://localhost:5000/data
```

Réponse attendue (200) :
```json
{
  "distance": 15.3,
  "message": "bon"
}
```

### Suivre le flux SSE

```bash
curl -N http://localhost:5000/stream
```

Affichage en temps réel :
```
data: {"distance": 15.3, "message": "bon"}

data: {"distance": 14.8, "message": "bon"}

: keep-alive

...
```

## 📄 Licence

MIT License — Libre d'utilisation et de modification.

## 👤 Auteur

Projet de soutenance — Gestion Intelligente des Déchets Urbains (2026)

---

**Statut**: ✅ Prototype fonctionnel — Prêt pour intégration production

**Questions/Feedback?** Ouvrez une issue sur le dépôt GitHub.
