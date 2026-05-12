import os
import json
import time
import shutil
import requests
import git
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

app = Flask(__name__)

# ========== CONFIGURACIÓN ==========
DOMINIOS_OFICIALES = [
    "pjud.cl", "sernac.cl", "cmfchile.cl", "subtel.gob.cl",
    "anci.gob.cl", "bcentral.cl", "superdesalud.gob.cl", "bcn.cl", "cplt.cl"
]

PAL_CLAVE_DP = [
    "protección de datos", "privacidad", "habeas data", "ley 19.628", "datos personales",
    "consentimiento", "seguridad de la información", "datos sensibles", "encargado de datos",
    "bases de datos personales", "derechos arco", "transferencia internacional de datos"
]

PAL_CLAVE_CONSUMO = [
    "consumidor", "sernac", "garantía legal", "cláusula abusiva", "publicidad engañosa",
    "producto defectuoso", "derecho a retracto", "proveedor", "servicios financieros",
    "tasa de interés", "comisión bancaria", "crédito hipotecario", "crédito de consumo",
    "portabilidad numérica", "facturación", "reclamación"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
}

# ========== FUNCIONES DE VERIFICACIÓN ==========
def es_fuente_oficial(url):
    from urllib.parse import urlparse
    dominio = urlparse(url).netloc.lower()
    dominio = dominio.replace("www.", "")
    return any(dominio == oficial or dominio.endswith("." + oficial) for oficial in DOMINIOS_OFICIALES)

# ========== BUSCADORES ==========
def buscar_sernac():
    # Feed RSS del SERNAC (actualmente no funciona, se deja para futuro)
    return []

def buscar_cmf_normativa():
    """Busca normativas y circulares en la CMF (funciona correctamente)"""
    novedades = []
    url = "https://www.cmfchile.cl/portal/principal/613/w3-propertyvalue-29580.html"
    try:
        response = requests.get(url, timeout=10, headers=HEADERS)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            titulo = link.get_text(strip=True)
            enlace = link['href']
            if titulo:
                if ('.pdf' in enlace or 
                    'circular' in titulo.lower() or 
                    'norma' in titulo.lower() or 
                    'capítulo' in titulo.lower() or
                    'recopilación' in titulo.lower() or
                    'ley' in titulo.lower()):
                    enlace_completo = urljoin(url, enlace)
                    novedades.append({
                        "titulo": titulo,
                        "url": enlace_completo,
                        "fecha": datetime.now().strftime("%Y-%m-%d"),
                        "contenido": titulo,
                        "fuente": "CMF Normativa"
                    })
                    if len(novedades) >= 10:
                        break
        return novedades
    except Exception:
        return []

def buscar_todas_fuentes():
    print("Buscando en CMF Normativa...")
    todas = buscar_cmf_normativa()
    time.sleep(1)
    return todas

# ========== CLASIFICACIÓN ==========
def clasificar_contenido(item):
    texto = (item["titulo"] + " " + item.get("contenido", "")).lower()
    score_dp = sum(1 for p in PAL_CLAVE_DP if p in texto)
    score_consumo = sum(1 for p in PAL_CLAVE_CONSUMO if p in texto)
    if item["fuente"] == "CMF Normativa" and score_dp == 0 and score_consumo == 0:
        return "ambos"
    if score_dp > score_consumo:
        return "datos_personales"
    elif score_consumo > score_dp:
        return "consumo"
    elif score_dp > 0 and score_consumo > 0:
        return "ambos"
    else:
        return "ninguno"

def verificar_autenticidad(novedad):
    if not es_fuente_oficial(novedad["url"]):
        return False
    if novedad["url"].endswith('.pdf'):
        return True
    if len(novedad.get("contenido", "")) < 10 and len(novedad.get("titulo", "")) < 10:
        return False
    return True

# ========== ACTUALIZACIÓN LOCAL Y GITHUB ==========
def generar_json(tema, novedades):
    archivo = f"actualizaciones_{tema}.json"
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(novedades, f, indent=2, ensure_ascii=False)
    print(f"✅ Generado {archivo} con {len(novedades)} novedades.")
    return archivo

def subir_a_github(repo_url, archivo_local, destino_en_repo, token, commit_msg):
    url_con_token = repo_url.replace("https://", f"https://{token}@")
    nombre_repo = repo_url.split("/")[-1].replace(".git", "")
    repo_path = os.path.join(os.getcwd(), f"temp_{nombre_repo}")
    try:
        if os.path.exists(repo_path):
            repo = git.Repo(repo_path)
            repo.remotes.origin.pull()
        else:
            repo = git.Repo.clone_from(url_con_token, repo_path, branch="main")
        destino_completo = os.path.join(repo_path, destino_en_repo)
        os.makedirs(os.path.dirname(destino_completo), exist_ok=True)
        shutil.copy2(archivo_local, destino_completo)
        repo.index.add([destino_en_repo])
        repo.index.commit(f"{commit_msg} - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        repo.remotes.origin.push()
        print(f"✅ Subido a {repo_url} -> {destino_en_repo}")
        # Limpiar clon temporal para ahorrar espacio
        shutil.rmtree(repo_path)
        return True
    except Exception as e:
        print(f"❌ Error subiendo a {repo_url}: {e}")
        return False

# ========== CICLO PRINCIPAL DE ACTUALIZACIÓN ==========
def ejecutar_actualizacion():
    """Ejecuta una ronda de búsqueda, genera JSON y sube a GitHub"""
    print(f"\n=== INICIANDO ACTUALIZACIÓN - {datetime.now()} ===\n")
    novedades_crudas = buscar_todas_fuentes()
    print(f"Total encontrado: {len(novedades_crudas)} novedades.\n")

    dp_items = []
    consumo_items = []

    for item in novedades_crudas:
        if not verificar_autenticidad(item):
            continue
        destino = clasificar_contenido(item)
        print(f"[{item['fuente']}] {item['titulo'][:60]}... → {destino}")
        if destino in ["datos_personales", "ambos"]:
            dp_items.append(item)
        if destino in ["consumo", "ambos"]:
            consumo_items.append(item)

    archivo_dp = None
    archivo_consumo = None
    if dp_items:
        archivo_dp = generar_json("datos_personales", dp_items)
    else:
        print("No hay novedades para Datos Personales")
    if consumo_items:
        archivo_consumo = generar_json("consumo", consumo_items)
    else:
        print("No hay novedades para Consumo")

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("⚠️ No se encontró GITHUB_TOKEN en .env. No se subirán archivos.")
        return

    if archivo_dp:
        subir_a_github(
            repo_url="https://github.com/Mariajardinera/OleOle.git",
            archivo_local=archivo_dp,
            destino_en_repo="datos/actualizaciones.json",
            token=token,
            commit_msg="Actualización automática de normativa (datos personales)"
        )
    if archivo_consumo:
        subir_a_github(
            repo_url="https://github.com/Mariajardinera/EMPTOR.git",
            archivo_local=archivo_consumo,
            destino_en_repo="datos/actualizaciones.json",
            token=token,
            commit_msg="Actualización automática de normativa (consumo)"
        )
    print(f"\n=== FIN DE LA ACTUALIZACIÓN - {datetime.now()} ===\n")

# ========== ENDPOINTS DEL SERVICIO WEB ==========
@app.route('/')
def home():
    """Raíz informativa: no ejecuta actualización automática"""
    return "Agente activo. Usa /update para ejecutar actualización.", 200

@app.route('/update')
def trigger_update():
    """Endpoint que activa manualmente la actualización (usado por cron gratuito)"""
    ejecutar_actualizacion()
    return "OK", 200

@app.route('/health')
def health():
    """Endpoint para health check de Render (no ejecuta actualización)"""
    return "Agente activo", 200

# ========== INICIO DEL SERVIDOR ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)