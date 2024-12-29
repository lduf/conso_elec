# main.py

import os
from multiprocessing import Process

def launch_streamlit():
    """Lance l'application Streamlit."""
    os.system("streamlit run front/streamlit_app.py")

def launch_dash():
    """Lance l'application Dash."""
    os.system("python dash_app/app.py")

if __name__ == "__main__":
    # Lancer Streamlit et Dash en parallèle
    streamlit_process = Process(target=launch_streamlit)
    dash_process = Process(target=launch_dash)

    # Démarrer les deux processus
    streamlit_process.start()
    dash_process.start()

    # Attendre que les deux processus terminent (optionnel)
    streamlit_process.join()
    dash_process.join()