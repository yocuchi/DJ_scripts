import os
import json
import numpy as np
import threading
from typing import Optional, List, Tuple

# Configurar TensorFlow para reducir verbosidad de logs
# Solo mostrar errores críticos, una línea por ejecución
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # 0=all, 1=info, 2=warnings, 3=errors only
os.environ['TF_CPP_MIN_VLOG_LEVEL'] = '3'  # Desactivar logs verbosos

try:
    import essentia.standard as es
    ESSENTIA_AVAILABLE = True
except ImportError:
    ESSENTIA_AVAILABLE = False

# Variables globales para el modelo (singleton)
_model_path = None
_json_path = None
_classes = None
_predictor = None
_model_loading = False
_model_loaded = False
_model_lock = threading.Lock()

def _get_model_paths():
    """Obtiene las rutas de los archivos del modelo."""
    global _model_path, _json_path
    if _model_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(script_dir, 'essentia', 'tf_models')
        _model_path = os.path.join(models_dir, 'discogs-effnet-bs64-1.pb')
        _json_path = os.path.join(models_dir, 'genre_discogs400-discogs-effnet-1.json')
    return _model_path, _json_path

def _load_classes():
    """Carga las clases del modelo desde el JSON."""
    global _classes
    if _classes is None:
        _, json_path = _get_model_paths()
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    metadata = json.load(f)
                    if 'classes' in metadata:
                        _classes = metadata['classes']
            except Exception as e:
                print(f"Error leyendo metadatos del modelo: {e}")
                _classes = []
        else:
            print(f"Metadatos del modelo no encontrados en: {json_path}")
            _classes = []
    return _classes

def _load_predictor():
    """Carga el predictor de TensorFlow (singleton, thread-safe)."""
    global _predictor, _model_loading, _model_loaded
    
    # Si ya está cargado, devolverlo
    if _predictor is not None:
        return _predictor
    
    # Si está cargando, esperar
    if _model_loading:
        while _model_loading:
            threading.Event().wait(0.1)
        return _predictor
    
    # Cargar el modelo
    with _model_lock:
        if _predictor is not None:  # Doble verificación
            return _predictor
        
        _model_loading = True
        try:
            model_path, _ = _get_model_paths()
            if not os.path.exists(model_path):
                print(f"Modelo TF no encontrado en: {model_path}")
                _model_loading = False
                return None
            
            print("🔄 Cargando modelo TensorFlow/CUDA (esto puede tardar unos segundos)...")
            # Ejecutar Modelo TensorFlow
            # TensorflowPredictEffnetDiscogs realiza el preprocesado (Melspectrogram) internamente.
            # Apuntamos al output 'PartitionedCall' que contiene las predicciones de las 400 clases.
            _predictor = es.TensorflowPredictEffnetDiscogs(
                graphFilename=model_path, 
                output="PartitionedCall"
            )
            _model_loaded = True
            print("✅ Modelo TensorFlow/CUDA cargado correctamente")
        except Exception as e:
            print(f"❌ Error cargando modelo TensorFlow: {e}")
            _predictor = None
        finally:
            _model_loading = False
    
    return _predictor

def preload_model_async():
    """Precarga el modelo en un hilo separado (no bloqueante)."""
    def _preload():
        _load_classes()  # Cargar clases primero (rápido)
        _load_predictor()  # Cargar predictor (puede tardar con CUDA)
    
    thread = threading.Thread(target=_preload, daemon=True)
    thread.start()
    return thread

def is_model_ready():
    """Verifica si el modelo está listo para usar."""
    return _model_loaded and _predictor is not None

def predict_genre_discogs(file_path: str) -> Optional[List[Tuple[str, float]]]:
    """
    Predicts genre using Essentia TensorFlow models (Discogs-EffNet).
    Returns a list of (genre, probability) tuples sorted by probability descending.
    """
    if not ESSENTIA_AVAILABLE:
        print("Essentia no está disponible.")
        return None

    if not os.path.exists(file_path):
        print(f"Archivo no encontrado: {file_path}")
        return None

    # Cargar clases
    classes = _load_classes()
    if not classes:
        return None

    # Cargar predictor (lazy loading, thread-safe)
    predictor = _load_predictor()
    if predictor is None:
        return None

    try:
        # Cargar audio a 16kHz (requisito de Effnet)
        loader = es.MonoLoader(filename=file_path, sampleRate=16000)
        audio = loader()

        # Ejecutar predicción
        activations = predictor(audio)
        
        # Promediar sobre todos los parches/frames si es necesario
        if len(activations.shape) > 1:
            mean_activations = np.mean(activations, axis=0)
        else:
            mean_activations = activations.flatten()

        # Obtener top predictions
        sorted_indices = np.argsort(mean_activations)[::-1]
        
        results = []
        for i in range(min(5, len(classes))): # Top 5
            idx = sorted_indices[i]
            score = float(mean_activations[idx])
            if idx < len(classes):
                label = classes[idx]
                results.append((label, score))
        
        return results

    except Exception as e:
        print(f"Error durante la predicción TF: {e}")
        return None

def get_best_genre(file_path: str, min_confidence: float = 0.05) -> Optional[str]:
    """
    Wrapper simplificado para obtener el mejor género.
    Limpia la etiqueta de Discogs (e.g., 'Electronic---Techno' -> 'Techno').
    """
    predictions = predict_genre_discogs(file_path)
    if not predictions:
        return None
        
    best_genre, probability = predictions[0]
    
    if probability < min_confidence:
        return None
        
    # Limpiar formato Discogs "Category---Subcategory"
    if '---' in best_genre:
        # Preferir la subcategoría si es específica
        parts = best_genre.split('---')
        # Si la categoría principal es muy genérica (Electronic, Rock), tomamos la subcategoría
        # Pero a veces queremos mantener la estructura.
        # Por ahora devolvemos el formato "Subcategory" (parte final) para que encaje mejor como carpeta
        return parts[-1] 
    
    return best_genre

