# Blue Ant KI Portfolio-Dashboard

Dieses Projekt ist eine integrierte, containerisierte Webanwendung zur intelligenten Analyse von Projekt- und Portfolio-Daten aus dem Projektmanagementsystem **Blue Ant** mittels lokaler/universitärer **Ollama LLM (Large Language Model) Instanzen**. 


---

## 📂 Systemarchitektur & Datenfluss

Das System wurde nach modernen Software-Design-Richtlinien modular und lose gekoppelt aufgebaut. 

Das folgende Ablaufdiagramm beschreibt den Datenfluss bei einer Portfolio- bzw. Projektanalyse:

<img width="481" height="552" alt="Ablaufdiagramm" src="https://github.com/user-attachments/assets/6531c20d-2f2d-46b8-96b5-9be8504854fd" />

---


## 🛠️ Technologien & Bibliotheken

* **Backend**: Python 3.10, FastAPI, Uvicorn, HTTPX, PyYAML
* **Frontend**: HTML5, CSS3 (Vanilla CSS variables), Javascript (Vanilla ES6), Chart.js, FontAwesome 6
* **Infrastruktur & QA**: Docker, Docker Compose, Python Unittest

---

## 🚀 Installation & Inbetriebnahme (Docker)

### Voraussetzungen
* Installiertes **Docker Desktop** auf Ihrem System.

### Starten der Anwendung
1. Klonen oder kopieren Sie das Projektverzeichnis auf Ihren Rechner.
2. Öffnen Sie ein Terminal (PowerShell / CMD) im Projektordner.
3. Starten Sie den Docker-Container mit folgendem Befehl:
   ```bash
   docker compose up --build -d
   ```
4. Die Anwendung ist nun unter **`http://localhost:8000`** in Ihrem Browser erreichbar.

---

## ⚙️ Einrichtung der API-Verbindung

Um die echten Daten Ihrer Hochschule anzuzeigen, müssen Sie das Dashboard konfigurieren:

1. **Server-URL einstellen**:
   - Gehen Sie im Dashboard in den Tab **"Einstellungen"**.
   - Tragen Sie als **Blue Ant Service-Basis-URL** ihre Adresse ein.
   - Passen Sie ggf. die **Ollama-Verbindung** an (z. B. `http://hpc-node:11434` und den Modellnamen wie `llama3`).
   - Klicken Sie auf **"Einstellungen speichern"**.

2. **API-Schlüssel hinterlegen**:
   - Klicken Sie oben rechts auf **"API-Schlüssel festlegen"**.
   - Fügen Sie Ihren persönlichen **Blue Ant REST API-Token** (aus Ihren Profileinstellungen in Blue Ant) und optional den **Ollama-API-Schlüssel** ein.
   - Klicken Sie auf **"Schlüssel speichern"**.

---

## 🧪 Automatisierte Tests ausführen

Führen Sie die Tests direkt in Ihrer lokalen Python-Umgebung aus:

```bash
python -m unittest tests/test_analysis.py
```
