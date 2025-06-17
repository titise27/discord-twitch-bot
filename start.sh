#!/bin/bash
# Donne les droits d'exécution au script (à faire une fois en local : chmod +x start.sh)

# Active l'environnement virtuel si besoin (optionnel)
# source /opt/venv/bin/activate

# Installe les dépendances (si tu veux forcer à chaque démarrage)
pip install -r requirements.txt

# Lance le bot
python main.py
