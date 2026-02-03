import sys
import os
import json
import numpy as np

# Configurar TensorFlow para reducir verbosidad de logs
# Solo mostrar errores críticos, una línea por ejecución
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # 0=all, 1=info, 2=warnings, 3=errors only
os.environ['TF_CPP_MIN_VLOG_LEVEL'] = '3'  # Desactivar logs verbosos

try:
    import essentia.standard as es
except ImportError:
    print("Error: Essentia no está instalado. Asegúrate de tenerlo instalado.")
    sys.exit(1)

def analyze_genre_tf(file_path):
    if not os.path.exists(file_path):
        print(f"Error: El archivo '{file_path}' no existe.")
        return

    # 1. Configurar rutas de modelos
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    models_dir = os.path.join(project_root, 'essentia', 'tf_models')
    
    # Modelos
    # Usamos el modelo 'discogs-effnet-bs64-1.pb' que contiene la red completa (incluida clasificación)
    # accesible a través del nodo PartitionedCall.
    model_name = 'discogs-effnet-bs64-1.pb'
    model_path = os.path.join(models_dir, model_name)
    
    # Metadata con los nombres de las clases (usamos el del clasificador 400 clases)
    json_name = 'genre_discogs400-discogs-effnet-1.json'
    json_path = os.path.join(models_dir, json_name)
    
    if not os.path.exists(model_path):
        print(f"Error: Falta el modelo en {model_path}")
        return
        
    classes = []
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            metadata = json.load(f)
            if 'classes' in metadata:
                classes = metadata['classes']
    
    print(f"Analizando: {file_path}")
    print("Iniciando inferencia...")

    try:
        # Paso 1: Cargar audio
        # Effnet Discogs requiere 16kHz
        loader = es.MonoLoader(filename=file_path, sampleRate=16000)
        audio = loader()

        # Paso 2: Ejecutar Modelo
        print("Ejecutando modelo TensorFlow...")
        # TensorflowPredictEffnetDiscogs realiza el preprocesado (Melspectrogram) internamente.
        # Apuntamos al output 'PartitionedCall' que contiene las predicciones de las 400 clases
        # en este grafo específico.
        predictor = es.TensorflowPredictEffnetDiscogs(
            graphFilename=model_path, 
            output="PartitionedCall"
        )
        activations = predictor(audio)
        
        # activations shape: [frames, 400]
        # print(f"Activations shape: {activations.shape}")

        # Paso 3: Agregar y Mostrar
        if len(activations.shape) > 1:
            mean_activations = np.mean(activations, axis=0)
        else:
            mean_activations = activations.flatten()

        print("\n--- Resultados (Top 10 Géneros Discogs) ---")
        
        sorted_indices = np.argsort(mean_activations)[::-1]
        
        for i in range(10):
            idx = sorted_indices[i]
            score = mean_activations[idx]
            
            label = f"Clase {idx}"
            if classes and idx < len(classes):
                label = classes[idx]
                
            print(f"{i+1}. {label}: {score:.2%}")

    except Exception as e:
        print(f"Error durante la predicción TF: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python extract_genre_tf.py <ruta_mp3>")
    else:
        analyze_genre_tf(sys.argv[1])
