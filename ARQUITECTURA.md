# Arquitectura de DPI

## Organización actual

- `dpi/ciencia`: estadística, datación, cofecha, tendencias, autorregresión y cronologías.
- `dpi/medicion`: modelos, geometría, proyecciones, sesión, EW/LW, médula, intensidad y autodetección.
- `dpi/series`: modelo de series originales y editadas.
- `dpi/formatos`: lectores y escritores por familia de formatos.
- `dpi/infraestructura`: JSON e imágenes.
- `dpi/ui`: componentes Qt trasladados; aún conviven con interfaces históricas en la raíz.

Las importaciones históricas se conservan como adaptadores de compatibilidad.
Para código nuevo se prefieren los nombres de paquete. Los algoritmos y modelos
no deben importar interfaces Qt; la UI coordina los modelos, no al revés.

## Arranque y pruebas

Desde la raíz: `python -m dpi` o `python run_dpi.py`.
Para pruebas: `python -m unittest discover -s tests -v`.
En entornos sin pantalla, establecer `QT_QPA_PLATFORM=offscreen`.
Las pruebas de arranque necesitan las dependencias declaradas en requirements.txt.

## Trabajo pendiente

La migración de archivos no equivale por sí sola a desacoplamiento completo.
PanelCodatacion, PestanaImagen y VistaInteractiva todavía coordinan numerosas
operaciones; su descomposición funcional requiere pruebas de interacción Qt.
Los adaptadores históricos deben retirarse solo cuando se hayan migrado sus
consumidores y se haya verificado la distribución en Windows y Linux.
