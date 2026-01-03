# 🎨 Cómo ver emojis en la GUI en WSL/Linux

La GUI ahora detecta automáticamente fuentes con soporte de emojis, pero para que funcionen correctamente necesitas instalar fuentes de emojis en tu sistema.

## Instalación rápida

Ejecuta el script de instalación:

```bash
./install_emoji_fonts.sh
```

Este script detectará tu distribución y instalará las fuentes necesarias automáticamente.

## Instalación manual

### Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y fonts-noto-color-emoji fonts-noto-emoji
fc-cache -f -v
```

### Fedora/RHEL:

```bash
sudo dnf install -y google-noto-emoji-fonts google-noto-color-emoji-fonts
fc-cache -f -v
```

### Arch Linux:

```bash
sudo pacman -S noto-fonts-emoji
fc-cache -f -v
```

## Verificar instalación

Para verificar que las fuentes están instaladas:

```bash
fc-list : family | grep -i emoji
```

Deberías ver algo como:
- `Noto Color Emoji`
- `Noto Emoji`

## Reiniciar la aplicación

Después de instalar las fuentes, reinicia la GUI:

```bash
python3 ide.py
```

La aplicación detectará automáticamente las fuentes con soporte de emojis y las usará.

## Solución de problemas

### Los emojis aún no se ven:

1. **Verifica que las fuentes estén instaladas:**
   ```bash
   fc-list : family | grep -i emoji
   ```

2. **Actualiza la caché de fuentes:**
   ```bash
   fc-cache -f -v
   ```

3. **Reinicia WSL:**
   ```powershell
   # Desde PowerShell de Windows
   wsl --shutdown
   # Luego reinicia WSL
   ```

4. **Verifica que el servidor X11 esté funcionando:**
   ```bash
   echo $DISPLAY
   xset q
   ```

### La aplicación no detecta las fuentes:

La aplicación intenta detectar automáticamente fuentes con soporte de emojis. Si no encuentra ninguna, usará Arial como fallback. Puedes ver qué fuente está usando en la salida de la consola cuando inicias la aplicación.

## Fuentes soportadas

La aplicación busca estas fuentes (en orden de preferencia):

1. Noto Color Emoji
2. Noto Emoji
3. Apple Color Emoji
4. Segoe UI Emoji
5. DejaVu Sans
6. Liberation Sans
7. Arial (fallback)

Si tienes alguna de estas fuentes instalada, la aplicación la usará automáticamente.

