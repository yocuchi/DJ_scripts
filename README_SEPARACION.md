# Separación de IDE y Procesos

Este documento explica cómo se ha separado la IDE de los procesos de descarga, permitiendo actualizar el código de los procesos sin modificar la IDE.

## ¿Cómo funciona?

### Arquitectura Anterior (Acoplada)

```
ide.py
  └─> import download_youtube  (importación directa)
      └─> Usa funciones directamente
```

**Problema**: Si cambias `download_youtube.py`, necesitas reiniciar la IDE.

### Arquitectura Nueva (Separada)

```
ide.py
  └─> process_interface.py
      └─> Ejecuta download_youtube.py como subproceso
          └─> Proceso independiente
```

**Ventaja**: Puedes actualizar `download_youtube.py` sin reiniciar la IDE.

## Uso

### Modo Separado (Recomendado)

```python
from process_interface import get_interface

# Obtener interfaz en modo separado (subprocesos)
interface = get_interface(use_direct_imports=False)

# Descargar una canción
result = interface.download_quick("https://youtube.com/watch?v=...")
if result['success']:
    print("✅ Descarga completada")
    print(result['output'])
else:
    print(f"❌ Error: {result['error']}")
```

### Modo Directo (Rápido, pero acoplado)

```python
from process_interface import get_interface

# Obtener interfaz en modo directo (imports)
interface = get_interface(use_direct_imports=True)

# Acceso directo a funciones
video_info = interface.get_video_info_direct(url)
songs = interface.get_database_direct().get_all_songs()
```

## Migración de la IDE

Para migrar `ide.py` a usar la interfaz separada:

### Antes:
```python
from download_youtube import download_audio, get_video_info

def download_with_metadata(self):
    video_info = get_video_info(url)
    download_audio(url, output_path, metadata)
```

### Después:
```python
from process_interface import get_interface

def download_with_metadata(self):
    interface = get_interface(use_direct_imports=False)
    
    # Para funciones que necesitan datos estructurados, 
    # usa modo directo temporalmente o crea wrappers
    interface_direct = get_interface(use_direct_imports=True)
    video_info = interface_direct.get_video_info_direct(url)
    
    # Para descargas, usa subproceso
    result = interface.download_with_metadata(url, genre, artist, year)
```

## Ventajas

1. **Actualización sin reinicio**: Puedes modificar `download_youtube.py` y los cambios se aplicarán en la próxima ejecución
2. **Aislamiento**: Los errores en los procesos no crashean la IDE
3. **Flexibilidad**: Puedes cambiar entre modo directo y separado según necesites

## Desventajas

1. **Rendimiento**: Los subprocesos son ligeramente más lentos que los imports directos
2. **Complejidad**: Algunas funciones que devuelven objetos complejos requieren wrappers adicionales

## Recomendación

- **Para desarrollo**: Usa `use_direct_imports=True` (más rápido, fácil de debuggear)
- **Para producción**: Usa `use_direct_imports=False` (separación completa, permite actualizar procesos)

## Próximos Pasos

Para una separación completa, considera:

1. Crear scripts wrapper que devuelvan JSON para funciones complejas
2. Implementar un sistema de mensajes/cola para comunicación asíncrona
3. Crear una API REST local para comunicación más estructurada

