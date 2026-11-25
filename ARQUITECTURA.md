# Arquitectura de DPI

## Organización actual

- `dpi/ciencia`: estadística, datación, cofecha, tendencias, autorregresión y cronologías.
- `dpi/medicion`: modelos, geometría, proyecciones, sesión, EW/LW, médula, intensidad y autodetección.
- `dpi/series`: modelo de series originales y editadas.
- `dpi/formatos`: lectores y escritores por familia de formatos.
- `dpi/infraestructura`: JSON e imágenes.
- `dpi/ui`: componentes Qt trasladados; aún conviven con interfaces históricas en la raíz.

Los adaptadores históricos de medición, series, infraestructura, formatos y constantes fueron retirados. Las interfaces principales aún conservan sus nombres históricos.
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
El estado temporal de las herramientas está agrupado en objetos independientes; las operaciones Qt todavía reciben la vista. Falta verificar la distribución en Windows y Linux.
