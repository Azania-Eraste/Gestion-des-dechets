from flask import Flask, request, jsonify, render_template, Response, session, redirect, url_for
import threading
import math
import queue
import json
import time
import os
from functools import wraps

try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# --- CONFIGURATION ADMINISTRATEUR ---
ADMIN_PASSWORD = "admin123"  # À remplacer en production

def login_required(f):
    """Décorateur pour protéger les routes : redirige vers login si non authentifié."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'authenticated' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# BASE DE DONNÉES D'APPAREILLAGE (PROVISIONING)
# ==========================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'poubelles_config.json')

def load_db():
    """Charge la base depuis le fichier JSON local. Retourne un dict."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        app.logger.exception('Impossible de charger %s', CONFIG_FILE)
    return {}

def save_db(db_dict):
    """Sauvegarde le dict de configuration dans le fichier JSON local."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(db_dict, f, ensure_ascii=False, indent=2)
    except Exception:
        app.logger.exception('Impossible d\'écrire %s', CONFIG_FILE)

# Chargement initial de la base de données persistante
BASE_DE_DONNEES_MACS = load_db()

# Salle d'attente pour les MAC détectées mais non validées
macs_en_attente = set()

# --- CONFIGURATION MQTT ---
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

# Nouveaux Topics pour gérer la flotte
TOPIC_DEMANDE_APPAREILLAGE = "systeme/appareillage/demande"
TOPIC_DONNEES_POUBELLES = "abidjan/poubelles/niveau"

mqtt_client = None

try:
    from flask_cors import CORS
    CORS(app)
except Exception:
    pass

# L'état global stocke maintenant TOUTES les poubelles sous forme de dictionnaire de dictionnaires
donnees_actuelles = {} 
donnees_lock = threading.Lock()

# Historique des événements (max 500 entrées) pour traçabilité et stats
historique = []
historique_lock = threading.Lock()
MAX_HISTORIQUE = 500

clients = []
clients_lock = threading.Lock()

def add_to_history(bin_id, distance, message):
    """Enregistre un événement de changement dans l'historique."""
    with historique_lock:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        historique.append({
            'bin_id': bin_id,
            'distance': distance,
            'message': message,
            'timestamp': timestamp
        })
        # Garder seulement les MAX_HISTORIQUE dernières entrées
        if len(historique) > MAX_HISTORIQUE:
            historique.pop(0)

def register_client(q):
    with clients_lock:
        clients.append(q)

def unregister_client(q):
    with clients_lock:
        try:
            clients.remove(q)
        except ValueError:
            pass

def broadcast_update(data):
    text = json.dumps(data)
    with clients_lock:
        for q in list(clients):
            try:
                q.put_nowait(text)
            except Exception:
                try:
                    clients.remove(q)
                except Exception:
                    pass

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        app.logger.info('MQTT connecté au broker %s:%s', MQTT_HOST, MQTT_PORT)
        # S'abonner aux deux canaux vitaux du système
        client.subscribe(TOPIC_DEMANDE_APPAREILLAGE)
        client.subscribe(TOPIC_DONNEES_POUBELLES)
        print(f"✅ Serveur prêt. Écoute sur {TOPIC_DEMANDE_APPAREILLAGE} et {TOPIC_DONNEES_POUBELLES}", flush=True)
    else:
        app.logger.warning('MQTT connexion refusée, code: %s', reason_code)

def on_mqtt_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode('utf-8'))
        
        # CAS 1 : Un ESP32 vierge s'allume et demande qui il est
        if topic == TOPIC_DEMANDE_APPAREILLAGE:
            mac = payload.get('mac')
            if mac:
                print(f"📡 Demande d'appareillage reçue de la MAC : {mac}", flush=True)
                
                # On vérifie si la MAC est enregistrée dans notre base
                if mac in BASE_DE_DONNEES_MACS:
                    config = BASE_DE_DONNEES_MACS[mac]
                    topic_reponse = f"systeme/appareillage/config/{mac}"
                    
                    # On envoie la configuration sur le canal personnel de cet ESP32
                    client.publish(topic_reponse, json.dumps(config))
                    print(f"✅ Appareillage réussi : {mac} est maintenant {config['id']}", flush=True)
                else:
                    # MAC inconnue -> mettre en attente pour validation via l'interface web
                    if mac not in macs_en_attente:
                        macs_en_attente.add(mac)
                        print(f"🆕 Nouvel appareil détecté, MAC ajoutée en attente: {mac}", flush=True)
                    else:
                        print(f"ℹ️ MAC {mac} déjà en attente pour appareillage", flush=True)

        # CAS 2 : Une poubelle configurée envoie ses niveaux de déchets
        elif topic == TOPIC_DONNEES_POUBELLES:
            bin_id = payload.get('id')
            if bin_id and 'distance' in payload and 'message' in payload:
                
                # Mise à jour de la poubelle spécifique dans le dictionnaire global
                with donnees_lock:
                    donnees_actuelles[bin_id] = {
                        "distance": payload['distance'],
                        "message": payload['message'].strip().lower(),
                        "lat": payload.get('lat', 0.0),
                        "lng": payload.get('lng', 0.0),
                        "derniere_maj": time.strftime("%H:%M:%S") # Pratique pour l'interface web
                    }
                    snapshot = dict(donnees_actuelles)
                
                # Enregistrer dans l'historique
                add_to_history(bin_id, payload['distance'], payload['message'].strip().lower())
                    
                print(f"📥 [{bin_id}] -> Distance: {payload['distance']} cm | Statut: {payload['message']}", flush=True)
                broadcast_update(snapshot)
                
    except Exception as e:
        app.logger.exception(f"Erreur MQTT : {e}")

def init_mqtt_connection():
    global mqtt_client
    if mqtt is None:
        return
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message 
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        mqtt_client.loop_start()
    except Exception:
        app.logger.exception('Échec de connexion au broker MQTT')

# --- ROUTES FLASK ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            session['authenticated'] = True
            session.permanent = True
            print("✅ Administrateur connecté", flush=True)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Mot de passe incorrect")
    if 'authenticated' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/appareillage')
@login_required
def appareillage():
    return render_template('appareillage.html')

@app.route('/data', methods=['GET'])
def get_data():
    with donnees_lock:
        snapshot = dict(donnees_actuelles)
    return jsonify(snapshot)


# API pour gestion de l'appareillage (Frontend)
@app.route('/api/appareillage/en-attente', methods=['GET'])
@login_required
def api_appareillage_en_attente():
    return jsonify(list(macs_en_attente))


@app.route('/api/appareillage/valider', methods=['POST'])
@login_required
def api_appareillage_valider():
    data = request.get_json() or {}
    mac = data.get('mac')
    if not mac:
        return jsonify({'success': False, 'error': 'Paramètre mac manquant'}), 400
    if mac not in macs_en_attente:
        return jsonify({'success': False, 'error': 'MAC non présente en attente'}), 400

    # Construire la configuration à sauvegarder
    config = {
        'id': data.get('id'),
        'lat': data.get('lat'),
        'lng': data.get('lng')
    }
    BASE_DE_DONNEES_MACS[mac] = config
    save_db(BASE_DE_DONNEES_MACS)
    macs_en_attente.discard(mac)

    # Publier la configuration immédiatement sur MQTT
    topic_reponse = f"systeme/appareillage/config/{mac}"
    try:
        if mqtt_client:
            mqtt_client.publish(topic_reponse, json.dumps(config))
    except Exception:
        app.logger.exception('Erreur lors de la publication MQTT de la config validée')

    return jsonify({'success': True, 'mac': mac, 'config': config})


# API pour statistiques et historique
@app.route('/api/stats', methods=['GET'])
@login_required
def api_stats():
    """Retourne les statistiques de remplissage du parc."""
    with donnees_lock:
        data = dict(donnees_actuelles)
    
    if not data:
        return jsonify({
            'total_bins': 0,
            'avg_fill': 0,
            'max_fill': 0,
            'min_fill': 0,
            'critical_count': 0,
            'warning_count': 0,
            'ok_count': 0
        })
    
    def estimate_fill(distance):
        if distance is None or distance == '':
            return 0
        try:
            d = float(distance)
            fullAt = 5
            emptyAt = 40
            ratio = ((emptyAt - d) / (emptyAt - fullAt)) * 100
            return max(0, min(100, round(ratio)))
        except:
            return 0
    
    fills = []
    critical = 0
    warning = 0
    ok = 0
    
    for bin_id, info in data.items():
        fill = estimate_fill(info.get('distance'))
        fills.append(fill)
        msg = info.get('message', '').lower()
        if msg in ['deborde', 'débordé']:
            critical += 1
        elif msg in ['assez rempli', 'assez_rempli']:
            warning += 1
        else:
            ok += 1
    
    avg_fill = round(sum(fills) / len(fills)) if fills else 0
    max_fill = max(fills) if fills else 0
    min_fill = min(fills) if fills else 0
    
    return jsonify({
        'total_bins': len(data),
        'avg_fill': avg_fill,
        'max_fill': max_fill,
        'min_fill': min_fill,
        'critical_count': critical,
        'warning_count': warning,
        'ok_count': ok
    })


@app.route('/api/historique', methods=['GET'])
@login_required
def api_historique():
    """Retourne les 50 derniers événements de l'historique."""
    with historique_lock:
        return jsonify(list(reversed(historique[-50:])))


@app.route('/stream')
def stream():
    q = queue.Queue()
    register_client(q)
    def event_stream():
        try:
            with donnees_lock:
                initial = dict(donnees_actuelles)
            yield 'data: %s\n\n' % json.dumps(initial)
            while True:
                try:
                    item = q.get(timeout=15)
                    yield 'data: %s\n\n' % item
                except queue.Empty:
                    yield ': keep-alive\n\n'
        finally:
            unregister_client(q)
    return Response(event_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    init_mqtt_connection()
    app.run(host='0.0.0.0', port=5000, debug=False)