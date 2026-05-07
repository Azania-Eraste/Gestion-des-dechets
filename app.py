from flask import Flask, request, jsonify, render_template, Response
import threading
import math
import queue
import json
import time

app = Flask(__name__)

# tentative d'activer CORS si installé (optionnel)
try:
    from flask_cors import CORS
    CORS(app)
except Exception:
    pass

# On utilise un dictionnaire pour stocker les deux valeurs (prototype)
donnees_actuelles = {"distance": 0, "message": "En attente..."}
# Verrou pour protéger les accès concurrents à l'état global
donnees_lock = threading.Lock()
# Liste de queues pour diffuser les mises à jour aux clients SSE
clients = []
clients_lock = threading.Lock()


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
        # parcourir une copie pour éviter modification pendant itération
        for q in list(clients):
            try:
                q.put_nowait(text)
            except Exception:
                try:
                    clients.remove(q)
                except Exception:
                    pass


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/update', methods=['POST'])
def update():
    """Endpoint utilisé par l'ESP32 pour poster JSON: {distance: number, message: string}.

    Cette fonction vérifie le Content-Type, parse le JSON de façon sûre,
    valide les types et met à jour l'état global sous verrou.
    """
    if not request.is_json:
        app.logger.warning('Requête non JSON reçue sur /update')
        return jsonify({"status": "error", "reason": "Content-Type must be application/json"}), 400

    try:
        data = request.get_json(silent=True)
    except Exception as e:
        app.logger.exception('Erreur lors du parsing JSON')
        return jsonify({"status": "error", "reason": "Malformed JSON"}), 400

    if not data:
        return jsonify({"status": "error", "reason": "Empty or invalid JSON"}), 400

    # Vérification des champs attendus
    if 'distance' not in data or 'message' not in data:
        return jsonify({"status": "error", "reason": "Missing keys: distance and message required"}), 400

    # Validation minimale des types
    distance = data['distance']
    message = data['message']

    if not isinstance(message, str):
        return jsonify({"status": "error", "reason": "message must be a string"}), 400

    # Normaliser le message
    message = message.strip().lower()

    # Accept numeric types for distance
    if isinstance(distance, (int, float)):
        if math.isfinite(distance) and distance >= 0 and distance <= 10000:
            # ok
            pass
        else:
            return jsonify({"status": "error", "reason": "distance out of range"}), 400
    else:
        # essayer de coerce depuis une chaîne contenant un nombre
        try:
            distance = float(distance)
            if not (math.isfinite(distance) and distance >= 0 and distance <= 10000):
                return jsonify({"status": "error", "reason": "distance out of range"}), 400
        except Exception:
            return jsonify({"status": "error", "reason": "distance must be numeric"}), 400

    # Mise à jour atomique de l'état
    with donnees_lock:
        donnees_actuelles['distance'] = distance
        donnees_actuelles['message'] = message

    app.logger.info('Reçu -> Distance: %s cm | Statut: %s', distance, message)

    # Diffuser la mise à jour aux clients SSE (non bloquant)
    try:
        with donnees_lock:
            snapshot = dict(donnees_actuelles)
        broadcast_update(snapshot)
    except Exception:
        app.logger.exception('Erreur lors de la diffusion SSE')

    return jsonify({"status": "success"}), 200


@app.route('/data', methods=['GET'])
def get_data():
    # Récupérer une copie sous verrou pour éviter des lectures partielles
    with donnees_lock:
        snapshot = dict(donnees_actuelles)
    return jsonify(snapshot)


@app.route('/stream')
def stream():
    """Endpoint SSE (Server-Sent Events) pour pousser les mises à jour aux clients.

    Le client ouvre une connexion EventSource sur `/stream` et reçoit des événements
    `data: {...}\n\n` contenant le snapshot JSON.
    """
    q = queue.Queue()
    register_client(q)

    def event_stream():
        try:
            # Envoyer immédiatement l'état courant
            with donnees_lock:
                initial = dict(donnees_actuelles)
            yield 'data: %s\n\n' % json.dumps(initial)

            while True:
                try:
                    item = q.get(timeout=15)
                    yield 'data: %s\n\n' % item
                except queue.Empty:
                    # keep-alive comment pour maintenir la connexion
                    yield ': keep-alive\n\n'
        finally:
            unregister_client(q)

    return Response(event_stream(), mimetype='text/event-stream')


if __name__ == '__main__':
    # Ne pas activer le debugger dans ce script par défaut
    app.run(host='0.0.0.0', port=5000, debug=False)