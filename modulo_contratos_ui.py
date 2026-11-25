"""Contratos de composición de las vistas Qt."""


def instalar_controles(destino, controles):
    """Mantiene los nombres públicos históricos al componer una vista.

    La fábrica no recibe este destino; solo devuelve sus controles.
    """
    for nombre, control in vars(controles).items():
        setattr(destino, nombre, control)
