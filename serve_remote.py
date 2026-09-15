#!/usr/bin/env python3
"""
Punto de entrada para servir la app en un servidor remoto (la Oracle).

No sustituye a `python app.py`, que sigue siendo el modo local de escritorio.
Este arranque añade lo que falta para que la app pueda estar encendida en una
maquina que no esta delante de ti:

  * Servidor WSGI de verdad (waitress), sin el debugger de Werkzeug.
  * Escucha solo en 127.0.0.1: quien publica el servicio es `tailscale serve`,
    que anade TLS y solo deja entrar a los dispositivos de la tailnet.
  * Autenticacion por identidad de Tailscale: `tailscale serve` inyecta la
    cabecera Tailscale-User-Login con el correo del usuario que hace la
    peticion. Si falta la cabecera, la peticion no viene de la tailnet.
  * Modo publico: desactiva los endpoints que administran la maquina
    (explorador de ficheros, escritura del .env, reinicios, pip install...).
    Esa configuracion se toca por SSH, no desde la web.
  * SECRET_KEY estable y cabeceras CORS retiradas.

Se configura por entorno; ver dj-scripts.env.example.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _flag(name: str, default: str = '1') -> bool:
    return (os.getenv(name, default) or '').strip().lower() in ('1', 'true', 'yes', 'on')


BIND_HOST = os.getenv('DJ_BIND_HOST', '127.0.0.1')
BIND_PORT = int(os.getenv('DJ_BIND_PORT', '5001'))
PUBLIC_MODE = _flag('DJ_PUBLIC_MODE', '1')
REQUIRE_IDENTITY = _flag('DJ_REQUIRE_IDENTITY', '1')
# Correos de Tailscale con acceso (vacio = cualquier usuario de la tailnet)
ALLOWED_USERS = {
    u.strip().lower()
    for u in (os.getenv('DJ_ALLOWED_USERS', '') or '').split(',')
    if u.strip()
}

# Endpoints que administran la maquina, no la musica. Bloqueados en modo publico.
BLOCKED = {
    ('POST', '/api/config'),
    ('POST', '/api/config/reload'),
    ('POST', '/api/config/restart'),
    ('POST', '/api/config/reset-db'),
    ('POST', '/api/config/yt-dlp-update'),
    ('POST', '/api/config/ffmpeg-install'),
    ('POST', '/api/import/folder'),
    ('GET', '/api/browse'),
}

# Claves del .env que no deben salir por la web ni enmascaradas a medias
SECRET_CONFIG_KEYS = ('LASTFM_API_KEY', 'ACOUSTID_API_KEY')

# Importar la app despues de leer el entorno (app.py resuelve la BD al importarse)
import app as dj_app  # noqa: E402

flask_app = dj_app.app

_secret = os.getenv('DJ_SECRET_KEY', '').strip()
if _secret:
    flask_app.config['SECRET_KEY'] = _secret
elif PUBLIC_MODE:
    print('⚠️  DJ_SECRET_KEY sin definir: las sesiones se invalidaran al reiniciar')


@flask_app.before_request
def _guard():
    from flask import request, jsonify

    # 1) Identidad: `tailscale serve` firma cada peticion con el correo del usuario.
    if REQUIRE_IDENTITY:
        login = (request.headers.get('Tailscale-User-Login') or '').strip().lower()
        if not login:
            return jsonify({
                'success': False,
                'error': 'Acceso solo desde la tailnet (falta identidad de Tailscale)'
            }), 403
        if ALLOWED_USERS and login not in ALLOWED_USERS:
            return jsonify({
                'success': False,
                'error': f'Usuario no autorizado: {login}'
            }), 403

    # 2) Modo publico: la administracion de la maquina no se expone.
    if PUBLIC_MODE:
        path = request.path.rstrip('/') or '/'
        if (request.method, path) in BLOCKED:
            return jsonify({
                'success': False,
                'error': 'Deshabilitado en modo remoto: se configura por SSH'
            }), 403
    return None


@flask_app.after_request
def _mask_secrets(response):
    """El GET /api/config devuelve el .env: no dejar salir las claves de API."""
    from flask import request

    if request.path.rstrip('/') != '/api/config' or request.method != 'GET':
        return response
    if not response.is_json:
        return response
    try:
        payload = response.get_json()
        config = (payload or {}).get('config') or {}
        for key in SECRET_CONFIG_KEYS:
            if config.get(key):
                config[key] = '********'
        response.set_data(json.dumps(payload))
    except Exception:
        # Ante la duda, no devolver el cuerpo original sin enmascarar
        response.set_data(json.dumps({'success': False, 'error': 'config no disponible'}))
    return response


class HardenHeaders:
    """
    Middleware WSGI: se ejecuta despues de Flask, asi que puede retirar las
    cabeceras que flask-cors pone en todas las respuestas (CORS(app) publica
    Access-Control-Allow-Origin: *). La PWA es del mismo origen y no las
    necesita.
    """

    STRIP = (
        'access-control-allow-origin',
        'access-control-allow-headers',
        'access-control-allow-methods',
        'access-control-expose-headers',
        'access-control-allow-credentials',
    )

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        def _start(status, headers, exc_info=None):
            headers = [(k, v) for (k, v) in headers if k.lower() not in self.STRIP]
            headers.append(('X-Content-Type-Options', 'nosniff'))
            headers.append(('Referrer-Policy', 'no-referrer'))
            headers.append(('X-Frame-Options', 'SAMEORIGIN'))
            return start_response(status, headers, exc_info)

        return self.wsgi_app(environ, _start)


application = HardenHeaders(flask_app.wsgi_app)
flask_app.wsgi_app = application


def main():
    from waitress import serve

    print('🎧 DJ scripts en modo remoto')
    print(f'   bind .............. {BIND_HOST}:{BIND_PORT}')
    print(f'   modo publico ...... {"si" if PUBLIC_MODE else "no"}')
    print(f'   exige identidad ... {"si" if REQUIRE_IDENTITY else "no"}')
    print(f'   usuarios .......... {", ".join(sorted(ALLOWED_USERS)) or "cualquiera de la tailnet"}')
    print(f'   biblioteca ........ {dj_app.MUSIC_FOLDER}')
    serve(flask_app, host=BIND_HOST, port=BIND_PORT, threads=8, ident='dj-scripts')


if __name__ == '__main__':
    main()
