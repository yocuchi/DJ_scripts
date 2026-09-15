# Despliegue en la Oracle (`orac` / `chichi`)

La app corre 24/7 en la instancia Oracle, accesible **solo desde la tailnet**.
No hay ningún puerto abierto a internet: el servicio escucha en `127.0.0.1` y
quien lo publica es `tailscale serve`.

## La máquina

| | |
|---|---|
| Host SSH | `orac` (= `chichi`, `100.124.105.22`) |
| Arquitectura | **aarch64** (Ampere A1), 1 vCPU, 5,8 GB RAM |
| SO | Ubuntu 24.04 |
| Código | `/opt/dj-scripts` |
| Biblioteca | `/srv/dj-music/DJ_SCRIPTS_LIB` |
| URL | `https://chichi.tail74da15.ts.net:8443/` (**https**, puerto 8443) |

Ser ARM con 1 vCPU es lo que decide `requirements-server.txt`: **sin essentia
ni TensorFlow**, porque no hay ruedas para aarch64 y con un solo core el
análisis de audio no es viable. En su lugar, la identificación por huella
acústica (`fpcalc`/AcoustID + género de MusicBrainz) cubre ese hueco sin
apenas coste: ~0.3s y ~30MB de RAM por canción, probado en esta misma
máquina. Ver `ACOUSTID_API_KEY` y `--test-acoustid` en `download_youtube.py`.

## Qué protege qué

El `app.py` de escritorio no es seguro de exponer: `/api/browse` lista
cualquier directorio, `POST /api/config` escribe cualquier clave en el `.env`
y `CORS(app)` publica `Access-Control-Allow-Origin: *`. Por eso el servidor
**no arranca `app.py`**, sino `serve_remote.py`, que envuelve la misma app:

1. **waitress** en lugar del servidor de desarrollo de Werkzeug (cuyo debugger
   es ejecución remota de código).
2. **`127.0.0.1` únicamente.** Ni la IP de la tailnet: solo loopback.
3. **`tailscale serve`** delante. Restringe el acceso a los dispositivos de la
   tailnet e inyecta la cabecera `Tailscale-User-Login` con el correo de quien
   hace la petición. Un cliente **no puede falsificarla**: `serve` sobreescribe
   la que venga de fuera (verificado).
4. **`DJ_REQUIRE_IDENTITY`**: sin esa cabecera, 403. Con `DJ_ALLOWED_USERS`,
   solo los correos de la lista.
5. **`DJ_PUBLIC_MODE`**: 403 en los endpoints que administran la máquina y no
   la música — `/api/browse`, `POST /api/config`, `reload`, `restart`,
   `reset-db`, `yt-dlp-update`, `ffmpeg-install`, `import/folder`. Al cerrar la
   escritura del `.env`, `MUSIC_FOLDER` ya no se puede mover, y con eso la
   comprobación de contención de `/api/database/file` deja de ser eludible.
6. `LASTFM_API_KEY` enmascarada en el `GET /api/config`, cabeceras CORS
   retiradas, `SECRET_KEY` estable y `ProtectSystem`/`ProtectHome` en la unit.

## Rehacer el despliegue

```bash
# 1. Sistema
ssh orac 'sudo apt-get install -y ffmpeg python3-venv rsync libchromaprint-tools'
ssh orac 'sudo mkdir -p /opt/dj-scripts/{logs,home} /srv/dj-music && sudo chown -R ubuntu:ubuntu /opt/dj-scripts /srv/dj-music'

# 2. Código (solo lo commiteado, sin .env ni MUSIC/)
git archive --format=tar HEAD | ssh orac 'tar -x -C /opt/dj-scripts'

# 3. Entorno virtual
ssh orac 'cd /opt/dj-scripts && python3 -m venv .venv && .venv/bin/pip install -r requirements-server.txt'

# 4. Configuración (a partir de deploy/dj-scripts.env.example)
#    DJ_SECRET_KEY con: openssl rand -hex 32
ssh orac 'chmod 600 /opt/dj-scripts/.env'

# 5. Biblioteca. Ojo: el rsync de macOS es openrsync 2.6.9 y no acepta
#    --info=stats2 ni -a con xattrs; usar -rlptz.
rsync -rlptz --exclude '.youtube_music.db*' --exclude '.DS_Store' \
  "$MUSIC_FOLDER/" orac:/srv/dj-music/DJ_SCRIPTS_LIB/

# 6. La BD se copia con backup consistente, nunca con cp: la app local la
#    está escribiendo.
python3 -c "
import sqlite3
s = sqlite3.connect('file:$DB_PATH?mode=ro', uri=True)
d = sqlite3.connect('/tmp/db.sqlite')
with d: s.backup(d)"
scp /tmp/db.sqlite orac:/srv/dj-music/DJ_SCRIPTS_LIB/.youtube_music.db

# 7. Servicio
ssh orac 'sudo cp /opt/dj-scripts/deploy/dj-scripts.service /etc/systemd/system/ \
  && sudo systemctl daemon-reload && sudo systemctl enable --now dj-scripts'

# 8. Publicar en la tailnet con TLS
ssh orac 'sudo tailscale serve --bg --https=8443 http://127.0.0.1:5001'
```

## Comprobar que sigue bien

```bash
# La identidad es obligatoria (403 sin ella, 200 con ella)
ssh orac 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/'
ssh orac 'curl -s -o /dev/null -w "%{http_code}\n" -H "Tailscale-User-Login: yocuchi@gmail.com" http://127.0.0.1:5001/'

# No se pueden leer ficheros del sistema
ssh orac 'curl -s -H "Tailscale-User-Login: yocuchi@gmail.com" \
  --get --data-urlencode "path=/etc/passwd" http://127.0.0.1:5001/api/database/file'

ssh orac 'tail -20 /opt/dj-scripts/logs/server.log'
```

## HTTPS y los puertos

La app se publica en **`https://chichi.tail74da15.ts.net:8443/`**. Ojo con las
tres formas de equivocarse, que ya pasaron todas:

| URL | Qué es |
|---|---|
| `http://chichi.tail74da15.ts.net/` | **fantasy-web**, otro servicio. No es esto |
| `http://chichi.tail74da15.ts.net:8080/` | La configuración vieja, ya apagada |
| `http://chichi.tail74da15.ts.net:8443/` | **HTTP 400**: es un puerto HTTPS hablado en HTTP |

El 8443 exige `https://`. Si el navegador devuelve un 400 y el log de
`tailscaled` dice *"client sent an HTTP request to an HTTPS server"*, es
exactamente eso.

El certificado lo emite Tailscale por ACME, y **requiere que HTTPS
Certificates esté activado** en el admin del tailnet (DNS → HTTPS
Certificates). Mientras estuvo desactivado, `tailscale serve --https` aceptaba
la configuración pero no llegaba a escuchar en el puerto: `serve status`
mostraba la entrada y `ss -tlnp` no mostraba nada. Comprobación rápida:

```bash
ssh orac 'sudo tailscale cert --cert-file /tmp/t.crt --key-file /tmp/t.key chichi.tail74da15.ts.net'
```

Sin HTTPS no basta con que el tráfico vaya cifrado (WireGuard ya lo cifra):
el navegador necesita un origen seguro o **no registra el service worker**, y
sin él la PWA no se instala.

## Rutas de la biblioteca entre máquinas

La BD se comparte entre el PC, WSL, el Mac y ahora el servidor, así que la
misma pista aparece con cuatro prefijos distintos. `_normalize_file_path_from_db`
recoloca cualquiera de ellos sobre el `MUSIC_FOLDER` local, y si el nombre no
coincide exactamente hace una última pasada ignorando mayúsculas y la forma
Unicode: macOS guarda los nombres en NFD y es insensible a mayúsculas, Linux es
sensible a las dos cosas. Sin eso, 43 de las 588 pistas daban 404 en el
servidor. Cobertura actual: **588/588**.

## Cookies de YouTube

**No están en el servidor, a propósito.** `youtube_cookies.txt` es la sesión de
tu cuenta de Google; copiarla a una máquina encendida en internet convierte
cualquier fallo del servidor en un problema de tu cuenta. Sin ellas, las
descargas desde una IP de datacenter fallarán más a menudo. Si decides
ponerlas, que sea con `chmod 600` y con `YOUTUBE_COOKIES_FILE` en el `.env`.
