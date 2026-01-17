#!/usr/bin/env python3
"""
Script de prueba para verificar si Essentia está instalado y funciona correctamente.
"""

import sys
from pathlib import Path

def test_essentia():
    """Prueba si Essentia está disponible y funciona."""
    print("=" * 60)
    print("🔍 PRUEBA DE ESSENTIA")
    print("=" * 60)
    print()
    
    # 1. Verificar importación
    print("1️⃣  Verificando importación de Essentia...")
    try:
        import essentia.standard as es
        print("   ✅ Essentia importado correctamente")
    except ImportError as e:
        print(f"   ❌ Error al importar Essentia: {e}")
        print()
        print("💡 Para instalar Essentia, ejecuta:")
        print("   pip install essentia")
        print()
        print("   Nota: Essentia puede requerir dependencias adicionales del sistema.")
        print("   Consulta: https://essentia.upf.edu/documentation/installing.html")
        return False
    except Exception as e:
        print(f"   ❌ Error inesperado: {e}")
        return False
    
    print()
    
    # 2. Verificar funciones básicas
    print("2️⃣  Verificando funciones básicas...")
    try:
        # Verificar que MonoLoader existe
        loader = es.MonoLoader
        print("   ✅ MonoLoader disponible")
        
        # Verificar que RhythmExtractor2013 existe
        rhythm_extractor = es.RhythmExtractor2013
        print("   ✅ RhythmExtractor2013 disponible")
        
        # Verificar que KeyExtractor existe
        key_extractor = es.KeyExtractor
        print("   ✅ KeyExtractor disponible")
        
        # Verificar que SpectralCentroid existe (puede no estar disponible en todas las versiones)
        try:
            spectral_centroid = es.SpectralCentroid
            print("   ✅ SpectralCentroid disponible")
        except AttributeError:
            print("   ⚠️  SpectralCentroid no disponible (opcional, no es crítico)")
        
        # Verificar si TaggerMusicNN está disponible (opcional)
        try:
            tagger = es.TaggerMusicNN
            print("   ✅ TaggerMusicNN disponible (modelo preentrenado)")
        except AttributeError:
            print("   ⚠️  TaggerMusicNN no disponible (modelos preentrenados no instalados)")
            print("      Esto es opcional, el análisis básico funcionará igual")
        
    except Exception as e:
        print(f"   ❌ Error al verificar funciones: {e}")
        return False
    
    print()
    
    # 3. Probar con un archivo de audio (si se proporciona)
    if len(sys.argv) > 1:
        audio_file = Path(sys.argv[1])
        if audio_file.exists():
            print(f"3️⃣  Probando análisis de audio: {audio_file.name}")
            try:
                # Cargar audio
                loader = es.MonoLoader(filename=str(audio_file))
                audio = loader()
                print(f"   ✅ Audio cargado: {len(audio)} muestras")
                
                # Extraer tempo
                rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
                bpm, beats, beats_confidence, _, beats_intervals = rhythm_extractor(audio)
                print(f"   ✅ Tempo detectado: {bpm:.1f} BPM")
                
                # Extraer key
                key_extractor = es.KeyExtractor()
                key, scale, strength = key_extractor(audio)
                print(f"   ✅ Tonalidad detectada: {key} {scale} (confianza: {strength:.2f})")
                
                # Extraer características espectrales (opcional)
                try:
                    spectral_centroid = es.SpectralCentroid()
                    centroid = spectral_centroid(audio)
                    avg_centroid = float(sum(centroid) / len(centroid)) if len(centroid) > 0 else 0
                    print(f"   ✅ Centroide espectral: {avg_centroid:.1f} Hz")
                except (AttributeError, Exception):
                    print("   ⚠️  SpectralCentroid no disponible (opcional)")
                
                # Intentar usar TaggerMusicNN si está disponible
                try:
                    tagger = es.TaggerMusicNN()
                    predictions = tagger(audio)
                    print(f"   ✅ TaggerMusicNN ejecutado correctamente")
                    if isinstance(predictions, dict):
                        print(f"      Predicciones: {len(predictions)} etiquetas")
                        # Mostrar las 5 primeras predicciones
                        sorted_preds = sorted(predictions.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)
                        print("      Top 5 etiquetas:")
                        for i, (tag, value) in enumerate(sorted_preds[:5], 1):
                            print(f"         {i}. {tag}: {value}")
                except Exception as e:
                    print(f"   ⚠️  TaggerMusicNN no disponible o error: {e}")
                
                print()
                print("   ✅ Análisis de audio completado correctamente")
                
            except Exception as e:
                print(f"   ❌ Error al analizar audio: {e}")
                import traceback
                traceback.print_exc()
                return False
        else:
            print(f"   ⚠️  Archivo no encontrado: {audio_file}")
    else:
        print("3️⃣  Prueba de análisis de audio: OMITIDA")
        print("   💡 Para probar con un archivo de audio, ejecuta:")
        print("      python test_essentia.py <ruta_al_archivo.mp3>")
    
    print()
    print("=" * 60)
    print("✅ ESSENTIA ESTÁ DISPONIBLE Y FUNCIONANDO")
    print("=" * 60)
    return True


if __name__ == '__main__':
    success = test_essentia()
    sys.exit(0 if success else 1)

